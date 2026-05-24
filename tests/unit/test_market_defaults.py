"""Gold default symbol / exchange normalization."""
from __future__ import annotations

from pa_agent.data.market_defaults import (
    GOLD_MT5_SYMBOL,
    GOLD_TV_EXCHANGE,
    GOLD_TV_SYMBOL,
    migrate_general_gold_defaults,
    normalize_gold_symbol_for_kind,
    normalize_gold_tv_exchange,
    resolve_tv_gold_pair,
)


def test_crypto_symbol_migrates_to_gold():
    assert normalize_gold_symbol_for_kind("mt5", "BTCUSD") == GOLD_MT5_SYMBOL
    assert normalize_gold_symbol_for_kind("tradingview", "BTCUSDT") == GOLD_TV_SYMBOL


def test_mt5_suffix_on_tv_becomes_xauusd():
    assert normalize_gold_symbol_for_kind("tradingview", "XAUUSDm") == GOLD_TV_SYMBOL


def test_tv_exchange_defaults_to_oanda():
    assert normalize_gold_tv_exchange("") == GOLD_TV_EXCHANGE
    assert normalize_gold_tv_exchange("BINANCE") == GOLD_TV_EXCHANGE


def test_tvc_xauusd_is_invalid_pair_fixed_to_gold():
    ex, sym, adjusted = resolve_tv_gold_pair("TVC", "XAUUSD")
    assert ex == "TVC"
    assert sym == "GOLD"
    assert adjusted is True


def test_oanda_xauusd_unchanged():
    ex, sym, adjusted = resolve_tv_gold_pair("OANDA", "XAUUSD")
    assert (ex, sym, adjusted) == ("OANDA", "XAUUSD", False)


def test_migrate_general_fixes_tvc_xauusd():
    general = {
        "last_data_source": "tradingview",
        "last_symbol": "XAUUSD",
        "last_tradingview_exchange": "TVC",
    }
    migrate_general_gold_defaults(general)
    assert general["last_tradingview_exchange"] == "TVC"
    assert general["last_symbol"] == "GOLD"
