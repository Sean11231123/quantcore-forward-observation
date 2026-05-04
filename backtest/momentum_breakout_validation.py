from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import COMMISSION, INITIAL_BALANCE, RSI_PERIOD, SYMBOLS
from core.strategies.momentum_breakout import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    generate_momentum_signal,
)
from v12_strategy import RISK_PCT, align_1h_adx_to_15m, compute_v12_15m
from backtest.v12_backtest import _load_btc_regime


OUTPUT_PATH = "backtest/output/momentum_breakout_trade_log.csv"
RESULT_PATH = "backtest/output/momentum_breakout_validation_results.json"

FULL_START = "2023-01-01"
IS_START = "2023-01-01"
IS_END = "2023-12-31 23:59:59"
OOS_START = "2024-01-01"
END_DATE = "2026-04-21 23:59:59"

ENTRY_FEE = COMMISSION
EXIT_FEE = COMMISSION
SL_ATR_MULT = 2.0
TP_ATR_MULT = 3.0


@dataclass
class SimulationResult:
    log: list[dict[str, Any]]
    series: list[float]
    frames: dict[str, pd.DataFrame]


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":USDT", "")


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    return np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss.replace(0, np.nan)))


def load_entry_frames() -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for raw_symbol in SYMBOLS:
        symbol = normalize_symbol(raw_symbol)
        p15 = os.path.join("data", f"{symbol}_15m.csv")
        p1h = os.path.join("data", f"{symbol}_1h.csv")
        if not os.path.exists(p15) or not os.path.exists(p1h):
            continue
        df15 = pd.read_csv(p15)
        df1h = pd.read_csv(p1h)
        df15.columns = [c.lower() for c in df15.columns]
        df1h.columns = [c.lower() for c in df1h.columns]
        df15["timestamp"] = pd.to_datetime(df15["timestamp"])
        df1h["timestamp"] = pd.to_datetime(df1h["timestamp"])
        df = compute_v12_15m(df15.sort_values("timestamp").reset_index(drop=True))
        df = align_1h_adx_to_15m(df, df1h)
        df["volume_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, pd.NA)
        df["rsi"] = compute_rsi(df["close"])
        df["previous_10_high"] = df["high"].rolling(10, min_periods=10).max().shift(1)
        df = df[(df["timestamp"] >= pd.Timestamp(FULL_START)) & (df["timestamp"] <= pd.Timestamp(END_DATE))].reset_index(drop=True)
        frames[symbol] = df
    return frames


def load_btc_context() -> pd.DataFrame:
    btc = _load_btc_regime()
    if btc is None:
        return pd.DataFrame(columns=["timestamp", "btc_adx", "btc_re", "btc_regime"])
    btc = btc.sort_values("timestamp").reset_index(drop=True)
    btc["btc_regime"] = "OTHER"
    btc.loc[(btc["btc_adx_1h"] > 30) & (btc["btc_ema20"] < btc["btc_ema50"]), "btc_regime"] = "TRENDING_BEAR"
    btc.loc[(btc["btc_adx_1h"] < 20) & (btc["btc_re"] < 0.20), "btc_regime"] = "CHOPPY"

    return btc[["timestamp", "btc_adx_1h", "btc_re", "btc_regime"]].rename(columns={"btc_adx_1h": "btc_adx"})


def attach_btc_context(frames: dict[str, pd.DataFrame], btc: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    btc_sorted = btc.sort_values("timestamp")
    for symbol, df in frames.items():
        merged = pd.merge_asof(
            df.sort_values("timestamp"),
            btc_sorted,
            on="timestamp",
            direction="backward",
        )
        out[symbol] = merged.reset_index(drop=True)
    return out


def prepare() -> tuple[dict[str, pd.DataFrame], dict[str, dict[pd.Timestamp, int]], list[pd.Timestamp]]:
    frames = attach_btc_context(load_entry_frames(), load_btc_context())
    idx_map = {
        symbol: {pd.Timestamp(ts): idx for idx, ts in enumerate(df["timestamp"])}
        for symbol, df in frames.items()
    }
    all_ts = sorted({pd.Timestamp(ts) for df in frames.values() for ts in df["timestamp"].tolist()})
    return frames, idx_map, all_ts


def simulate(
    start_date: str,
    end_date: str,
    prepared: tuple[dict[str, pd.DataFrame], dict[str, dict[pd.Timestamp, int]], list[pd.Timestamp]] | None = None,
) -> SimulationResult:
    frames, idx_map, all_ts = prepared if prepared is not None else prepare()
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    symbol_order = [normalize_symbol(s) for s in SYMBOLS if normalize_symbol(s) in frames]

    balance = float(INITIAL_BALANCE)
    series: list[float] = []
    log: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None

    for ts in all_ts:
        if ts < start_ts or ts > end_ts:
            continue
        series.append(balance)

        if pos is not None:
            idx = idx_map[pos["symbol"]].get(ts)
            if idx is not None:
                row = frames[pos["symbol"]].iloc[idx]
                pos["bars_held"] += 1
                hi = float(row["high"])
                lo = float(row["low"])
                pos["mfe_atr"] = max(pos["mfe_atr"], (hi - pos["entry_price"]) / pos["atr"])
                pos["mae_atr"] = max(pos["mae_atr"], (pos["entry_price"] - lo) / pos["atr"])

                exit_reason = None
                exit_price = None
                if lo <= pos["stop_loss"]:
                    exit_reason = "HARD_SL"
                    exit_price = pos["stop_loss"]
                elif hi >= pos["take_profit"]:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = pos["take_profit"]

                if exit_reason is not None:
                    pnl = pos["position_notional"] * (exit_price - pos["entry_price"]) / pos["entry_price"]
                    balance += pnl
                    balance *= 1.0 - EXIT_FEE
                    pnl_portfolio_pct = (balance - pos["balance_before_entry"]) / pos["balance_before_entry"] * 100
                    log.append(
                        {
                            "symbol": pos["symbol"],
                            "side": "long",
                            "entry_time": pos["entry_time"],
                            "exit_time": ts,
                            "entry_idx": pos["entry_idx"],
                            "entry_price": pos["entry_price"],
                            "exit_price": exit_price,
                            "pnl_portfolio_pct": pnl_portfolio_pct,
                            "exit_reason": exit_reason,
                            "mfe_atr": pos["mfe_atr"],
                            "mae_atr": pos["mae_atr"],
                            "bars_held": pos["bars_held"],
                            "rsi_14": pos["rsi_14"],
                            "adx_15m": pos["adx_15m"],
                            "volume_ratio": pos["volume_ratio"],
                            "atr": pos["atr"],
                            "btc_regime": pos["btc_regime"],
                            "btc_re": pos["btc_re"],
                            "btc_adx": pos["btc_adx"],
                            "balance": balance,
                        }
                    )
                    series.append(balance)
                    pos = None

        if pos is not None:
            continue

        for symbol in symbol_order:
            idx = idx_map[symbol].get(ts)
            if idx is None:
                continue
            frame = frames[symbol]
            row = frame.iloc[idx]
            if bool(row.get("warmup_excluded", False)):
                continue
            if pd.isna(row.get("btc_adx")) or pd.isna(row.get("btc_re")):
                continue
            context = {"btc_regime": row.get("btc_regime")}
            signal = generate_momentum_signal(frame, idx, context)
            if signal is None:
                continue

            atr = float(signal["atr"])
            entry_price = float(signal["entry_price"])
            balance_before_entry = balance
            risk = balance * RISK_PCT
            position_notional = risk * entry_price / (SL_ATR_MULT * atr)
            balance *= 1.0 - ENTRY_FEE
            pos = {
                "symbol": symbol,
                "entry_time": ts,
                "entry_idx": idx,
                "entry_price": entry_price,
                "stop_loss": float(signal["stop_loss"]),
                "take_profit": float(signal["take_profit"]),
                "atr": atr,
                "position_notional": position_notional,
                "balance_before_entry": balance_before_entry,
                "mfe_atr": 0.0,
                "mae_atr": 0.0,
                "bars_held": 0,
                "rsi_14": float(row["rsi"]),
                "adx_15m": float(row["adx"]),
                "volume_ratio": float(row["volume_ratio"]),
                "btc_regime": row.get("btc_regime"),
                "btc_re": float(row["btc_re"]),
                "btc_adx": float(row["btc_adx"]),
            }
            break

    return SimulationResult(log=log, series=series, frames=frames)


def max_drawdown(series: list[float]) -> float:
    if not series:
        return 0.0
    curve = pd.Series(series, dtype="float64")
    peak = curve.cummax()
    return float(((peak - curve) / peak).max() * 100)


def stats(log: list[dict[str, Any]], series: list[float]) -> dict[str, float | int]:
    final_balance = float(series[-1]) if series else float(INITIAL_BALANCE)
    if not log:
        return {
            "trades": 0,
            "win_pct": 0.0,
            "expectancy_pct": 0.0,
            "max_dd_pct": max_drawdown(series),
            "final_balance": final_balance,
            "profit_factor": 0.0,
        }
    df = pd.DataFrame(log)
    pnl = df["pnl_portfolio_pct"].astype(float)
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = pnl[pnl <= 0].sum()
    return {
        "trades": int(len(df)),
        "win_pct": float((pnl > 0).mean() * 100),
        "expectancy_pct": float(pnl.mean()),
        "max_dd_pct": max_drawdown(series),
        "final_balance": final_balance,
        "profit_factor": float(gross_profit / abs(gross_loss)) if gross_loss < 0 else 0.0,
    }


def yearly_stats(log: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    if not log:
        return {str(year): {"trades": 0, "expectancy_pct": 0.0} for year in [2023, 2024, 2025, 2026]}
    df = pd.DataFrame(log)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["year"] = df["entry_time"].dt.year
    out = {}
    for year in [2023, 2024, 2025, 2026]:
        part = df[df["year"] == year]
        out[str(year)] = {
            "trades": int(len(part)),
            "expectancy_pct": float(part["pnl_portfolio_pct"].mean()) if len(part) else 0.0,
        }
    return out


def entry_quality(oos: SimulationResult) -> dict[str, Any]:
    df = pd.DataFrame(oos.log)
    if df.empty:
        return {
            "OOS": {
                "winning_trades": {"count": 0, "avg_mfe_atr": 0.0, "avg_mae_atr": 0.0, "avg_bars_held": 0.0},
                "losing_trades": {"count": 0, "avg_mfe_atr": 0.0, "avg_mae_atr": 0.0, "avg_bars_held": 0.0},
            },
            "forward_return_proxy_OOS": {key: 0.0 for key in [
                "pct_positive_4bars", "pct_positive_8bars", "pct_positive_12bars",
                "avg_return_4bars", "avg_return_8bars", "avg_return_12bars",
                "median_return_4bars", "median_return_8bars", "median_return_12bars",
            ]},
        }

    def side_stats(part: pd.DataFrame) -> dict[str, float | int]:
        return {
            "count": int(len(part)),
            "avg_mfe_atr": float(part["mfe_atr"].mean()) if len(part) else 0.0,
            "avg_mae_atr": float(part["mae_atr"].mean()) if len(part) else 0.0,
            "avg_bars_held": float(part["bars_held"].mean()) if len(part) else 0.0,
        }

    forward: dict[int, list[float]] = {4: [], 8: [], 12: []}
    for trade in oos.log:
        frame = oos.frames[trade["symbol"]]
        entry_idx = int(trade["entry_idx"])
        entry_price = float(trade["entry_price"])
        for bars in forward:
            if entry_idx + bars < len(frame):
                future_close = float(frame.iloc[entry_idx + bars]["close"])
                forward[bars].append((future_close - entry_price) / entry_price * 100)

    proxy = {}
    for bars in [4, 8, 12]:
        arr = np.array(forward[bars], dtype="float64")
        proxy[f"pct_positive_{bars}bars"] = float((arr > 0).mean() * 100) if len(arr) else 0.0
        proxy[f"avg_return_{bars}bars"] = float(arr.mean()) if len(arr) else 0.0
        proxy[f"median_return_{bars}bars"] = float(np.median(arr)) if len(arr) else 0.0

    winners = df[df["pnl_portfolio_pct"] > 0]
    losers = df[df["pnl_portfolio_pct"] <= 0]
    return {
        "OOS": {
            "winning_trades": side_stats(winners),
            "losing_trades": side_stats(losers),
        },
        "forward_return_proxy_OOS": {
            "pct_positive_4bars": proxy["pct_positive_4bars"],
            "pct_positive_8bars": proxy["pct_positive_8bars"],
            "pct_positive_12bars": proxy["pct_positive_12bars"],
            "avg_return_4bars": proxy["avg_return_4bars"],
            "avg_return_8bars": proxy["avg_return_8bars"],
            "avg_return_12bars": proxy["avg_return_12bars"],
            "median_return_4bars": proxy["median_return_4bars"],
            "median_return_8bars": proxy["median_return_8bars"],
            "median_return_12bars": proxy["median_return_12bars"],
        },
    }


def monte_carlo(oos_log: list[dict[str, Any]]) -> dict[str, Any]:
    if len(oos_log) < 50:
        return {
            "executed": "No",
            "reason_if_skipped": "OOS trades < 50",
            "n_simulations": 5000,
            "sample_size": 0,
        }
    pnl = pd.DataFrame(oos_log)["pnl_portfolio_pct"].astype(float).to_numpy()
    sample_size = min(50, len(pnl))
    rng = np.random.default_rng(42)
    finals = []
    exps = []
    for _ in range(5000):
        sample = rng.choice(pnl, size=sample_size, replace=True)
        balance = 100.0
        for value in sample:
            balance *= 1.0 + value / 100.0
        finals.append(balance)
        exps.append(float(sample.mean()))
    finals_arr = np.array(finals)
    exps_arr = np.array(exps)
    return {
        "executed": "Yes",
        "reason_if_skipped": "",
        "n_simulations": 5000,
        "sample_size": int(sample_size),
        "final_balance": {f"p{p}": float(np.percentile(finals_arr, p)) for p in [5, 25, 50, 75, 95]},
        "expectancy": {f"p{p}": float(np.percentile(exps_arr, p)) for p in [5, 50, 95]},
        "probability_positive_expectancy": float((exps_arr > 0).mean() * 100),
        "probability_final_balance_above_100": float((finals_arr > 100).mean() * 100),
    }


def sample_status(trades: int) -> str:
    if trades >= 50:
        return "sufficient"
    if trades >= 30:
        return "borderline"
    return "insufficient"


def acceptance_gate(oos_stats: dict[str, float | int], yearly: dict[str, dict[str, float | int]], quality: dict[str, Any]) -> dict[str, Any]:
    oos_trades = int(oos_stats["trades"])
    oos_exp = float(oos_stats["expectancy_pct"])
    oos_pf = float(oos_stats["profit_factor"])
    max_dd = float(oos_stats["max_dd_pct"])
    pct_pos_4 = float(quality["forward_return_proxy_OOS"]["pct_positive_4bars"])
    yearly_values = [float(yearly[str(year)]["expectancy_pct"]) for year in [2024, 2025, 2026]]

    if oos_trades < 30:
        candidate = "No"
        reason = "insufficient_sample"
    elif oos_exp <= 0:
        candidate = "No"
        reason = "no_positive_oos_edge"
    elif oos_trades < 50:
        candidate = "Maybe"
        reason = "borderline_sample"
    elif oos_pf > 1 and max_dd < 30:
        candidate = "Yes"
        reason = "passes_oos_trade_expectancy_pf_dd_thresholds"
    else:
        candidate = "No"
        reason = "failed_acceptance_thresholds"

    return {
        "OOS_trades_at_least_50": "Yes" if oos_trades >= 50 else "No",
        "OOS_expectancy_positive": "Yes" if oos_exp > 0 else "No",
        "OOS_profit_factor_above_1": "Yes" if oos_pf > 1 else "No",
        "yearly_not_all_negative": "Yes" if any(value >= 0 for value in yearly_values) else "No",
        "max_dd_below_30pct": "Yes" if max_dd < 30 else "No",
        "entry_quality_positive_4bars_above_50pct": "Yes" if pct_pos_4 > 50 else "No",
        "candidate_can_enter_forward_logger_research_only": {
            "value": candidate,
            "reason": reason,
        },
    }


def run_validation() -> dict[str, Any]:
    prepared = prepare()
    full = simulate(FULL_START, END_DATE, prepared)
    is_result = simulate(IS_START, IS_END, prepared)
    oos = simulate(OOS_START, END_DATE, prepared)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    pd.DataFrame(full.log).to_csv(OUTPUT_PATH, index=False)

    full_stats = stats(full.log, full.series)
    is_stats = stats(is_result.log, is_result.series)
    oos_stats = stats(oos.log, oos.series)
    yearly = yearly_stats(full.log)
    quality = entry_quality(oos)
    mc = monte_carlo(oos.log)
    gate = acceptance_gate(oos_stats, yearly, quality)

    results = {
        "momentum_breakout_validation": {
            "strategy_name": STRATEGY_NAME,
            "strategy_version": STRATEGY_VERSION,
            "timeframe": "15m",
            "data_source": "clean CSV data with V12 helper indicators, 2021/2022 excluded_due_source_coverage",
            "portfolio_model": "sequential",
            "same_bar_rule": "SL_first",
            "parameters_modified": "No",
            "full": full_stats,
            "IS_2023": is_stats,
            "OOS_2024_2026": oos_stats,
            "yearly": yearly,
        },
        "momentum_entry_quality": quality,
        "momentum_mc_oos": mc,
        "acceptance_gate": gate,
        "files_created_or_modified": [
            "core/strategies/momentum_breakout.py",
            "backtest/momentum_breakout_validation.py",
            OUTPUT_PATH,
            RESULT_PATH,
        ],
        "not_modified": [
            "V12 entry logic",
            "V12 exit logic",
            "router.py",
            "Telegram",
            "Forward Logger",
            "live trading",
        ],
        "errors": [],
    }
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return results


def main() -> None:
    print(json.dumps(run_validation(), indent=2))


if __name__ == "__main__":
    main()
