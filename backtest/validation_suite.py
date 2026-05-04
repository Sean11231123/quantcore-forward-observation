from __future__ import annotations

import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import binomtest, norm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import COMMISSION, INITIAL_BALANCE
from v12_strategy import (
    RISK_PCT,
    SL_ATR_MULT,
    build_daily_whitelist,
    build_daily_whitelist_with_sources,
    check_entry_long,
    get_whitelist_for_ts,
    get_whitelist_source_for_ts,
)
from backtest.v12_backtest import (
    V12State,
    _exit,
    _load_btc_regime,
    _load_symbols,
    _prepare,
    _ts_index,
)


PARAMS = {
    "top_n": 3,
    "mode": "C3",
    "adx_entry_override": 30.0,
    "re_threshold_override": 0.22,
    "tp_atr_mult": 1.5,
    "no_be": False,
    "be_threshold": 2.5,
}


def sim_params(**overrides) -> dict:
    params = {k: v for k, v in PARAMS.items() if k != "top_n"}
    params.update(overrides)
    return params


@dataclass
class SimResult:
    log: list[dict]
    series: list[float]
    audit: dict


class CachedV12Simulator:
    def __init__(self, top_n: int = 3):
        print("Preparing cached V12 data...")
        raw = _load_symbols()
        btc = _load_btc_regime()
        symbol_raw = {s: p[0] for s, p in raw.items()}
        self.whitelist, self.whitelist_sources = build_daily_whitelist_with_sources(symbol_raw, top_n=top_n)
        self.prepared = {s: _prepare(df15, df1h, btc) for s, (df15, df1h) in raw.items()}
        self.prepared = {s: df.reset_index(drop=True) for s, df in self.prepared.items() if not df.empty}
        self.idx_map = {s: _ts_index(df) for s, df in self.prepared.items()}
        self.ts_list = self._build_ts_list()
        print(f"Cached symbols={len(self.prepared)} bars={len(self.ts_list)}")

    def _build_ts_list(self) -> list[pd.Timestamp]:
        if not self.prepared:
            return []
        first = list(self.prepared.keys())[0]
        return [pd.Timestamp(x) for x in self.prepared[first]["timestamp"].tolist()]

    def simulate(
        self,
        start_date: str,
        end_date: str,
        tp_atr_mult: float = 1.5,
        mode: str = "C3",
        adx_entry_override: float = 30.0,
        re_threshold_override: float = 0.22,
        btc_re_lower: float = 0.20,
        btc_re_upper: float | None = 0.40,
        no_be: bool = False,
        be_threshold: float = 2.5,
    ) -> SimResult:
        state = V12State()
        audit = defaultdict(int)
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        for ts in self.ts_list:
            if ts < start_ts or ts > end_ts:
                continue

            state.balance_series.append(state.balance)

            if state.pos_sym:
                df = self.prepared[state.pos_sym]
                if ts not in self.idx_map[state.pos_sym]:
                    continue

                row = df.iloc[self.idx_map[state.pos_sym][ts]]
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

            wl = get_whitelist_for_ts(self.whitelist, ts)
            whitelist_source_date = get_whitelist_source_for_ts(self.whitelist_sources, ts)
            for sym in wl:
                if sym not in self.prepared or ts not in self.idx_map[sym]:
                    continue

                df = self.prepared[sym]
                row = df.iloc[self.idx_map[sym][ts]]
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

                state.entry_price = row["close"]
                state.entry_time = ts
                state.entry_atr = atr
                risk = state.balance * RISK_PCT
                state.position_notional = risk * state.entry_price / (SL_ATR_MULT * atr)
                state.balance_before_entry = state.balance
                state.balance *= 1.0 - COMMISSION
                state.pos_sym = sym
                state.btc_regime_at_entry = btc.copy()
                state.coin_adx_15m_at_entry = row.get("adx", 0)
                state.coin_adx_1h_at_entry = row.get("adx_1h", 0)
                state.whitelist_source_date = whitelist_source_date
                state.structure_sl = state.entry_price - SL_ATR_MULT * atr
                break

        return SimResult(state.trade_log, state.balance_series, dict(audit))


