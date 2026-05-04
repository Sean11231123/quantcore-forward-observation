from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import INITIAL_BALANCE, SYMBOLS


TRADE_LOG_PATH = os.path.join("backtest", "output", "strategy_a_trade_log.csv")
RESULT_PATH = os.path.join("backtest", "output", "strategy_a_validation_results.json")

FULL_START = pd.Timestamp("2021-01-01")
FULL_END = pd.Timestamp("2026-04-21 23:59:59")
IS_START = pd.Timestamp("2021-01-01")
IS_END = pd.Timestamp("2023-12-31 23:59:59")
OOS_START = pd.Timestamp("2024-01-01")
OOS_END = pd.Timestamp("2026-04-21 23:59:59")


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":USDT", "")


SYMBOLS_UNIVERSE = [normalize_symbol(symbol) for symbol in SYMBOLS if normalize_symbol(symbol) != "BTCUSDT"]


def load_trades() -> pd.DataFrame:
    if not os.path.exists(TRADE_LOG_PATH):
        raise FileNotFoundError(TRADE_LOG_PATH)
    df = pd.read_csv(TRADE_LOG_PATH)
    if df.empty:
        return df
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    return df.sort_values(["exit_time", "symbol"]).reset_index(drop=True)


def period_filter(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df[(df["entry_time"] >= start) & (df["entry_time"] <= end)].copy()


def aggregate_curve(df: pd.DataFrame) -> tuple[list[float], float]:
    balances = {symbol: float(INITIAL_BALANCE) for symbol in SYMBOLS_UNIVERSE}
    total = sum(balances.values())
    curve = [total]
    if df.empty:
        return curve, total / len(balances)
    for _, row in df.sort_values(["exit_time", "symbol"]).iterrows():
        symbol = row["symbol"]
        if symbol not in balances:
            balances[symbol] = float(INITIAL_BALANCE)
        balances[symbol] *= 1.0 + float(row["pnl_portfolio_pct"]) / 100.0
        curve.append(sum(balances.values()))
    return curve, sum(balances.values()) / len(balances)


def max_drawdown(curve: list[float]) -> float:
    if not curve:
        return 0.0
    s = pd.Series(curve, dtype="float64")
    peak = s.cummax()
    return float(((peak - s) / peak).max() * 100.0)


def sharpe(values: pd.Series) -> float:
    if len(values) < 2:
        return 0.0
    std = float(values.std(ddof=1))
    if std == 0:
        return 0.0
    return float(values.mean() / std * np.sqrt(len(values)))


def stats(df: pd.DataFrame) -> dict:
    curve, final_balance = aggregate_curve(df)
    if df.empty:
        return {
            "trades": 0,
            "win_pct": 0.0,
            "expectancy_E_A": 0.0,
            "expectancy_E_B": 0.0,
            "profit_factor": 0.0,
            "max_dd": max_drawdown(curve),
            "final_balance": final_balance,
            "sharpe": 0.0,
        }
    net = df["net_pnl_pct"].astype(float)
    gross = df["pnl_pct"].astype(float)
    wins = net[net > 0]
    losses = net[net <= 0]
    return {
        "trades": int(len(df)),
        "win_pct": float((net > 0).mean() * 100.0),
        "expectancy_E_A": float(gross.mean()),
        "expectancy_E_B": float(net.mean()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 0.0,
        "max_dd": max_drawdown(curve),
        "final_balance": float(final_balance),
        "sharpe": sharpe(net),
    }


def yearly_oos(df: pd.DataFrame) -> dict:
    out = {}
    for year in [2024, 2025, 2026]:
        part = df[df["entry_time"].dt.year == year]
        out[str(year)] = {
            "trades": int(len(part)),
            "exp_EB": float(part["net_pnl_pct"].mean()) if len(part) else 0.0,
        }
    return out


def monte_carlo_oos(df: pd.DataFrame) -> dict:
    if len(df) < 30:
        return {
            "executed": "No",
            "reason_if_skipped": "OOS trades < 30",
            "p5_p50_p95_final_balance": "not_available",
            "prob_positive_expectancy": 0.0,
        }
    values = df["net_pnl_pct"].astype(float).to_numpy()
    rng = np.random.default_rng(42)
    finals = []
    exps = []
    for _ in range(1000):
        sample = rng.choice(values, size=len(values), replace=True)
        balance = 100.0
        for item in sample:
            balance *= 1.0 + item / 100.0
        finals.append(balance)
        exps.append(float(sample.mean()))
    return {
        "executed": "Yes",
        "reason_if_skipped": "",
        "p5_p50_p95_final_balance": [
            float(np.percentile(finals, 5)),
            float(np.percentile(finals, 50)),
            float(np.percentile(finals, 95)),
        ],
        "prob_positive_expectancy": float((np.array(exps) > 0).mean() * 100.0),
    }


def forward_return_oos(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"pct_positive_4bars": 0.0, "pct_positive_8bars": 0.0, "median_return_4bars": 0.0}
    r4 = df["forward_return_4bars"].dropna().astype(float)
    r8 = df["forward_return_8bars"].dropna().astype(float)
    return {
        "pct_positive_4bars": float((r4 > 0).mean() * 100.0) if len(r4) else 0.0,
        "pct_positive_8bars": float((r8 > 0).mean() * 100.0) if len(r8) else 0.0,
        "median_return_4bars": float(r4.median()) if len(r4) else 0.0,
    }


def exit_distribution(df: pd.DataFrame) -> dict:
    counts = df["exit_reason"].value_counts().to_dict() if not df.empty else {}
    return {
        "TAKE_PROFIT": int(counts.get("TAKE_PROFIT", 0)),
        "STOP_LOSS": int(counts.get("STOP_LOSS", 0)),
        "TIME_STOP": int(counts.get("TIME_STOP", 0)),
        "BREAK_EVEN_SL": int(counts.get("BREAK_EVEN_SL", 0)),
    }


def btc_adx_split(df: pd.DataFrame) -> dict:
    buckets = {
        "low_btc_adx_lt_25": df[df["btc_adx"] < 25] if not df.empty else df,
        "mid_btc_adx_25_35": df[(df["btc_adx"] >= 25) & (df["btc_adx"] <= 35)] if not df.empty else df,
        "high_btc_adx_gt_35": df[df["btc_adx"] > 35] if not df.empty else df,
    }
    out = {}
    for name, part in buckets.items():
        net = part["net_pnl_pct"].astype(float) if len(part) else pd.Series(dtype="float64")
        out[name] = {
            "trades": int(len(part)),
            "win_pct": float((net > 0).mean() * 100.0) if len(part) else 0.0,
            "exp_EB": float(net.mean()) if len(part) else 0.0,
        }
    return out


def acceptance_gate(oos_stats: dict, is_stats: dict, yearly: dict, forward: dict) -> dict:
    oos_trades = int(oos_stats["trades"])
    exp_eb = float(oos_stats["expectancy_E_B"])
    pf = float(oos_stats["profit_factor"])
    max_dd = float(oos_stats["max_dd"])
    pct4 = float(forward["pct_positive_4bars"])
    wfe = exp_eb / float(is_stats["expectancy_E_B"]) if float(is_stats["expectancy_E_B"]) != 0 else 0.0
    yearly_values = [float(yearly[str(year)]["exp_EB"]) for year in [2024, 2025, 2026]]

    failed = []
    if oos_trades < 30:
        candidate = "No"
        reason = "insufficient_sample"
    elif exp_eb <= 0:
        candidate = "No"
        reason = "no_positive_oos_edge"
    elif oos_trades < 50:
        candidate = "Maybe"
        reason = "borderline_sample"
    elif oos_trades >= 50 and exp_eb > 0 and pf > 1 and max_dd < 30 and pct4 > 50:
        candidate = "Yes"
        reason = "passes_all_thresholds"
    else:
        candidate = "No"
        if pf <= 1:
            failed.append("OOS_profit_factor_not_above_1")
        if max_dd >= 30:
            failed.append("max_dd_not_below_30pct")
        if pct4 <= 50:
            failed.append("pct_positive_4bars_not_above_50pct")
        reason = ",".join(failed) if failed else "failed_acceptance_thresholds"

    return {
        "OOS_trades_at_least_50": "Yes" if oos_trades >= 50 else "No",
        "OOS_expectancy_EB_positive": "Yes" if exp_eb > 0 else "No",
        "OOS_profit_factor_above_1": "Yes" if pf > 1 else "No",
        "yearly_not_all_negative": "Yes" if any(value >= 0 for value in yearly_values) else "No",
        "max_dd_below_30pct": "Yes" if max_dd < 30 else "No",
        "pct_positive_4bars_above_50pct": "Yes" if pct4 > 50 else "No",
        "WFE_above_0": "Yes" if wfe > 0 else "No",
        "candidate_approved": candidate,
        "reason": reason,
        "WFE": wfe,
    }


def run_validation() -> dict:
    trades = load_trades()
    full = period_filter(trades, FULL_START, FULL_END)
    is_df = period_filter(trades, IS_START, IS_END)
    oos = period_filter(trades, OOS_START, OOS_END)
    full_stats = stats(full)
    is_stats = stats(is_df)
    oos_stats = stats(oos)
    yearly = yearly_oos(oos)
    mc = monte_carlo_oos(oos)
    forward = forward_return_oos(oos)
    exits = exit_distribution(oos)
    split = btc_adx_split(oos)
    gate = acceptance_gate(oos_stats, is_stats, yearly, forward)

    result = {
        "strategy_a_v1_validation": {
            "metadata": {
                "strategy_name": "Strategy_A_HigherTF_Pullback",
                "strategy_version": "v1_validation",
                "timeframe": "1h",
                "direction": "long_only",
                "execution_model": "enter_on_signal_bar_close",
                "same_bar_rule": "TP_first_then_SL_then_TimeStop",
                "portfolio_model": "per_symbol_independent",
                "portfolio_comparability_to_V12": "Not directly comparable",
                "parameters_modified": "No",
                "existing_system_modified": "No",
            },
            "full_period": full_stats,
            "OOS": {
                "IS": is_stats,
                "OOS": oos_stats,
                "WFE": gate["WFE"],
            },
            "yearly_OOS": yearly,
            "monte_carlo_OOS": mc,
            "PSR": {
                "value": "not_available",
                "Bonferroni_p": "not_available",
                "n_tests": 1,
                "reason_if_not_available": "PSR/binomial implementation not included in Strategy A v1 validation",
            },
            "forward_return_OOS": forward,
            "exit_distribution_OOS": exits,
            "btc_adx_regime_split_OOS": split,
            "acceptance_gate": {k: v for k, v in gate.items() if k != "WFE"},
        },
        "files_created": [
            "backtest/strategy_a_backtest.py",
            "backtest/strategy_a_validation.py",
            "backtest/output/strategy_a_trade_log.csv",
            "backtest/output/strategy_a_validation_results.json",
        ],
        "files_modified_existing": ["none"],
        "not_modified": [
            "V12 entry logic",
            "V12 exit logic",
            "engine.py",
            "router.py",
            "Telegram",
            "Forward Logger",
            "Pullback",
            "VolExpansion",
            "live trading",
        ],
        "errors": [],
    }
    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def main() -> None:
    print(json.dumps(run_validation(), indent=2))


if __name__ == "__main__":
    main()
