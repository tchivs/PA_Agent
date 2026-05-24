"""Unit tests for Stage 2 normalizer — next_bar_prediction (T4)."""
from __future__ import annotations

from pa_agent.ai.stage2_normalizer import normalize_stage2, _normalize_next_bar_prediction


# ── _normalize_next_bar_prediction direct tests ──────────────────────────────


def test_normalize_next_bar_prediction_unpredictable_forces_null():
    """unpredictable=true → direction/probabilities normalized to None."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 60, "bearish": 30, "neutral": 10},
        "reasoning": "test",
        "unpredictable": True,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["unpredictable"] is True
    assert pred["direction"] is None
    assert pred["probabilities"] is None


def test_normalize_next_bar_prediction_rounds_probabilities():
    """Float probabilities must be rounded to ints, clamped to [0, 100]."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 49.7, "bearish": 30.3, "neutral": 20.0},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    probs = pred["probabilities"]
    assert probs == {"bullish": 50, "bearish": 30, "neutral": 20}


def test_normalize_next_bar_prediction_direction_argmax():
    """direction must be corrected to argmax of probabilities."""
    pred = {
        "direction": "bearish",  # wrong
        "probabilities": {"bullish": 55, "bearish": 35, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["direction"] == "bullish"


def test_normalize_next_bar_prediction_direction_argmax_tie_break():
    """Tied probabilities: break by literal order (bullish > bearish > neutral)."""
    pred = {
        "direction": "neutral",
        "probabilities": {"bullish": 40, "bearish": 40, "neutral": 20},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["direction"] == "bullish"  # bullish before bearish


def test_normalize_next_bar_prediction_features_used_dedup_min():
    """features_used must be deduplicated and contain at least stage1_diagnosis."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["kline_features", "kline_features", "stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["features_used"] == ["kline_features", "stage1_diagnosis"]


def test_normalize_next_bar_prediction_features_used_min_set():
    """Missing stage1_diagnosis gets prepended."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["kline_features"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["features_used"][0] == "stage1_diagnosis"


def test_normalize_next_bar_prediction_reasoning_truncation():
    """Reasoning > 1500 chars gets truncated with ellipsis."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "x" * 2000,
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert len(pred["reasoning"]) == 1500
    assert pred["reasoning"].endswith("…")


def test_normalize_next_bar_prediction_non_string_reasoning():
    """Non-string reasoning becomes empty string."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": 42,
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["reasoning"] == ""


def test_normalize_next_bar_prediction_idempotent():
    """Calling normalize twice must produce same result."""
    pred = {
        "direction": "bearish",
        "probabilities": {"bullish": 55, "bearish": 35, "neutral": 10},
        "reasoning": "test reasoning for idempotency check",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    first = {**pred}
    _normalize_next_bar_prediction(pred)
    assert pred == first


# ── Integration: normalize_stage2 with prediction ────────────────────────────


def test_normalize_stage2_with_prediction():
    """normalize_stage2 must call _normalize_next_bar_prediction."""
    obj = {
        "decision": {
            "order_type": "不下单",
            "order_direction": None,
            "entry_price": None,
            "take_profit_price": None,
            "stop_loss_price": None,
            "reasoning": "test",
            "diagnosis_confidence": 40,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 30,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 55,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [
            {"node_id": "10.3", "question": "q", "answer": "否", "reason": "r", "bar_range": "K1"},
        ],
        "terminal": {"node_id": "10.3", "outcome": "wait", "label": "test"},
        "next_bar_prediction": {
            "direction": "bearish",  # wrong: argmax is bullish
            "probabilities": {"bullish": 55.4, "bearish": 34.6, "neutral": 10.0},
            "reasoning": "test",
            "unpredictable": False,
            "features_used": [],
        },
    }
    result = normalize_stage2(obj)
    pred = result["next_bar_prediction"]
    assert pred["direction"] == "bullish"
    assert pred["probabilities"] == {"bullish": 55, "bearish": 35, "neutral": 10}
    assert pred["features_used"] == ["stage1_diagnosis"]


def test_normalize_stage2_without_prediction_noop():
    """Legacy Stage 2 without prediction must normalize without error."""
    obj = {
        "decision": {
            "order_type": "不下单",
            "order_direction": None,
            "entry_price": None,
            "take_profit_price": None,
            "stop_loss_price": None,
            "reasoning": "test",
            "diagnosis_confidence": 40,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 30,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": None,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "0", "outcome": "wait", "label": "test"},
    }
    result = normalize_stage2(obj)
    assert "next_bar_prediction" not in result
