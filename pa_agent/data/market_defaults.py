"""Default gold (XAU) market identifiers across data sources."""
from __future__ import annotations

# MT5 broker spot gold (suffix varies by broker; m = common micro/mini suffix)
GOLD_MT5_SYMBOL = "XAUUSDm"

# TradingView spot gold — verified with tvdatafeed (anonymous):
#   OANDA:XAUUSD, PEPPERSTONE:XAUUSD, FOREXCOM:XAUUSD  OK
#   TVC:GOLD, CAPITALCOM:GOLD  OK
#   TVC:XAUUSD  INVALID (0 bars)
GOLD_TV_SYMBOL = "XAUUSD"
GOLD_TV_EXCHANGE = "OANDA"

# Exchange → correct gold symbol on TradingView (do not use XAUUSD on TVC)
TV_GOLD_SYMBOL_BY_EXCHANGE: dict[str, str] = {
    "OANDA": "XAUUSD",
    "PEPPERSTONE": "XAUUSD",
    "FOREXCOM": "XAUUSD",
    "FX": "XAUUSD",
    "FXCM": "XAUUSD",
    "TVC": "GOLD",
    "CAPITALCOM": "GOLD",
}

_CRYPTO_HINTS = ("BTC", "ETH", "USDT", "SOL", "DOGE", "BNB", "XRP", "CRYPTO")


def is_likely_crypto_symbol(symbol: str) -> bool:
    s = (symbol or "").upper().replace("/", "").replace("-", "")
    return any(h in s for h in _CRYPTO_HINTS)


def normalize_gold_symbol_for_kind(kind: str, symbol: str) -> str:
    """Map crypto / MT5-style names to gold defaults for *kind*."""
    sym = (symbol or "").strip()
    if not sym or is_likely_crypto_symbol(sym):
        return GOLD_TV_SYMBOL if kind == "tradingview" else GOLD_MT5_SYMBOL
    if kind == "tradingview" and sym.lower().endswith("m") and len(sym) > 2:
        return GOLD_TV_SYMBOL
    return sym


def normalize_gold_tv_exchange(exchange: str) -> str:
    """Default to OANDA for spot XAUUSD; map crypto venues away."""
    ex = (exchange or "").strip().upper()
    if ex in ("", "BINANCE", "COINBASE", "BITSTAMP", "BYBIT", "OKX", "KRAKEN"):
        return GOLD_TV_EXCHANGE
    return ex


def resolve_tv_gold_pair(
    exchange: str,
    symbol: str,
) -> tuple[str, str, bool]:
    """Return ``(exchange, symbol, adjusted)`` for a valid TV gold feed.

    Fixes common mistake ``TVC`` + ``XAUUSD`` → ``TVC`` + ``GOLD``.
    """
    ex = normalize_gold_tv_exchange(exchange)
    sym = (symbol or "").strip().upper() or GOLD_TV_SYMBOL
    expected = TV_GOLD_SYMBOL_BY_EXCHANGE.get(ex)
    if expected is not None:
        if sym != expected:
            return ex, expected, True
        return ex, expected, False
    if sym == "GOLD":
        return "TVC", "GOLD", ex != "TVC"
    return GOLD_TV_EXCHANGE, GOLD_TV_SYMBOL, ex != GOLD_TV_EXCHANGE or sym != GOLD_TV_SYMBOL


def migrate_general_gold_defaults(general: dict) -> None:
    """In-place migration: gold symbol + valid TV exchange/symbol pair."""
    kind = str(general.get("last_data_source", "mt5"))
    sym = str(general.get("last_symbol", ""))
    general["last_symbol"] = normalize_gold_symbol_for_kind(kind, sym)
    if kind == "tradingview":
        ex, sym, _ = resolve_tv_gold_pair(
            str(general.get("last_tradingview_exchange", GOLD_TV_EXCHANGE)),
            general["last_symbol"],
        )
        general["last_tradingview_exchange"] = ex
        general["last_symbol"] = sym
    else:
        general["last_tradingview_exchange"] = normalize_gold_tv_exchange(
            str(general.get("last_tradingview_exchange", ""))
        )
