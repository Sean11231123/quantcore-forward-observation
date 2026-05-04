from __future__ import annotations

from typing import Any

import pandas as pd


STRATEGY_NAME = "Momentum_Breakout"
STRATEGY_VERSION = "v0_validation"


def generate_momentum_signal(df: pd.DataFrame, idx: int, context: dict[str, Any]) -> dict[str, Any] | None:
    if idx <= 0 or idx >= len(df):
        return None

    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    btc_regime = context.get("btc_regime")

    required = [
        row.get("rsi"),
        row.get("volume_ratio"),
        row.get("previous_10_high"),
        row.get("adx"),
        prev.get("adx"),
        row.get("atr"),
        row.get("close"),
    ]
    if any(pd.isna(value) for value in required):
        return None

    atr = float(row["atr"])
    if atr <= 0:
        return None

    if btc_regime in {"CHOPPY", "TRENDING_BEAR"}:
        return None
    if float(row["rsi"]) <= 60:
        return None
    if float(row["volume_ratio"]) <= 1.5:
        return None
    if float(row["close"]) <= float(row["previous_10_high"]):
        return None
    if float(row["adx"]) <= 25:
        return None
    if float(row["adx"]) <= float(prev["adx"]):
        return None

    entry = float(row["close"])
    return {
        "strategy_name": STRATEGY_NAME,
        "strategy_version": STRATEGY_VERSION,
        "side": "long",
        "entry_price": entry,
        "stop_loss": entry - 2.0 * atr,
        "take_profit": entry + 3.0 * atr,
        "atr": atr,
        "metadata": {
            "rsi_14": float(row["rsi"]),
            "adx_15m": float(row["adx"]),
            "volume_ratio": float(row["volume_ratio"]),
            "previous_10_high": float(row["previous_10_high"]),
            "btc_regime": btc_regime,
        },
    }
