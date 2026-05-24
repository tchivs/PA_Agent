"""User-facing Chinese messages for TradingView / tvdatafeed failures."""
from __future__ import annotations


def format_tradingview_fetch_error(
    symbol: str,
    exchange: str,
    *,
    empty_data: bool = False,
    cause: BaseException | None = None,
) -> str:
    """Return a short status-bar message for a failed TV snapshot."""
    sym = (symbol or "").strip()
    ex = (exchange or "").strip().upper()
    ex_hint = ex if ex else "未填写"

    cause_text = str(cause or "").lower()
    if "timed out" in cause_text or "timeout" in cause_text:
        return (
            f"TradingView 连接超时（{ex_hint} / {sym}）："
            "请检查网络能否访问 TradingView，或确认交易所 OANDA + 品种 XAUUSD"
        )

    if sym.lower().endswith("m") and len(sym) > 2:
        return (
            f"TradingView 无数据（{ex_hint} / {sym}）："
            "品种名像 MT5 券商后缀（…m），请去掉 m 或改用「数据来源 → MT5」。"
            "黄金示例：交易所 OANDA + 品种 XAUUSD"
        )

    if ex == "TVC" and sym.upper() == "XAUUSD":
        return (
            "TradingView 组合错误：TVC 上黄金是 GOLD，不是 XAUUSD。"
            "请用 OANDA + XAUUSD，或 TVC + GOLD"
        )

    if empty_data or "no data" in cause_text:
        if not ex:
            return (
                f"TradingView 无数据（品种 {sym}，未填交易所）："
                "请填写 OANDA + XAUUSD（现货黄金）"
            )
        hint = "OANDA + XAUUSD"
        if ex == "TVC":
            hint = "TVC + GOLD"
        elif ex == "CAPITALCOM":
            hint = "CAPITALCOM + GOLD"
        return (
            f"TradingView 无数据（{ex} / {sym}）："
            f"该组合可能无效，现货黄金请用 {hint}"
        )

    if cause is not None:
        return f"TradingView 拉取失败（{ex_hint} / {sym}）：{cause}"

    return f"TradingView 拉取失败（{ex_hint} / {sym}），请检查交易所与品种"
