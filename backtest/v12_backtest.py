"""
V12 Trend Strategy Backtest v2 — Clean Architecture
- single engine
- no duplicate state
- deterministic execution
"""

from __future__ import annotations

import glob
import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import COMMISSION, INITIAL_BALANCE
from v12_strategy import (
    SL_ATR_MULT,
    RISK_PCT,
    compute_v12_15m,
    align_1h_adx_to_15m,
    shift_candle_open_to_close,
    build_daily_whitelist,
    build_daily_whitelist_with_sources,
    get_whitelist_for_ts,
    get_whitelist_source_for_ts,
    check_entry_long,
    strong_reverse_candle_long,
)

# =========================================================
# State Object
# =========================================================

class V12State:
    def __init__(self):
        self.balance = float(INITIAL_BALANCE)

        self.pos_sym = None
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_atr = 0.0
        self.position_notional = 0.0
        self.balance_before_entry = 0.0
        self.coin_adx_15m_at_entry = 0.0
        self.coin_adx_1h_at_entry = 0.0
        self.whitelist_source_date = None

        self.bars_in_trade = 0
        self.mfe_atr = 0.0
        self.mae_atr = 0.0

        self.structure_sl = 0.0
        self.ema_break_cnt = 0

        self.btc_regime_at_entry = {}

        self.trade_log: List[dict] = []
        self.balance_series: List[float] = []


# =========================================================
# Data Loaders
# =========================================================

def _load_btc_regime() -> Optional[pd.DataFrame]:
    p15 = "data/BTC_USDT_15m.csv"
    p1h = "data/BTC_USDT_1h.csv"

    if not os.path.exists(p15) or not os.path.exists(p1h):
        return None

    btc15 = pd.read_csv(p15)
    btc1h = pd.read_csv(p1h)

    btc15.columns = [c.lower() for c in btc15.columns]
    btc1h.columns = [c.lower() for c in btc1h.columns]

    btc15["timestamp"] = pd.to_datetime(btc15["timestamp"])
    btc1h["timestamp"] = pd.to_datetime(btc1h["timestamp"])

    btc15 = compute_v12_15m(btc15)
    btc1h = compute_v12_15m(btc1h)
    btc1h = shift_candle_open_to_close(btc1h, "1h")

    btc1h = btc1h[["timestamp", "adx"]].rename(columns={"adx": "btc_adx_1h"})

    btc15 = btc15.sort_values("timestamp")
    btc1h = btc1h.sort_values("timestamp")

    df = pd.merge_asof(btc15, btc1h, on="timestamp", direction="backward")

    df = df.rename(columns={
        "close": "btc_close",
        "adx": "btc_adx",
        "ema20": "btc_ema20",
        "ema50": "btc_ema50",
        "ema200": "btc_ema200",
        "range_efficiency": "btc_re",
    })
    return df[[
        "timestamp",
        "btc_close",
        "btc_adx",
        "btc_adx_1h",
        "btc_ema20",
        "btc_ema50",
        "btc_ema200",
        "btc_re",
    ]]


def _load_symbols() -> Dict[str, Tuple[pd.DataFrame, pd.DataFrame]]:
    out = {}

    for f15 in glob.glob("data/*_15m.csv"):
        sym = os.path.basename(f15).replace("_15m.csv", "")
        if sym == "BTC_USDT":
            continue

        f1h = f15.replace("15m", "1h")
        if not os.path.exists(f1h):
            continue

        df15 = pd.read_csv(f15)
        df1h = pd.read_csv(f1h)

        df15.columns = [c.lower() for c in df15.columns]
        df1h.columns = [c.lower() for c in df1h.columns]

        df15["timestamp"] = pd.to_datetime(df15["timestamp"])
        df1h["timestamp"] = pd.to_datetime(df1h["timestamp"])

        out[sym] = (df15, df1h)

    return out


# =========================================================
# Data Prep
# =========================================================

