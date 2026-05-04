from __future__ import annotations

import os
import sys
from collections import defaultdict
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategy_validation_common import run_validation, simulate_sequential
from backtest.v12_backtest import _load_btc_regime, _load_symbols, _prepare, _ts_index


class PullbackBacktester:
    def __init__(self):
        print("Preparing Pullback data...")
        raw = _load_symbols()
        btc = _load_btc_regime()
        self.symbols = list(raw.keys())
        self.prepared = {s: self._add_indicators(_prepare(df15, df1h, btc)) for s, (df15, df1h) in raw.items()}
        self.prepared = {s: df.reset_index(drop=True) for s, df in self.prepared.items() if not df.empty}
        self.idx_map = {s: _ts_index(df) for s, df in self.prepared.items()}
        first = list(self.prepared.keys())[0]
        self.ts_list = [pd.Timestamp(x) for x in self.prepared[first]["timestamp"].tolist()]
        self._signal_cache = {}
        print(f"Pullback cached symbols={len(self.prepared)} bars={len(self.ts_list)}")

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        close, high, low = out["close"], out["high"], out["low"]
        out["ema20"] = close.ewm(span=20, adjust=False).mean()
        out["ema50"] = close.ewm(span=50, adjust=False).mean()
        out["rsi"] = self._rsi(close, 14)
        out["atr"] = self._atr(high, low, close)
        out["atr_ma20"] = out["atr"].rolling(20).mean()
        out["low3"] = low.rolling(3).min()
        out["high3"] = high.rolling(3).max()
        out["prior_high20"] = high.rolling(20).max().shift(1)
        out["prior_low20"] = low.rolling(20).min().shift(1)
        return out

    def row_at(self, symbol: str, ts: pd.Timestamp):
        idx = self.idx_map.get(symbol, {}).get(ts)
        if idx is None:
            return None
        return self.prepared[symbol].iloc[idx]

    def _signals(self, params: dict):
        key = tuple(sorted(params.items()))
        if key in self._signal_cache:
            return self._signal_cache[key]

        ema_col = f"ema{params['ema_period']}"
        signals = defaultdict(list)
        for sym in self.symbols:
            df = self.prepared[sym]
            if ema_col not in df.columns:
                df = df.copy()
                df[ema_col] = df["close"].ewm(span=params["ema_period"], adjust=False).mean()
                self.prepared[sym] = df

            healthy_rsi = df["rsi"].between(params["rsi_low"], params["rsi_high"])
            atr_expansion = df["atr"] > df["atr_ma20"] * 1.15
            long_mask = (
                (df["btc_ema20"] > df["btc_ema50"])
                & (df["close"] > df["ema50"])
                & (df["low"] <= df[ema_col])
                & (df["close"] > df[ema_col])
                & healthy_rsi
                & (~atr_expansion.fillna(False))
            )
            short_mask = (
                (df["btc_ema20"] < df["btc_ema50"])
                & (df["close"] < df["ema50"])
                & (df["high"] >= df[ema_col])
                & (df["close"] < df[ema_col])
                & healthy_rsi
                & (~atr_expansion.fillna(False))
            )

            for _, row in df[long_mask].iterrows():
                stop = row["low3"] - params["sl_atr_mult"] * row["atr"]
                target = row["prior_high20"]
                if pd.isna(stop) or pd.isna(target) or target <= row["close"]:
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
                stop = row["high3"] + params["sl_atr_mult"] * row["atr"]
                target = row["prior_low20"]
                if pd.isna(stop) or pd.isna(target) or target >= row["close"]:
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

    def simulate(self, start_date, end_date, ema_period=20, rsi_low=40, rsi_high=60, sl_atr_mult=0.5, time_stop_bars=20):
        params = {
            "ema_period": ema_period,
            "rsi_low": rsi_low,
            "rsi_high": rsi_high,
            "sl_atr_mult": sl_atr_mult,
            "time_stop_bars": time_stop_bars,
        }
        log, series = simulate_sequential(self, self._signals(params), start_date, end_date, params)
        return log, series, {}

    def check_exit(self, pos: dict, row: pd.Series, params: dict):
        if pos["side"] == "buy":
            if row["high"] >= pos["take_profit"]:
                return "TAKE_PROFIT", pos["take_profit"]
            if row["low"] <= pos["stop_loss"]:
                return "HARD_SL", pos["stop_loss"]
        else:
            if row["low"] <= pos["take_profit"]:
                return "TAKE_PROFIT", pos["take_profit"]
            if row["high"] >= pos["stop_loss"]:
                return "HARD_SL", pos["stop_loss"]
        if pos["bars"] >= params["time_stop_bars"]:
            return "TIME_STOP", row["close"]
        return None, None

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(high, low, close):
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(14).mean()


def main():
    sim = PullbackBacktester()
    default = {"ema_period": 20, "rsi_low": 40, "rsi_high": 60, "sl_atr_mult": 0.5, "time_stop_bars": 20}
    grid = [
        {"ema_period": 20, "rsi_low": rsi_low, "rsi_high": 60, "sl_atr_mult": sl_atr, "time_stop_bars": 20}
        for rsi_low, sl_atr in product([35, 40, 45], [0.5, 1.0])
    ]
    run_validation(
        sim,
        "Pullback Strategy",
        default,
        grid,
        bonferroni_tests=6,
        report_path="backtest/pullback_validation.txt",
        chart_path="backtest/pullback_mc.png",
    )


if __name__ == "__main__":
    main()