def max_drawdown_pct(series: list[float]) -> float:
    if not series:
        return 0.0
    s = pd.Series(series, dtype="float64")
    peak = s.cummax()
    dd = (peak - s) / peak
    return float(dd.max() * 100)


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
    wins = int((df["pnl"] > 0).sum())
    std = returns.std(ddof=1)
    sharpe = float(returns.mean() / std * math.sqrt(len(returns))) if std and not np.isnan(std) else 0.0
    return {
        "trades": len(df),
        "wins": wins,
        "win_pct": float((df["pnl"] > 0).mean() * 100),
        "expectancy_pct": float(df["pnl_portfolio_pct"].mean()),
        "max_dd_pct": max_drawdown_pct(series),
        "sharpe": sharpe,
        "final_balance": float(series[-1]) if series else float(df.iloc[-1]["balance"]),
        "skew": float(returns.skew()) if len(returns) > 2 else 0.0,
        "kurt": float(returns.kurtosis() + 3) if len(returns) > 3 else 3.0,
    }


def print_stats(label: str, stats: dict) -> None:
    print(
        f"{label}: trades={stats['trades']} win%={stats['win_pct']:.2f} "
        f"expectancy={stats['expectancy_pct']:.4f}% max_dd={stats['max_dd_pct']:.2f}% "
        f"sharpe={stats['sharpe']:.3f} final={stats['final_balance']:.4f}"
    )


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


def regime_re_buckets(log: list[dict]) -> None:
    print("\n[OOS Regime RE Buckets]")
    if not log:
        print("No OOS trades")
        return

    df = pd.DataFrame(log)
    buckets = [
        ("low <0.25", df[df["btc_re"] < 0.25]),
        ("mid 0.25-0.35", df[(df["btc_re"] >= 0.25) & (df["btc_re"] <= 0.35)]),
        ("high >0.35", df[df["btc_re"] > 0.35]),
    ]
    for label, part in buckets:
        if part.empty:
            print(f"{label}: trades=0 win%=0.00 expectancy=0.0000%")
        else:
            print(
                f"{label}: trades={len(part)} win%={(part['pnl'] > 0).mean() * 100:.2f} "
                f"expectancy={part['pnl_portfolio_pct'].mean():.4f}%"
            )


def run_oos(sim: CachedV12Simulator | None = None) -> SimResult:
    sim = sim or CachedV12Simulator(top_n=PARAMS["top_n"])
    print("\n" + "=" * 60)
    print("MODULE 1: OOS + Regime Buckets + PSR + Bonferroni")
    print("=" * 60)

    is_result = sim.simulate("2021-01-01", "2023-12-31", **sim_params())
    oos_result = sim.simulate("2024-01-01", "2026-04-21", **sim_params())

    is_stats = standard_stats(is_result.log, is_result.series)
    oos_stats = standard_stats(oos_result.log, oos_result.series)
    print_stats("IS  2021-2023", is_stats)
    print_stats("OOS 2024-2026", oos_stats)
    print(f"OOS exits: {dict(Counter(t['exit'] for t in oos_result.log))}")
    regime_re_buckets(oos_result.log)

    psr = probabilistic_sharpe(
        oos_stats["sharpe"],
        sr_benchmark=0.0,
        n=max(oos_stats["trades"], 1),
        skew=oos_stats["skew"],
        kurt=oos_stats["kurt"],
    )
    print(f"\nPSR Sharpe > 0: {psr * 100:.2f}%")

    threshold = 0.05 / 6
    if oos_stats["trades"] > 0:
        result = binomtest(
            k=oos_stats["wins"],
            n=oos_stats["trades"],
            p=0.5,
            alternative="greater",
        )
        significant = result.pvalue < threshold
        print("TP scan tests=6, Bonferroni threshold: p < 0.05/6 = 0.0083")
        print(
            f"Bonferroni corrected OOS win-rate p-value: {result.pvalue:.4f}; "
            f"significant={significant}"
        )
    else:
        print("Bonferroni corrected OOS win-rate p-value: N/A")

    return oos_result


