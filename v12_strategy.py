from __future__ import annotations

from collections.abc import MutableMapping
from typing import Optional

import pandas as pd


SL_ATR_MULT = 2.0
RISK_PCT = 0.01


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = _true_range(df)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def compute_v12_15m(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out["timestamp"] = pd.to_datetime(out["timestamp"])

    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()
    out["atr"] = _true_range(out).rolling(14, min_periods=14).mean()
    out["adx"] = _adx(out)
    out["prior_high_20"] = out["high"].rolling(20, min_periods=20).max().shift(1)

    window = 20
    range_high = out["high"].rolling(window, min_periods=window).max()
    range_low = out["low"].rolling(window, min_periods=window).min()
    out["range_efficiency"] = (
        (out["close"] - out["close"].shift(window)).abs()
        / (range_high - range_low).replace(0, pd.NA)
    ).fillna(0.0)

    return out


def shift_candle_open_to_close(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Convert candle-open timestamps to candle-close timestamps for safe lower-TF merges."""
    offsets = {
        "15m": pd.Timedelta(minutes=15),
        "30m": pd.Timedelta(minutes=30),
        "1h": pd.Timedelta(hours=1),
        "2h": pd.Timedelta(hours=2),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
    }
    if timeframe not in offsets:
        raise ValueError(f"Unsupported timeframe for timestamp shift: {timeframe}")
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    out["timestamp"] = out["timestamp"] + offsets[timeframe]
    return out


def align_1h_adx_to_15m(df15: pd.DataFrame, df1h: pd.DataFrame) -> pd.DataFrame:
    one_hour = compute_v12_15m(df1h)
    one_hour = shift_candle_open_to_close(one_hour, "1h")
    one_hour = one_hour[["timestamp", "adx"]].rename(columns={"adx": "adx_1h"})
    return pd.merge_asof(
        df15.sort_values("timestamp"),
        one_hour.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )


def build_daily_whitelist_with_sources(
    symbol_raw: dict[str, pd.DataFrame],
    top_n: int = 5,
) -> tuple[dict[pd.Timestamp, list[str]], dict[pd.Timestamp, pd.Timestamp]]:
    frames = []
    for symbol, df in symbol_raw.items():
        data = df.copy()
        data.columns = [c.lower() for c in data.columns]
        data["timestamp"] = pd.to_datetime(data["timestamp"])
        data["date"] = data["timestamp"].dt.normalize()
        data["dollar_volume"] = data["close"] * data["volume"]
        daily = data.groupby("date", as_index=False)["dollar_volume"].sum()
        daily["symbol"] = symbol
        frames.append(daily)

    if not frames:
        return {}, {}

    ranked = pd.concat(frames, ignore_index=True)
    ranked_by_date = {
        pd.Timestamp(date): group
        for date, group in ranked.groupby("date")
    }

    whitelist: dict[pd.Timestamp, list[str]] = {}
    sources: dict[pd.Timestamp, pd.Timestamp] = {}
    for trade_date in sorted(ranked_by_date):
        source_date = pd.Timestamp(trade_date) - pd.Timedelta(days=1)
        sources[pd.Timestamp(trade_date)] = source_date
        group = ranked_by_date.get(source_date)
        if group is None:
            whitelist[pd.Timestamp(trade_date)] = []
            continue
        whitelist[pd.Timestamp(trade_date)] = (
            group.sort_values("dollar_volume", ascending=False)["symbol"].head(top_n).tolist()
        )
    return whitelist, sources


def build_daily_whitelist(symbol_raw: dict[str, pd.DataFrame], top_n: int = 5) -> dict[pd.Timestamp, list[str]]:
    whitelist, _ = build_daily_whitelist_with_sources(symbol_raw, top_n=top_n)
    return whitelist


def get_whitelist_for_ts(whitelist: dict[pd.Timestamp, list[str]], ts) -> list[str]:
    return whitelist.get(pd.Timestamp(ts).normalize(), [])


def get_whitelist_source_for_ts(sources: dict[pd.Timestamp, pd.Timestamp], ts) -> Optional[pd.Timestamp]:
    return sources.get(pd.Timestamp(ts).normalize())


def _audit(audit: Optional[MutableMapping[str, int]], key: str) -> None:
    if audit is not None:
        audit[key] = audit.get(key, 0) + 1


def check_entry_long(
    row,
    prior_high: float,
    atr: float,
    adx_1h: float,
    btc_regime: Optional[dict] = None,
    mode: str = "C3",
    adx_entry_override: float = 30.0,
    re_threshold_override: float = 0.22,
    btc_re_lower: float = 0.20,
    btc_re_upper: Optional[float] = 0.40,
    audit: Optional[MutableMapping[str, int]] = None,
) -> bool:
    _audit(audit, "total_checked")

    required = [row.get("close"), row.get("ema20"), row.get("ema50"), prior_high, atr, adx_1h]
    if any(pd.isna(v) for v in required) or atr <= 0:
        _audit(audit, "fail_nan")
        return False

    btc_regime = btc_regime or {}
    btc_adx_1h = float(btc_regime.get("btc_adx_1h", 0) or 0)
    btc_re = float(btc_regime.get("btc_re", 0) or 0)

    if float(row.get("adx", 0) or 0) < adx_entry_override or float(adx_1h or 0) < 22:
        _audit(audit, "fail_adx")
        return False

    if mode == "C3":
        re_pass = btc_re >= btc_re_lower
        if btc_re_upper is not None:
            re_pass = re_pass and btc_re <= btc_re_upper
        allow_regime = btc_adx_1h >= 30.0 and re_pass
        if not allow_regime:
            _audit(audit, "fail_btc_regime_c3")
            return False
    else:
        if btc_adx_1h < 18:
            _audit(audit, "fail_btc_adx")
            return False

        if btc_re < re_threshold_override:
            _audit(audit, "fail_re")
            return False

    bullish_stack = row["close"] > row["ema20"] > row["ema50"]
    breakout = row["close"] > prior_high
    if not bullish_stack or not breakout:
        _audit(audit, "fail_breakout")
        return False

    _audit(audit, "passed")
    return True


def strong_reverse_candle_long(row) -> bool:
    body = abs(row["close"] - row["open"])
    candle_range = row["high"] - row["low"]
    if candle_range <= 0:
        return False
    lower_wick = min(row["open"], row["close"]) - row["low"]
    return row["close"] > row["open"] and lower_wick / candle_range > 0.45 and body / candle_range > 0.25
