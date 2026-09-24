import pytest

from src.api.botv2_adapter import BotV2Client


class FakeSettings:
    DEMO_MODE = True
    POCKETOPTION_SSID = ""


class FakeBroker:
    async def buy(self, asset, amount, duration):
        assert asset == "EURUSD"
        assert amount == 10.0
        assert duration == 60
        return ("BROKER-TRADE-123", {"id": "BROKER-TRADE-123"})


@pytest.mark.asyncio
async def test_place_trade_exposes_broker_trade_id():
    client = BotV2Client(FakeSettings())
    client._client = FakeBroker()
    client._connected = True
    client._authenticated = True

    result = await client.place_trade(
        asset="EURUSD",
        direction="call",
        amount=10.0,
        duration=60,
    )

    assert result["success"] is True
    assert result["trade_id"] == "BROKER-TRADE-123"
