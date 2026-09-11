"""Authentication Management"""
from __future__ import annotations

from typing import Optional

from ..utils.logger import get_logger
from .protocol import ParsedSSID, build_auth_message, parse_ssid

logger = get_logger(__name__)


class PocketOptionAuthenticator:
    """Parses SSID and builds auth frames for PocketOption."""

    def __init__(self, ssid: Optional[str] = None, user_id: Optional[str] = None):
        self.raw_ssid = ssid
        self.user_id = user_id
        self.parsed: Optional[ParsedSSID] = None
        self.is_authenticated = False

        if ssid:
            try:
                self.parsed = parse_ssid(ssid)
                if user_id and not self.parsed.uid:
                    self.parsed.uid = int(user_id)
            except Exception as e:
                logger.error("SSID parse error: %s", e)

    def build_auth_frame(self) -> Optional[str]:
        if not self.parsed:
            return None
        return build_auth_message(
            session=self.parsed.session,
            uid=self.parsed.uid,
            is_demo=self.parsed.is_demo,
            platform=self.parsed.platform,
            is_fast_history=self.parsed.is_fast_history,
            is_optimized=self.parsed.is_optimized,
        )

    def authenticate(self) -> bool:
        """Validate that we have enough credentials to attempt auth."""
        if not self.parsed or not self.parsed.session:
            logger.error("SSID session required")
            return False
        logger.info(
            "SSID ready (uid=%s demo=%s). Actual handshake is performed by PocketOptionClient.",
            self.parsed.uid,
            self.parsed.is_demo,
        )
        return True