def run_walk_forward(sim: CachedV12Simulator | None = None) -> list[dict]:
    sim = sim or CachedV12Simulator(top_n=PARAMS["top_n"])
    print("\n" + "=" * 60)
    print("MODULE 2: Walk-Forward")
    print("=" * 60)

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
        for tp in [1.5, 2.0, 2.5]:
            result = sim.simulate(
                str(is_start.date()),
                str(is_end.date()),
                **sim_params(tp_atr_mult=tp),
            )
            st = standard_stats(result.log, result.series)
            train.append((tp, st))

        best_tp, best_is = max(train, key=lambda item: item[1]["expectancy_pct"])
        test = sim.simulate(
            str(oos_start.date()),
            str(oos_end.date()),
            **sim_params(tp_atr_mult=best_tp),
        )
        test_stats = standard_stats(test.log, test.series)
        row = {
            "fold": fold,
            "is_start": is_start,
            "is_end": is_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "best_tp": best_tp,
            "is_exp": best_is["expectancy_pct"],
            "oos_trades": test_stats["trades"],
            "oos_win": test_stats["win_pct"],
            "oos_exp": test_stats["expectancy_pct"],
        }
        rows.append(row)
        print(
            f"Fold {fold}: IS={is_start:%Y-%m}~{is_end:%Y-%m}, "
            f"OOS={oos_start:%Y-%m}~{oos_end:%Y-%m}, best_tp={best_tp}, "
            f"trades={test_stats['trades']}, win%={test_stats['win_pct']:.2f}, "
            f"exp={test_stats['expectancy_pct']:.4f}%"
        )

        start = start + pd.DateOffset(months=3)
        fold += 1

    if rows:
        is_avg = float(np.mean([r["is_exp"] for r in rows]))
        oos_avg = float(np.mean([r["oos_exp"] for r in rows]))
        wfe = oos_avg / is_avg if is_avg else 0.0
        print(
            f"Overall: IS_avg_exp={is_avg:.4f}% OOS_avg_exp={oos_avg:.4f}% "
            f"Walk-Forward Efficiency={wfe:.3f}"
        )
    return rows


def run_monte_carlo(pnl_series, n=1000, output_path="backtest/monte_carlo_chart.png"):
    print("\n" + "=" * 60)
    print("MODULE 3: Monte Carlo")
    print("=" * 60)
    if not pnl_series:
        print("No OOS pnl series; Monte Carlo skipped")
        return {}

    rng = np.random.default_rng(42)
    returns = np.array(pnl_series, dtype="float64") / 100
    curves = []
    max_dds = []
    finals = []
    for _ in range(n):
        sample = rng.choice(returns, size=len(returns), replace=True)
        curve = INITIAL_BALANCE * np.cumprod(1 + sample)
        curves.append(curve)
        peak = np.maximum.accumulate(curve)
        max_dds.append(float(np.max((peak - curve) / peak) * 100))
        finals.append(float(curve[-1]))

    true_curve = INITIAL_BALANCE * np.cumprod(1 + returns)
    true_peak = np.maximum.accumulate(true_curve)
    true_dd = float(np.max((true_peak - true_curve) / true_peak) * 100)
    summary = {
        "final_p05": float(np.percentile(finals, 5)),
        "final_p50": float(np.percentile(finals, 50)),
        "final_p95": float(np.percentile(finals, 95)),
        "maxdd_p50": float(np.percentile(max_dds, 50)),
        "maxdd_p95": float(np.percentile(max_dds, 95)),
        "true_final": float(true_curve[-1]),
        "true_maxdd": true_dd,
    }
    print(
        f"Final balance p5/p50/p95: {summary['final_p05']:.2f} / "
        f"{summary['final_p50']:.2f} / {summary['final_p95']:.2f}"
    )
    print(
        f"MaxDD p50/p95: {summary['maxdd_p50']:.2f}% / {summary['maxdd_p95']:.2f}% "
        f"| true OOS maxDD={summary['true_maxdd']:.2f}%"
    )

    plt.figure(figsize=(10, 6))
    for curve in curves:
        plt.plot(curve, color="gray", alpha=0.035, linewidth=0.8)
    plt.plot(true_curve, color="orange", linewidth=2.2, label="True OOS")
    plt.title("Monte Carlo OOS Equity Curves")
    plt.xlabel("Trade")
    plt.ylabel("Balance")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()
    print(f"Chart saved: {output_path}")
    return summary


if __name__ == "__main__":
    print("=" * 60)
    print("QUANTCORE VALIDATION SUITE")
    print("=" * 60)
    simulator = CachedV12Simulator(top_n=PARAMS["top_n"])
    oos = run_oos(simulator)
    run_walk_forward(simulator)
    pnl_series = [t["pnl_portfolio_pct"] for t in oos.log]
    run_monte_carlo(pnl_series)
