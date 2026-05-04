from __future__ import annotations

import os
import sys
from collections import defaultdict
from itertools import product

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategy_validation_common import run_validation, simulate_sequential
from backtest.v12_backtest import _load_btc_regime, _load_symbols, _prepare, _ts_index


class VolatilityExpansionBacktester:
    def __init__(self):
        print("Preparing VolatilityExpansion data...")
        raw = _load_symbols()
        btc = _load_btc_regime()
        self.symbols = list(raw.keys())
        self.prepared = {s: _prepare(df15, df1h, btc).reset_index(drop=True) for s, (df15, df1h) in raw.items()}
        self.prepared = {s: df for s, df in self.prepared.items() if not df.empty}
        self.idx_map = {s: _ts_index(df) for s, df in self.prepared.items()}
        first = list(self.prepared.keys())[0]
        self.ts_list = [pd.Timestamp(x) for x in self.prepared[first]["timestamp"].tolist()]
        self._signal_cache = {}
        print(f"VolExpansion cached symbols={len(self.prepared)} bars={len(self.ts_list)}")

    def row_at(self, symbol: str, ts: pd.Timestamp):
        idx = self.idx_map.get(symbol, {}).get(ts)
        if idx is None:
            return None
        return self.prepared[symbol].iloc[idx]

    def _ensure_indicators(self, sym: str, bb_period: int):
        df = self.prepared[sym]
        suffix = f"_{bb_period}"
        if f"bb_mid{suffix}" in df.columns:
            return df
        df = df.copy()
        close, high, low = df["close"], df["high"], df["low"]
        mid = close.rolling(bb_period).mean()
        std = close.rolling(bb_period).std()
        df[f"bb_mid{suffix}"] = mid
        df[f"bb_upper{suffix}"] = mid + 2 * std
        df[f"bb_lower{suffix}"] = mid - 2 * std
        df[f"bb_width{suffix}"] = (df[f"bb_upper{suffix}"] - df[f"bb_lower{suffix}"]) / mid
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        df["atr14"] = tr.rolling(14).mean()
        df["atr_ma10"] = df["atr14"].rolling(10).mean()
        self.prepared[sym] = df
        return df

    def _signals(self, params: dict):
        key = tuple(sorted(params.items()))
        if key in self._signal_cache:
            return self._signal_cache[key]

        signals = defaultdict(list)
        bb_period = params["bb_period"]
        suffix = f"_{bb_period}"
        for sym in self.symbols:
            df = self._ensure_indicators(sym, bb_period)
            width = df[f"bb_width{suffix}"]
            min_width = width.rolling(11).min().shift(1)
            bb_expansion = width > min_width * (1 + params["bb_expansion_thresh"])
            atr_expansion = df["atr14"] > df["atr_ma10"] * params["atr_expansion_mult"]
            long_mask = (
                bb_expansion
                & atr_expansion
                & (df["close"] > df[f"bb_upper{suffix}"])
                & (df["btc_ema20"] > df["btc_ema50"])
            )
            short_mask = (
                bb_expansion
                & atr_expansion
                & (df["close"] < df[f"bb_lower{suffix}"])
                & (df["btc_ema20"] < df["btc_ema50"])
            )

            for _, row in df[long_mask].iterrows():
                width_dollar = row["close"] * row[f"bb_width{suffix}"]
                stop = row[f"bb_mid{suffix}"]
                target = row["close"] + width_dollar * params["tp_bb_mult"]
                if pd.isna(stop) or pd.isna(target) or stop >= row["close"]:
                    continue
                signals[pd.Timestamp(row["timestamp"])].append(
                    {
                        "symbol": sym,
                        "side": "buy",
                        "price": row["close"],
                        "stop_loss": stop,
                        "take_profit": target,
                        "btc_re": row.get("btc_re", 0.0),
                    }
                )
            for _, row in df[short_mask].iterrows():
                width_dollar = row["close"] * row[f"bb_width{suffix}"]
                stop = row[f"bb_mid{suffix}"]
                target = row["close"] - width_dollar * params["tp_bb_mult"]
                if pd.isna(stop) or pd.isna(target) or stop <= row["close"]:
                    continue
                signals[pd.Timestamp(row["timestamp"])].append(
                    {
                        "symbol": sym,
                        "side": "sell",
                        "price": row["close"],
                        "stop_loss": stop,
                        "take_profit": target,
                        "btc_re": row.get("btc_re", 0.0),
                    }
                )

        self._signal_cache[key] = dict(signals)
        return self._signal_cache[key]

    def simulate(
        self,
        start_date,
        end_date,
        bb_period=20,
        bb_expansion_thresh=0.20,
        atr_expansion_mult=1.10,
        tp_bb_mult=1.5,
        time_stop_bars=8,
    ):
        params = {
            "bb_period": bb_period,
            "bb_expansion_thresh": bb_expansion_thresh,
            "atr_expansion_mult": atr_expansion_mult,
            "tp_bb_mult": tp_bb_mult,
            "time_stop_bars": time_stop_bars,
        }
        log, series = simulate_sequential(self, self._signals(params), start_date, end_date, params)
        return log, series, {}

    def check_exit(self, pos: dict, row: pd.Series, params: dict):
        suffix = f"_{params['bb_period']}"
        mid = row[f"bb_mid{suffix}"]
        if pos["side"] == "buy":
            if row["high"] >= pos["take_profit"]:
                return "TAKE_PROFIT", pos["take_profit"]
            if row["low"] <= mid:
                return "BB_MID_SL", mid
        else:
            if row["low"] <= pos["take_profit"]:
                return "TAKE_PROFIT", pos["take_profit"]
            if row["high"] >= mid:
                return "BB_MID_SL", mid
        if pos["bars"] >= params["time_stop_bars"]:
            return "TIME_STOP", row["close"]
        return None, None


def main():
    sim = VolatilityExpansionBacktester()
    default = {
        "bb_period": 20,
        "bb_expansion_thresh": 0.20,
        "atr_expansion_mult": 1.10,
        "tp_bb_mult": 1.5,
        "time_stop_bars": 8,
    }
    grid = [
        {
            "bb_period": 20,
            "bb_expansion_thresh": bb_thresh,
            "atr_expansion_mult": 1.10,
            "tp_bb_mult": tp_mult,
            "time_stop_bars": 8,
        }
        for bb_thresh, tp_mult in product([0.15, 0.20, 0.25], [1.0, 1.5, 2.0])
    ]
    run_validation(
        sim,
        "Volatility Expansion Strategy",
        default,
        grid,
        bonferroni_tests=9,
        report_path="backtest/vol_expansion_validation.txt",
        chart_path="backtest/vol_expansion_mc.png",
    )


if __name__ == "__main__":
    main()
