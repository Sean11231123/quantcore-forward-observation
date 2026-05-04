from __future__ import annotations

import math
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import binomtest, norm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import INITIAL_BALANCE


COMMISSION = 0.0005


def max_drawdown_pct(series: list[float]) -> float:
    if not series:
        return 0.0
    s = pd.Series(series, dtype="float64")
    peak = s.cummax()
    return float(((peak - s) / peak).max() * 100)


def standard_stats(log: list[dict], series: list[float]) -> dict:
    if not log:
        return {
            "trades": 0,
            "wins": 0,
            "win_pct": 0.0,
            "expectancy_pct": 0.0,
            "max_dd_pct": max_drawdown_pct(series),
            "sharpe": 0.0,
            "final_balance": float(series[-1]) if series else float(INITIAL_BALANCE),
            "skew": 0.0,
            "kurt": 3.0,
        }

    df = pd.DataFrame(log)
    returns = df["pnl_portfolio_pct"].astype(float) / 100
    std = returns.std(ddof=1)
    sharpe = float(returns.mean() / std * math.sqrt(len(returns))) if std and not np.isnan(std) else 0.0
    return {
        "trades": len(df),
        "wins": int((df["pnl"] > 0).sum()),
        "win_pct": float((df["pnl"] > 0).mean() * 100),
        "expectancy_pct": float(df["pnl_portfolio_pct"].mean()),
        "max_dd_pct": max_drawdown_pct(series),
        "sharpe": sharpe,
        "final_balance": float(series[-1]) if series else float(df.iloc[-1]["balance"]),
        "skew": float(returns.skew()) if len(returns) > 2 else 0.0,
        "kurt": float(returns.kurtosis() + 3) if len(returns) > 3 else 3.0,
    }


def probabilistic_sharpe(sr_hat, sr_benchmark=0.0, n=100, skew=0, kurt=3):
    if n <= 1:
        return 0.0
    sr_std = np.sqrt(
        (1 + (0.5 * sr_hat**2) - skew * sr_hat + ((kurt - 3) / 4) * sr_hat**2)
        / (n - 1)
    )
    if sr_std == 0 or np.isnan(sr_std):
        return 0.0
    return float(norm.cdf((sr_hat - sr_benchmark) / sr_std))


def simulate_sequential(simulator, signals_by_ts, start_date: str, end_date: str, params: dict):
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    balance = float(INITIAL_BALANCE)
    series: list[float] = []
    log: list[dict] = []
    pos = None

    for ts in simulator.ts_list:
        if ts < start_ts or ts > end_ts:
            continue
        series.append(balance)

        if pos is not None:
            row = simulator.row_at(pos["symbol"], ts)
            if row is not None:
                pos["bars"] += 1
                exit_type, exit_px = simulator.check_exit(pos, row, params)
                if exit_type:
                    if pos["side"] == "buy":
                        pnl = pos["notional"] * (exit_px - pos["entry"]) / pos["entry"]
                    else:
                        pnl = pos["notional"] * (pos["entry"] - exit_px) / pos["entry"]
                    bal_before = balance
                    balance += pnl
                    balance *= 1.0 - COMMISSION
                    round_trip_before = pos.get("balance_before_entry", bal_before)
                    net_pnl = balance - round_trip_before
                    log.append(
                        {
                            "ts": ts,
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "exit": exit_type,
                            "pnl": pnl,
                            "net_pnl": net_pnl,
                            "balance_before": round_trip_before,
                            "pnl_portfolio_pct": net_pnl / round_trip_before * 100 if round_trip_before else 0.0,
                            "balance": balance,
                            "bars": pos["bars"],
                            "btc_re": pos.get("btc_re", 0.0),
                        }
                    )
                    series.append(balance)
                    pos = None

        if pos is None:
            for signal in signals_by_ts.get(ts, []):
                entry = signal["price"]
                stop = signal["stop_loss"]
                risk_per_unit = abs(entry - stop)
                if risk_per_unit <= 0:
                    continue
                balance_before_entry = balance
                risk = balance * 0.01
                notional = risk * entry / risk_per_unit
                balance *= 1.0 - COMMISSION
                pos = {
                    **signal,
                    "entry": entry,
                    "notional": notional,
                    "balance_before_entry": balance_before_entry,
                    "bars": 0,
                }
                break

    return log, series


