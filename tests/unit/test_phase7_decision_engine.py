from src.web.decision_engine import ProfessionalDecisionEngine


def test_phase7_call_decision_with_confluence():
    engine = ProfessionalDecisionEngine()
    result = engine.build(
        signal={"asset": "EURUSD_otc", "action": "CALL", "confidence": 88, "reason": "bullish confluence"},
        scanner={
            "asset": "EURUSD_otc", "strength": 90, "trend": "BULLISH",
            "momentum": "BULLISH", "macd_bias": "BULLISH", "confirmation_trend": "BULLISH",
            "regime": "TRENDING", "volatility_state": "NORMAL", "conflicts": [],
        },
        timeframe="1m", amount=10, balance=1000,
    )
    assert result["action"] == "CALL"
    assert result["market_regime"] == "TRENDING"
    assert result["trade_quality"]["score"] >= 70
    assert result["risk"]["status"] == "OK"
    assert result["decision"] == "EXECUTE_CANDIDATE"


def test_phase7_blocks_volatile_conflicted_setup():
    engine = ProfessionalDecisionEngine()
    result = engine.build(
        signal={"asset": "EURUSD_otc", "action": "PUT", "confidence": 72},
        scanner={
            "asset": "EURUSD_otc", "strength": 64, "trend": "BEARISH",
            "momentum": "BULLISH", "macd_bias": "BULLISH", "confirmation_trend": "BULLISH",
            "regime": "TRENDING", "volatility_state": "HIGH", "conflicts": ["HTF conflict", "Momentum conflict"],
        },
        timeframe="1m", amount=10, balance=1000,
    )
    assert result["market_regime"] == "VOLATILE"
    assert result["decision"] == "WAIT"
    assert result["no_trade_conditions"]
