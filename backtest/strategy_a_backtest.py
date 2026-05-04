from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ADX_PERIOD, ATR_PERIOD, INITIAL_BALANCE, RSI_PERIOD, SYMBOLS


STRATEGY_NAME = "Strategy_A_HigherTF_Pullback"
STRATEGY_VERSION = "v1_validation"
ENTRY_TF = "1h"
FEATURE_DIR = os.path.join("data", "features", ENTRY_TF)
OUTPUT_PATH = os.path.join("backtest", "output", "strategy_a_trade_log.csv")

COMMISSION = 0.0005
SLIPPAGE = 0.0002
RISK_PCT = 0.01
SL_ATR_MULT = 2.0
TP_ATR_MULT = 3.0
BE_TRIGGER_ATR = 1.5
TIME_STOP_BARS = 48
COOLDOWN_BARS = 24

START_FULL = pd.Timestamp("2021-01-01")
END_FULL = pd.Timestamp("2026-04-21 23:59:59")


@dataclass
class Position:
    symbol: str
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    atr: float
    stop_loss: float
    take_profit: float
    be_trigger: float
    qty: float
    balance_before_entry: float
    peak_price: float
    trough_price: float
    bars_held: int
    be_active: bool
    entry_features: dict[str, Any]


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":USDT", "")


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def load_feature_file(symbol: str) -> pd.DataFrame:
    path = os.path.join(FEATURE_DIR, f"{symbol}_features.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    required = {"timestamp", "candle_close_time", "open", "high", "low", "close", "volume", "ema20", "ema50", "ema200", "adx", "atr", "segment_id", "warmup_excluded"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{symbol} missing columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["candle_close_time"] = pd.to_datetime(df["candle_close_time"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[(df["timestamp"] >= START_FULL) & (df["timestamp"] <= END_FULL)].reset_index(drop=True)


def add_strategy_features(df: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for _, part in df.groupby("segment_id", sort=True):
        out = part.copy()
        out["adx_prev"] = out["adx"].shift(1)
        out["rsi_14"] = rsi(out["close"], RSI_PERIOD)
        out["rsi_prev"] = out["rsi_14"].shift(1)
        out["vol_ma20"] = out["volume"].rolling(20, min_periods=20).mean()
        out["vol_ratio"] = out["volume"] / out["vol_ma20"].replace(0, np.nan)
        out["had_pullback"] = (out["close"] < out["ema20"]).rolling(5, min_periods=5).max().shift(1).fillna(0).astype(bool)
        out["close_position"] = (out["close"] - out["low"]) / (out["high"] - out["low"] + 1e-9)
        pieces.append(out)
    return pd.concat(pieces, ignore_index=True).sort_values("timestamp").reset_index(drop=True)


def load_btc_regime() -> pd.DataFrame:
    btc = add_strategy_features(load_feature_file("BTCUSDT"))
    btc = btc.rename(
        columns={
            "ema20": "btc_ema20",
            "ema50": "btc_ema50",
            "ema200": "btc_ema200",
            "adx": "btc_adx",
        }
    )
    return btc[["candle_close_time", "btc_ema20", "btc_ema50", "btc_ema200", "btc_adx", "warmup_excluded"]].rename(
        columns={"warmup_excluded": "btc_warmup_excluded"}
    )


def merge_btc(df: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    return pd.merge_asof(
        df.sort_values("candle_close_time"),
        btc.sort_values("candle_close_time"),
        on="candle_close_time",
        direction="backward",
    ).sort_values("timestamp").reset_index(drop=True)


def load_symbol_frames() -> dict[str, pd.DataFrame]:
    btc = load_btc_regime()
    frames: dict[str, pd.DataFrame] = {}
    for raw_symbol in SYMBOLS:
        symbol = normalize_symbol(raw_symbol)
        if symbol == "BTCUSDT":
            continue
        df = add_strategy_features(load_feature_file(symbol))
        frames[symbol] = merge_btc(df, btc)
    return frames


def has_gap_crossing_issue(frames: dict[str, pd.DataFrame]) -> list[str]:
    issues = []
    for symbol, df in frames.items():
        if "segment_id" not in df.columns or "warmup_excluded" not in df.columns:
            issues.append(f"{symbol}: missing gap-aware columns")
        if bool(df["gap_before_current_bar"].any()) and not bool(df["warmup_excluded"].any()):
            issues.append(f"{symbol}: gap exists without warmup exclusion")
    return issues


def entry_signal(row: pd.Series, idx: int, last_exit_idx: int | None) -> tuple[bool, str]:
    if bool(row.get("warmup_excluded", False)) or bool(row.get("btc_warmup_excluded", False)):
        return False, ""
    required = [
        "ema20",
        "ema50",
        "ema200",
        "adx",
        "adx_prev",
        "atr",
        "rsi_14",
        "rsi_prev",
        "vol_ratio",
        "btc_ema20",
        "btc_ema50",
        "btc_ema200",
        "btc_adx",
    ]
    if any(pd.isna(row.get(col)) for col in required):
        return False, ""
    if float(row["atr"]) <= 0:
        return False, ""

    btc_regime_pass = bool(row["btc_ema20"] > row["btc_ema50"] > row["btc_ema200"] and row["btc_adx"] >= 25)
    trend_aligned = bool(row["ema20"] > row["ema50"] > row["ema200"])
    adx_pass = bool(row["adx"] >= 30 and row["adx"] > row["adx_prev"])
    pullback_occurred = bool(row["had_pullback"])
    close_above_ema20 = bool(row["close"] > row["ema20"])
    vol_confirm = bool(row["vol_ratio"] >= 1.3 and row["close_position"] >= 0.60)
    rsi_confirm = bool((row["rsi_14"] - row["rsi_prev"]) >= 5 and row["rsi_14"] > 40)
    not_overextended = bool((row["close"] - row["ema20"]) <= 1.5 * row["atr"])
    cooldown_pass = True if last_exit_idx is None else (idx - last_exit_idx >= COOLDOWN_BARS)

    confirmation_type = ""
    if vol_confirm and rsi_confirm:
        confirmation_type = "vol_and_rsi"
    elif vol_confirm:
        confirmation_type = "volume_candle"
    elif rsi_confirm:
        confirmation_type = "rsi_rebound"

    passed = all([
        btc_regime_pass,
        trend_aligned,
        adx_pass,
        pullback_occurred,
        close_above_ema20,
        bool(confirmation_type),
        not_overextended,
        cooldown_pass,
    ])
    return passed, confirmation_type


def forward_return(df: pd.DataFrame, idx: int, entry_price: float, bars: int) -> float:
    if idx + bars >= len(df):
        return np.nan
    return (float(df.iloc[idx + bars]["close"]) - entry_price) / entry_price * 100.0


def close_position(pos: Position, row: pd.Series, idx: int, balance: float, exit_price: float, reason: str) -> tuple[dict[str, Any], float]:
    pnl = pos.qty * (exit_price - pos.entry_price)
    gross_return_pct = (exit_price - pos.entry_price) / pos.entry_price * 100.0
    net_return_pct = gross_return_pct - (COMMISSION + SLIPPAGE) * 2 * 100.0
    balance_before_exit = balance
    balance = balance + pnl
    balance *= 1.0 - COMMISSION - SLIPPAGE
    pnl_portfolio_pct = (balance - pos.balance_before_entry) / pos.balance_before_entry * 100.0
    atr = pos.atr
    trade = {
        "symbol": pos.symbol,
        "side": "long",
        "entry_time": pos.entry_time,
        "exit_time": row["timestamp"],
        "entry_idx": pos.entry_idx,
        "exit_idx": idx,
        "entry_price": pos.entry_price,
        "exit_price": exit_price,
        "pnl_pct": gross_return_pct,
        "net_pnl_pct": net_return_pct,
        "pnl_portfolio_pct": pnl_portfolio_pct,
        "exit_reason": reason,
        "mfe_atr": (pos.peak_price - pos.entry_price) / atr if atr > 0 else 0.0,
        "mae_atr": (pos.entry_price - pos.trough_price) / atr if atr > 0 else 0.0,
        "bars_held": pos.bars_held,
        "rsi_14": pos.entry_features["rsi_14"],
        "adx_1h": pos.entry_features["adx_1h"],
        "adx_prev_1h": pos.entry_features["adx_prev_1h"],
        "vol_ratio": pos.entry_features["vol_ratio"],
        "atr": atr,
        "ema20": pos.entry_features["ema20"],
        "ema50": pos.entry_features["ema50"],
        "ema200": pos.entry_features["ema200"],
        "btc_adx": pos.entry_features["btc_adx"],
        "btc_ema20": pos.entry_features["btc_ema20"],
        "btc_ema50": pos.entry_features["btc_ema50"],
        "btc_ema200": pos.entry_features["btc_ema200"],
        "btc_regime_pass": pos.entry_features["btc_regime_pass"],
        "confirmation_type": pos.entry_features["confirmation_type"],
        "had_pullback": pos.entry_features["had_pullback"],
        "close_position": pos.entry_features["close_position"],
        "execution_model": "enter_on_signal_bar_close",
        "balance_before_entry": pos.balance_before_entry,
        "balance_before_exit": balance_before_exit,
        "balance_after_exit": balance,
        "forward_return_4bars": pos.entry_features["forward_return_4bars"],
        "forward_return_8bars": pos.entry_features["forward_return_8bars"],
    }
    return trade, balance


def run_symbol(symbol: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    balance = float(INITIAL_BALANCE)
    pos: Position | None = None
    last_exit_idx: int | None = None
    trades: list[dict[str, Any]] = []

    for idx, row in df.iterrows():
        if pos is not None:
            pos.bars_held += 1
            pos.peak_price = max(pos.peak_price, float(row["high"]))
            pos.trough_price = min(pos.trough_price, float(row["low"]))

            exit_price = None
            exit_reason = None
            if float(row["high"]) >= pos.take_profit:
                exit_price = pos.take_profit
                exit_reason = "TAKE_PROFIT"
            else:
                if float(row["high"]) >= pos.be_trigger:
                    pos.be_active = True
                    pos.stop_loss = max(pos.stop_loss, pos.entry_price)
                if float(row["low"]) <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "BREAK_EVEN_SL" if pos.be_active and pos.stop_loss >= pos.entry_price else "STOP_LOSS"
                elif pos.bars_held > TIME_STOP_BARS:
                    exit_price = float(row["close"])
                    exit_reason = "TIME_STOP"

            if exit_reason is not None and exit_price is not None:
                trade, balance = close_position(pos, row, idx, balance, exit_price, exit_reason)
                trades.append(trade)
                last_exit_idx = idx
                pos = None

        if pos is not None:
            continue

        passed, confirmation_type = entry_signal(row, idx, last_exit_idx)
        if not passed:
            continue
        entry_price = float(row["close"])
        atr = float(row["atr"])
        stop_loss = entry_price - SL_ATR_MULT * atr
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            continue
        risk_usdt = balance * RISK_PCT
        qty = risk_usdt / sl_distance
        balance_before_entry = balance
        balance *= 1.0 - COMMISSION - SLIPPAGE
        pos = Position(
            symbol=symbol,
            entry_idx=idx,
            entry_time=row["timestamp"],
            entry_price=entry_price,
            atr=atr,
            stop_loss=stop_loss,
            take_profit=entry_price + TP_ATR_MULT * atr,
            be_trigger=entry_price + BE_TRIGGER_ATR * atr,
            qty=qty,
            balance_before_entry=balance_before_entry,
            peak_price=entry_price,
            trough_price=entry_price,
            bars_held=0,
            be_active=False,
            entry_features={
                "rsi_14": float(row["rsi_14"]),
                "adx_1h": float(row["adx"]),
                "adx_prev_1h": float(row["adx_prev"]),
                "vol_ratio": float(row["vol_ratio"]),
                "ema20": float(row["ema20"]),
                "ema50": float(row["ema50"]),
                "ema200": float(row["ema200"]),
                "btc_adx": float(row["btc_adx"]),
                "btc_ema20": float(row["btc_ema20"]),
                "btc_ema50": float(row["btc_ema50"]),
                "btc_ema200": float(row["btc_ema200"]),
                "btc_regime_pass": True,
                "confirmation_type": confirmation_type,
                "had_pullback": bool(row["had_pullback"]),
                "close_position": float(row["close_position"]),
                "forward_return_4bars": forward_return(df, idx, entry_price, 4),
                "forward_return_8bars": forward_return(df, idx, entry_price, 8),
            },
        )
    return trades


def main() -> None:
    frames = load_symbol_frames()
    issues = has_gap_crossing_issue(frames)
    if issues:
        raise RuntimeError("ANOMALY rolling/gap issue: " + "; ".join(issues))

    all_trades: list[dict[str, Any]] = []
    for symbol, df in frames.items():
        all_trades.extend(run_symbol(symbol, df))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    pd.DataFrame(all_trades).sort_values(["entry_time", "symbol"]).to_csv(OUTPUT_PATH, index=False)
    print(f"wrote {OUTPUT_PATH} rows={len(all_trades)}")


if __name__ == "__main__":
    main()