def _prepare(df15, df1h, btc):
    df15 = df15.sort_values("timestamp").reset_index(drop=True)

    df = compute_v12_15m(df15)
    df["volume_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, pd.NA)
    candle_range = df["high"] - df["low"]
    df["candle_close_position"] = ((df["close"] - df["low"]) / candle_range.replace(0, pd.NA)).fillna(0.0)
    df = align_1h_adx_to_15m(df, df1h)

    if btc is not None:
        df = pd.merge_asof(
            df.sort_values("timestamp"),
            btc.sort_values("timestamp"),
            on="timestamp",
            direction="backward"
        )

    return df.reset_index(drop=True)


def _ts_index(df):
    return {pd.Timestamp(df.iloc[i]["timestamp"]): i for i in range(len(df))}


# =========================================================
# Exit Logic
# =========================================================

def _exit(state: V12State, ts, sym, exit_type, exit_px, bal_before):
    pnl = state.position_notional * (exit_px - state.entry_price) / state.entry_price

    state.balance += pnl
    state.balance *= (1.0 - COMMISSION)
    round_trip_before = state.balance_before_entry or bal_before
    net_pnl = state.balance - round_trip_before

    state.trade_log.append({
        "ts": ts,
        "symbol": sym,
        "side": "buy",
        "entry_time": state.entry_time,
        "exit_time": ts,
        "entry_price": state.entry_price,
        "exit_price": exit_px,
        "exit": exit_type,
        "exit_reason": exit_type,
        "pnl": pnl,
        "net_pnl": net_pnl,
        "balance_before": round_trip_before,
        "pnl_portfolio_pct": net_pnl / round_trip_before * 100 if round_trip_before else 0.0,
        "balance": state.balance,
        "mfe_atr": state.mfe_atr,
        "mae_atr": state.mae_atr,
        "bars": state.bars_in_trade,
        "bars_held": state.bars_in_trade,
        "btc_re": state.btc_regime_at_entry.get("btc_re", 0.0),
        "btc_adx_1h": state.btc_regime_at_entry.get("btc_adx_1h", 0.0),
        "coin_adx_15m": state.coin_adx_15m_at_entry,
        "coin_adx_1h": state.coin_adx_1h_at_entry,
        "whitelist_source_date": state.whitelist_source_date,
    })

    state.balance_series.append(state.balance)

    state.pos_sym = None
    state.bars_in_trade = 0
    state.mfe_atr = 0.0
    state.mae_atr = 0.0
    state.structure_sl = 0.0
    state.ema_break_cnt = 0
    state.btc_regime_at_entry = {}
    state.balance_before_entry = 0.0
    state.entry_time = None
    state.coin_adx_15m_at_entry = 0.0
    state.coin_adx_1h_at_entry = 0.0
    state.whitelist_source_date = None


# =========================================================
# Engine
# =========================================================

def simulate_v12_v2(
    top_n=5,
    start_date=None,
    end_date=None,
    tp_atr_mult: float = 4.0,
    mode: str = "C3",
    adx_entry_override: float = 30.0,
    re_threshold_override: float = 0.22,
    btc_re_lower: float = 0.20,
    btc_re_upper: Optional[float] = 0.40,
    volume_ratio_min: Optional[float] = None,
    candle_close_position_max: Optional[float] = None,
    no_be: bool = False,
    be_threshold: float = 2.5,
):

    state = V12State()
    audit = defaultdict(int)

    raw = _load_symbols()
    btc = _load_btc_regime()

    symbol_raw = {s: p[0] for s, p in raw.items()}
    whitelist, whitelist_sources = build_daily_whitelist_with_sources(symbol_raw, top_n=top_n)

    prepared = {}
    idx_map = {}

    for s, (df15, df1h) in raw.items():
        prepared[s] = _prepare(df15, df1h, btc)
        if start_date is not None:
            prepared[s] = prepared[s][prepared[s]["timestamp"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            prepared[s] = prepared[s][prepared[s]["timestamp"] <= pd.Timestamp(end_date)]
        prepared[s] = prepared[s].reset_index(drop=True)
        idx_map[s] = _ts_index(prepared[s])

    prepared = {s: df for s, df in prepared.items() if not df.empty}
    if not prepared:
        return [], [], dict(audit)

    first = list(prepared.keys())[0]
    ts_list = prepared[first]["timestamp"].tolist()

    for i, ts in enumerate(ts_list):

        ts = pd.Timestamp(ts)
        state.balance_series.append(state.balance)

        # =====================
        # EXIT
        # =====================
        if state.pos_sym:

            df = prepared[state.pos_sym]
            if ts not in idx_map[state.pos_sym]:
                continue

            row = df.iloc[idx_map[state.pos_sym][ts]]
            hi, lo, cl = row["high"], row["low"], row["close"]

            state.bars_in_trade += 1

            state.mfe_atr = max(state.mfe_atr, (hi - state.entry_price) / state.entry_atr)
            state.mae_atr = min(state.mae_atr, (lo - state.entry_price) / state.entry_atr)

            sl = state.entry_price - SL_ATR_MULT * state.entry_atr
            tp = state.entry_price + tp_atr_mult * state.entry_atr

            if hi >= tp:
                _exit(state, ts, state.pos_sym, "TAKE_PROFIT", tp, state.balance)
                continue

            if lo <= sl:
                _exit(state, ts, state.pos_sym, "HARD_SL", sl, state.balance)
                continue

            if cl < sl:
                _exit(state, ts, state.pos_sym, "STRUCT_BREAK", cl, state.balance)
                continue

        # =====================
        # ENTRY
        # =====================
        wl = get_whitelist_for_ts(whitelist, ts)
        whitelist_source_date = get_whitelist_source_for_ts(whitelist_sources, ts)

        for sym in wl:

            if sym not in prepared or ts not in idx_map[sym]:
                continue

            df = prepared[sym]
            row = df.iloc[idx_map[sym][ts]]

            atr = row["atr"]

            btc = {
                "btc_adx": row.get("btc_adx", 0),
                "btc_adx_1h": row.get("btc_adx_1h", 0),
                "btc_re": row.get("btc_re", 0),
            }

            if not check_entry_long(
                row,
                row["prior_high_20"],
                atr,
                row.get("adx_1h", 0),
                btc,
                mode=mode,
                adx_entry_override=adx_entry_override,
                re_threshold_override=re_threshold_override,
                btc_re_lower=btc_re_lower,
                btc_re_upper=btc_re_upper,
                audit=audit,
            ):
                continue

            if volume_ratio_min is not None and row.get("volume_ratio", 0) < volume_ratio_min:
                audit["fail_volume_ratio_filter"] += 1
                continue

            if (
                candle_close_position_max is not None
                and row.get("candle_close_position", 1) > candle_close_position_max
            ):
                audit["fail_candle_close_position_filter"] += 1
                continue

            state.entry_price = row["close"]
            state.entry_time = ts
            state.entry_atr = atr

            risk = state.balance * RISK_PCT
            state.position_notional = risk * state.entry_price / (SL_ATR_MULT * atr)

            state.pos_sym = sym
            state.btc_regime_at_entry = btc.copy()
            state.coin_adx_15m_at_entry = row.get("adx", 0)
            state.coin_adx_1h_at_entry = row.get("adx_1h", 0)
            state.whitelist_source_date = whitelist_source_date
            state.balance_before_entry = state.balance
            state.balance *= (1.0 - COMMISSION)

            state.structure_sl = state.entry_price - SL_ATR_MULT * atr

            break

    return state.trade_log, state.balance_series, dict(audit)


# =========================================================
# Stats
# =========================================================

def stats(log, series=None):
    if isinstance(log, V12State):
        series = log.balance_series
        log = log.trade_log

    if not log:
        return None

    df = pd.DataFrame(log)
    initial_balance = INITIAL_BALANCE
    final_balance = float(series[-1]) if series else float(df.iloc[-1]["balance"])
    returns = df["pnl"] / df["balance"].shift(1).fillna(initial_balance)

    return {
        "trades": len(df),
        "win_rate": (df["pnl"] > 0).mean() * 100,
        "win_rate_%": (df["pnl"] > 0).mean() * 100,
        "final": final_balance,
        "final_balance": final_balance,
        "avg_return": (final_balance / initial_balance - 1) * 100,
        "expectancy_per_trade_%": returns.mean() * 100,
    }


# =========================================================
# Run
# =========================================================

if __name__ == "__main__":

    log, series, audit = simulate_v12_v2(
        top_n=int(os.environ.get("V12_TOP_N", "5")),
        start_date=os.environ.get("V12_START_DATE", "2021-01-01"),
        end_date=os.environ.get("V12_END_DATE", "2026-01-01"),
        tp_atr_mult=float(os.environ.get("V12_TP_ATR_MULT", "4.0")),
    )

    print("Signal Flow Audit:")
    for key in (
        "total_checked",
        "fail_nan",
        "fail_adx",
        "fail_btc_adx",
        "fail_re",
        "fail_btc_regime_c3",
        "fail_breakout",
        "passed",
    ):
        print(f"  {key}: {audit.get(key, 0)}")
    print("Trades:", len(log))
    print("Final balance:", series[-1] if series else INITIAL_BALANCE)
