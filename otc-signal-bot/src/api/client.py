"""PocketOption API Client – live WebSocket scaffolding + demo fallback."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from ..utils.logger import get_logger
from .exceptions import AuthenticationError, ConnectionError, DataFetchError
from .protocol import (
    DEFAULT_WS_URLS,
    ParsedSSID,
    build_auth_message,
    build_history_request,
    build_subscribe_message,
    candles_to_dataframe,
    extract_candles_from_history_payload,
    parse_socketio_packet,
    parse_ssid,
    timeframe_to_seconds,
)

logger = get_logger(__name__)


class PocketOptionClient:
    """
    Professional API client with:
      - Socket.IO-style WebSocket connection
      - SSID authentication
      - Historical candle requests (loadHistoryPeriod)
      - Graceful demo fallback when live is unavailable
    """

    def __init__(self, settings: Any):
        self.settings = settings
        self.demo_mode = getattr(settings, "DEMO_MODE", True)
        self.websocket = None
        self._connected = False
        self._authenticated = False
        self._pending_candles: Optional[List] = None
        self._candles_event = asyncio.Event()
        self._listener_task: Optional[asyncio.Task] = None
        self._ssid: Optional[ParsedSSID] = None

        raw_ssid = getattr(settings, "POCKETOPTION_SSID", None) or ""
        uid = getattr(settings, "POCKETOPTION_USER_ID", None)
        # Ignore placeholders from .env.example
        if raw_ssid and "your_" in raw_ssid.lower():
            raw_ssid = ""
        if raw_ssid:
            try:
                self._ssid = parse_ssid(raw_ssid)
                if uid and str(uid).isdigit() and not self._ssid.uid:
                    self._ssid.uid = int(uid)
                if self._ssid.is_demo is False:
                    self.demo_mode = False
            except Exception as e:
                logger.warning("Could not parse SSID: %s", e)
                self._ssid = None

        self.ws_urls = list(DEFAULT_WS_URLS)
        cfg_url = getattr(settings, "API_WS_URL", None)
        if cfg_url and "po.market" in str(cfg_url):
            self.ws_urls.insert(0, cfg_url)

    @property
    def is_connected(self) -> bool:
        return self._connected and self.websocket is not None

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    async def connect(self) -> bool:
        """Connect (+ optionally authenticate). Non-fatal in DEMO_MODE."""
        if self.demo_mode and not self._ssid:
            logger.info("DEMO_MODE – no SSID configured; skipping live WebSocket")
            self._connected = False
            return False

        last_err = None
        for url in self.ws_urls:
            try:
                logger.info("Connecting to %s …", url)
                self.websocket = await asyncio.wait_for(
                    websockets.connect(
                        url,
                        ping_interval=20,
                        ping_timeout=10,
                        open_timeout=12,
                        max_size=8 * 1024 * 1024,
                    ),
                    timeout=15,
                )
                self._connected = True
                self._listener_task = asyncio.create_task(self._listen_loop())
                await asyncio.sleep(0.3)
                try:
                    await self.websocket.send("40")
                except Exception:
                    pass

                if self._ssid:
                    ok = await self.authenticate()
                    if ok:
                        logger.info("✅ Connected & authenticated")
                        return True
                    logger.warning("Connected but authentication failed")
                else:
                    logger.info("✅ Connected (no SSID – limited functionality)")
                    return True
            except Exception as e:
                last_err = e
                logger.warning("Connection to %s failed: %s", url, e)
                self._connected = False
                self.websocket = None

        if self.demo_mode:
            logger.warning("Live connection failed; continuing in demo mode (%s)", last_err)
            return False
        raise ConnectionError(f"Connection failed: {last_err}")

    async def authenticate(self) -> bool:
        if not self._ssid:
            logger.error("No SSID available for authentication")
            return False
        if not self.is_connected:
            return False

        msg = build_auth_message(
            session=self._ssid.session,
            uid=self._ssid.uid,
            is_demo=self._ssid.is_demo,
            platform=self._ssid.platform,
            is_fast_history=self._ssid.is_fast_history,
            is_optimized=self._ssid.is_optimized,
        )
        try:
            await self.websocket.send(msg)
            await asyncio.sleep(1.0)
            self._authenticated = True
            logger.info(
                "Auth message sent for uid=%s demo=%s",
                self._ssid.uid,
                self._ssid.is_demo,
            )
            return True
        except Exception as e:
            logger.error("Authentication failed: %s", e)
            self._authenticated = False
            if not self.demo_mode:
                raise AuthenticationError(str(e)) from e
            return False

    async def get_candles(
        self,
        asset: str,
        timeframe: Any = "1m",
        count: int = 200,
        end_time: Optional[int] = None,
    ):
        """Request historical candles via loadHistoryPeriod."""
        import pandas as pd

        if not self.is_connected:
            raise DataFetchError("Not connected")

        period = timeframe_to_seconds(timeframe)
        offset = max(count * period, 9000)

        self._pending_candles = None
        self._candles_event.clear()

        try:
            await self.websocket.send(build_subscribe_message(asset, period))
            await asyncio.sleep(0.2)
        except Exception:
            pass

        req = build_history_request(asset, period, end_time=end_time, offset=offset)
        await self.websocket.send(req)
        logger.debug("Sent history request for %s period=%s", asset, period)

        try:
            await asyncio.wait_for(self._candles_event.wait(), timeout=12.0)
        except asyncio.TimeoutError:
            logger.warning("Candle request timed out for %s", asset)
            return pd.DataFrame()

        raw = self._pending_candles or []
        df = candles_to_dataframe(raw)
        if len(df) > count:
            df = df.iloc[-count:].reset_index(drop=True)
        return df

    async def _listen_loop(self) -> None:
        try:
            while self._connected and self.websocket:
                try:
                    raw = await self.websocket.recv()
                except ConnectionClosed:
                    logger.warning("WebSocket closed")
                    break
                except Exception as e:
                    logger.debug("Recv error: %s", e)
                    break

                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")

                if raw == "2":
                    try:
                        await self.websocket.send("3")
                    except Exception:
                        pass
                    continue

                event, data = parse_socketio_packet(raw)
                if event in (
                    "loadHistoryPeriod",
                    "candles",
                    "history",
                    "updateHistoryNewFast",
                    "updateHistoryNew",
                ):
                    candles = extract_candles_from_history_payload(data)
                    if candles:
                        self._pending_candles = candles
                        self._candles_event.set()
                elif event == "successauth" or (
                    isinstance(data, dict) and data.get("status") == "success"
                ):
                    self._authenticated = True
                    logger.info("Server confirmed authentication")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Listener stopped: %s", e)
        finally:
            self._connected = False

    async def disconnect(self) -> None:
        self._connected = False
        self._authenticated = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except Exception:
                pass
            self._listener_task = None
        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:
                pass
        self.websocket = None
        logger.info("Disconnected from PocketOption")

    async def close(self) -> None:
        await self.disconnect()

    async def send_message(self, message: Dict[str, Any]) -> bool:
        if not self.is_connected:
            return False
        try:
            await self.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error("Send failed: %s", e)
            return False