def run_validation(
    simulator,
    strategy_name: str,
    default_params: dict,
    wf_grid: list[dict],
    bonferroni_tests: int,
    report_path: str,
    chart_path: str,
):
    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("=" * 60)
    emit(f"{strategy_name.upper()} VALIDATION")
    emit("=" * 60)

    full_log, full_series, _ = simulator.simulate("2021-01-01", "2026-04-21", **default_params)
    is_log, is_series, _ = simulator.simulate("2021-01-01", "2023-12-31", **default_params)
    oos_log, oos_series, _ = simulator.simulate("2024-01-01", "2026-04-21", **default_params)

    full = standard_stats(full_log, full_series)
    is_stats = standard_stats(is_log, is_series)
    oos = standard_stats(oos_log, oos_series)

    emit("\n[Full Backtest]")
    emit(format_stats("2021-2026", full))
    emit("\n[OOS]")
    emit(format_stats("IS  2021-2023", is_stats))
    emit(format_stats("OOS 2024-2026", oos))
    emit(f"OOS exits: {dict(Counter(t['exit'] for t in oos_log))}")

    psr = probabilistic_sharpe(
        oos["sharpe"],
        sr_benchmark=0.0,
        n=max(oos["trades"], 1),
        skew=oos["skew"],
        kurt=oos["kurt"],
    )
    threshold = 0.05 / bonferroni_tests
    if oos["trades"]:
        bt = binomtest(oos["wins"], oos["trades"], p=0.5, alternative="greater")
        pvalue = bt.pvalue
        significant = pvalue < threshold
    else:
        pvalue = float("nan")
        significant = False
    emit(f"PSR Sharpe > 0: {psr * 100:.2f}%")
    emit(
        f"Bonferroni p-value={pvalue:.4f}, threshold={threshold:.4f}, "
        f"significant={significant}"
    )

    emit("\n[Walk-Forward]")
    rows = run_walk_forward_rows(simulator, wf_grid)
    for row in rows:
        emit(
            f"Fold {row['fold']}: IS={row['is_start']:%Y-%m}~{row['is_end']:%Y-%m}, "
            f"OOS={row['oos_start']:%Y-%m}~{row['oos_end']:%Y-%m}, "
            f"best={row['best_params']}, trades={row['oos_trades']}, "
            f"win%={row['oos_win']:.2f}, exp={row['oos_exp']:.4f}%"
        )
    if rows:
        is_avg = float(np.mean([r["is_exp"] for r in rows]))
        oos_avg = float(np.mean([r["oos_exp"] for r in rows]))
        wfe = oos_avg / is_avg if is_avg else 0.0
    else:
        wfe = 0.0
    emit(f"Walk-Forward Efficiency={wfe:.3f}")

    emit("\n[Monte Carlo]")
    mc = run_monte_carlo(
        [t["pnl_portfolio_pct"] for t in oos_log],
        chart_path,
    )
    if mc:
        emit(
            f"final p5/p50/p95={mc['final_p05']:.2f}/{mc['final_p50']:.2f}/{mc['final_p95']:.2f}"
        )
        emit(f"maxDD p50/p95={mc['maxdd_p50']:.2f}%/{mc['maxdd_p95']:.2f}%")
        emit(f"positive return probability={mc['positive_prob'] * 100:.2f}%")
        emit(f"chart={chart_path}")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return {
        "full": full,
        "is": is_stats,
        "oos": oos,
        "wfe": wfe,
        "mc": mc,
        "psr": psr,
        "bonferroni_p": pvalue,
        "bonferroni_significant": significant,
    }


def format_stats(label: str, st: dict) -> str:
    return (
        f"{label}: trades={st['trades']} win%={st['win_pct']:.2f} "
        f"expectancy={st['expectancy_pct']:.4f}% max_dd={st['max_dd_pct']:.2f}% "
        f"sharpe={st['sharpe']:.3f} final={st['final_balance']:.4f}"
    )


def run_walk_forward_rows(simulator, wf_grid: list[dict]) -> list[dict]:
    rows = []
    start = pd.Timestamp("2021-01-01")
    final_end = pd.Timestamp("2026-04-21")
    fold = 1
    while True:
        is_start = start
        is_end = is_start + pd.DateOffset(months=12) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=3) - pd.DateOffset(days=1)
        if oos_start > final_end:
            break
        oos_end = min(oos_end, final_end)

        train = []
        for params in wf_grid:
            log, series, _ = simulator.simulate(str(is_start.date()), str(is_end.date()), **params)
            train.append((params, standard_stats(log, series)))
        best_params, best_stats = max(train, key=lambda item: item[1]["expectancy_pct"])

        log, series, _ = simulator.simulate(str(oos_start.date()), str(oos_end.date()), **best_params)
        test_stats = standard_stats(log, series)
        rows.append(
            {
                "fold": fold,
                "is_start": is_start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
                "best_params": best_params,
                "is_exp": best_stats["expectancy_pct"],
                "oos_trades": test_stats["trades"],
                "oos_win": test_stats["win_pct"],
                "oos_exp": test_stats["expectancy_pct"],
            }
        )
        start = start + pd.DateOffset(months=3)
        fold += 1
    return rows


def run_monte_carlo(pnl_series, chart_path: str, n=1000) -> dict:
    if not pnl_series:
        return {}
    rng = np.random.default_rng(42)
    returns = np.array(pnl_series, dtype="float64") / 100
    curves = []
    finals = []
    max_dds = []
    for _ in range(n):
        sample = rng.choice(returns, size=len(returns), replace=True)
        curve = INITIAL_BALANCE * np.cumprod(1 + sample)
        curves.append(curve)
        finals.append(float(curve[-1]))
        peak = np.maximum.accumulate(curve)
        max_dds.append(float(np.max((peak - curve) / peak) * 100))

    true_curve = INITIAL_BALANCE * np.cumprod(1 + returns)
    positive_prob = float(np.mean(np.array(finals) > INITIAL_BALANCE))

    plt.figure(figsize=(10, 6))
    for curve in curves:
        plt.plot(curve, color="gray", alpha=0.035, linewidth=0.8)
    plt.plot(true_curve, color="orange", linewidth=2.2, label="True OOS")
    plt.title(os.path.basename(chart_path))
    plt.xlabel("Trade")
    plt.ylabel("Balance")
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path, dpi=160)
    plt.close()

    return {
        "final_p05": float(np.percentile(finals, 5)),
        "final_p50": float(np.percentile(finals, 50)),
        "final_p95": float(np.percentile(finals, 95)),
        "maxdd_p50": float(np.percentile(max_dds, 50)),
        "maxdd_p95": float(np.percentile(max_dds, 95)),
        "positive_prob": positive_prob,
    }
