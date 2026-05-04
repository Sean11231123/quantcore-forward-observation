from __future__ import annotations

import os
import sys
from collections import OrderedDict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategy_validation_common import max_drawdown_pct, standard_stats
from backtest.v12_backtest import simulate_v12_v2


IS_DATE_RANGE = ("2021-01-01", "2023-12-31")

BASE_PARAMS = {
    "top_n": 3,
    "mode": "C3",
    "tp_atr_mult": 1.5,
    "adx_entry_override": 30.0,
    "re_threshold_override": 0.22,
    "btc_re_lower": 0.20,
    "btc_re_upper": 0.40,
    "no_be": False,
    "be_threshold": 2.5,
}

FILTERS = OrderedDict(
    [
        ("F0_baseline", {}),
        ("F1_volume", {"volume_ratio_min": 1.5}),
        ("F3_no_exhaustion", {"candle_close_position_max": 0.82}),
        (
            "F4_combined",
            {"volume_ratio_min": 1.5, "candle_close_position_max": 0.82},
        ),
    ]
)


def profit_factor(log: list[dict]) -> float:
    wins = sum(float(t["pnl_portfolio_pct"]) for t in log if float(t["pnl_portfolio_pct"]) > 0)
    losses = abs(sum(float(t["pnl_portfolio_pct"]) for t in log if float(t["pnl_portfolio_pct"]) < 0))
    return wins / losses if losses else 0.0


def yearly_stats(log: list[dict]) -> dict[int, dict]:
    df = pd.DataFrame(log)
    out = {}
    for year in [2021, 2022, 2023]:
        if df.empty:
            out[year] = {"trades": 0, "expectancy_pct": 0.0}
            continue
        source = df["exit_time"] if "exit_time" in df.columns else df["ts"]
        part = df[pd.to_datetime(source).dt.year == year]
        out[year] = {
            "trades": int(len(part)),
            "expectancy_pct": float(part["pnl_portfolio_pct"].mean()) if len(part) else 0.0,
        }
    return out


def run():
    results = {}
    for name, filter_params in FILTERS.items():
        params = dict(BASE_PARAMS)
        params.update(filter_params)
        log, series, _ = simulate_v12_v2(
            start_date=IS_DATE_RANGE[0],
            end_date=IS_DATE_RANGE[1],
            **params,
        )
        stats = standard_stats(log, series)
        stats["profit_factor"] = profit_factor(log)
        stats["yearly"] = yearly_stats(log)
        results[name] = stats
    return results


def main():
    results = run()
    print("is_filter_backtest:")
    labels = [
        ("F0_baseline", "F0_baseline"),
        ("F1_volume", "F1_volume"),
        ("F3_no_exhaustion", "F3_no_exhaustion"),
        ("F4_combined", "F4_combined"),
    ]
    for key, label in labels:
        st = results[key]
        print(
            f"  {label}: trades={st['trades']} win%={st['win_pct']:.2f}% "
            f"exp={st['expectancy_pct']:.4f}% dd={st['max_dd_pct']:.2f}% "
            f"final={st['final_balance']:.2f} pf={st['profit_factor']:.4f}"
        )

    print("")
    print("  yearly_breakdown:")
    yearly_labels = [
        ("F0", "F0_baseline"),
        ("F1", "F1_volume"),
        ("F3", "F3_no_exhaustion"),
        ("F4", "F4_combined"),
    ]
    for short, key in yearly_labels:
        yearly = results[key]["yearly"]
        parts = [
            f"{year}: trades={yearly[year]['trades']} expectancy={yearly[year]['expectancy_pct']:.4f}%"
            for year in [2021, 2022, 2023]
        ]
        print(f"    {short}: " + " ".join(parts))


if __name__ == "__main__":
    main()
