from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from config import COMMISSION, INITIAL_BALANCE
from v12_strategy import RISK_PCT, SL_ATR_MULT, shift_candle_open_to_close


FEATURE_ROOT = "data/features"
START_FULL = "2021-01-01"
END_FULL = "2026-04-21"
START_OOS = "2024-01-01"
TOP_N = 3


@dataclass
class TfConfig:
    name: str
    entry_tf: str
    confirm_tf: str
    regime_tf: str
    sl_atr_mult: float = SL_ATR_MULT


CONFIGS = [
    TfConfig("T0_15m", "15m", "1h", "1h", SL_ATR_MULT),
    TfConfig("T1_1h", "1h", "4h", "4h", 1.5),
    TfConfig("T2_4h", "4h", "1d", "1d", 1.5),
]


def feature_path(interval: str, symbol: str) -> str:
    return os.path.join(FEATURE_ROOT, interval, f"{symbol}_features.csv")


def load_features(interval: str) -> dict[str, pd.DataFrame]:
    out = {}
    root = os.path.join(FEATURE_ROOT, interval)
    if not os.path.isdir(root):
        return out
    for name in os.listdir(root):
        if not name.endswith("_features.csv"):
            continue
        symbol = name.replace("_features.csv", "")
        df = pd.read_csv(os.path.join(root, name))
        df.columns = [c.lower() for c in df.columns]
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if "candle_close_time" in df.columns:
            df["candle_close_time"] = pd.to_datetime(df["candle_close_time"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        out[symbol] = df
    return out


def merge_confirm(entry: pd.DataFrame, confirm: pd.DataFrame, confirm_tf: str) -> pd.DataFrame:
    conf = confirm.copy()
    if "candle_close_time" not in conf.columns:
        conf = shift_candle_open_to_close(conf, confirm_tf)
        conf["candle_close_time"] = conf["timestamp"]
    conf = conf[["candle_close_time", "adx", "warmup_excluded"]].rename(
        columns={"adx": "adx_confirm", "warmup_excluded": "confirm_warmup_excluded"}
    )
    return pd.merge_asof(
        entry.sort_values("timestamp"),
        conf.sort_values("candle_close_time"),
        left_on="timestamp",
        right_on="candle_close_time",
        direction="backward",
    )


def merge_btc_regime(entry: pd.DataFrame, btc_entry: pd.DataFrame, btc_regime: pd.DataFrame, regime_tf: str) -> pd.DataFrame:
    btc_e = btc_entry[["timestamp", "adx", "ema20", "ema50", "ema200", "range_efficiency", "close"]].rename(
        columns={
            "adx": "btc_adx",
            "ema20": "btc_ema20",
            "ema50": "btc_ema50",
            "ema200": "btc_ema200",
            "range_efficiency": "btc_re",
            "close": "btc_close",
        }
    )
    df = pd.merge_asof(
        entry.sort_values("timestamp"),
        btc_e.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    btc_r = btc_regime.copy()
    if "candle_close_time" not in btc_r.columns:
        btc_r = shift_candle_open_to_close(btc_r, regime_tf)
        btc_r["candle_close_time"] = btc_r["timestamp"]
    btc_r = btc_r[["candle_close_time", "adx", "warmup_excluded"]].rename(
        columns={"adx": "btc_adx_regime", "warmup_excluded": "btc_regime_warmup_excluded"}
    )
    return pd.merge_asof(
        df.sort_values("timestamp"),
        btc_r.sort_values("candle_close_time"),
        left_on="timestamp",
        right_on="candle_close_time",
        direction="backward",
    )


def build_whitelist(symbol_frames: dict[str, pd.DataFrame]) -> tuple[dict[pd.Timestamp, list[str]], dict[pd.Timestamp, pd.Timestamp]]:
    rows = []
    for symbol, df in symbol_frames.items():
        data = df.copy()
        data["date"] = data["timestamp"].dt.normalize()
        quote = data["quote_volume"] if "quote_volume" in data.columns else data["close"] * data["volume"]
        daily = pd.DataFrame({"date": data["date"], "dollar_volume": quote}).groupby("date", as_index=False).sum()
        daily["symbol"] = symbol
        rows.append(daily)
    ranked = pd.concat(rows, ignore_index=True)
    by_date = {pd.Timestamp(date): group for date, group in ranked.groupby("date")}
    whitelist = {}
    sources = {}
    for trade_date in sorted(by_date):
        source_date = trade_date - pd.Timedelta(days=1)
        sources[trade_date] = source_date
        group = by_date.get(source_date)
        if group is None:
            whitelist[trade_date] = []
        else:
            whitelist[trade_date] = group.sort_values("dollar_volume", ascending=False)["symbol"].head(TOP_N).tolist()
    return whitelist, sources


def prepare(config: TfConfig):
    entry = load_features(config.entry_tf)
    confirm = load_features(config.confirm_tf)
    btc_entry = entry.get("BTCUSDT")
    btc_regime = load_features(config.regime_tf).get("BTCUSDT")
    symbols = [s for s in entry if s != "BTCUSDT" and s in confirm]
    prepared = {}
    for symbol in symbols:
        df = entry[symbol].copy()
        df = merge_confirm(df, confirm[symbol], config.confirm_tf)
        if btc_entry is not None and btc_regime is not None:
            df = merge_btc_regime(df, btc_entry, btc_regime, config.regime_tf)
        prepared[symbol] = df.reset_index(drop=True)
    whitelist, sources = build_whitelist({s: entry[s] for s in symbols})
    idx_map = {
        s: {pd.Timestamp(row.timestamp): i for i, row in df[["timestamp"]].reset_index(drop=True).iterrows()}
        for s, df in prepared.items()
    }
    ts_list = []
    if prepared:
        first = list(prepared.keys())[0]
        ts_list = [pd.Timestamp(x) for x in prepared[first]["timestamp"].tolist()]
    return prepared, idx_map, ts_list, whitelist, sources


def passes_entry(row) -> bool:
    if bool(row.get("warmup_excluded", False)):
        return False
    if bool(row.get("confirm_warmup_excluded", False)) or bool(row.get("btc_regime_warmup_excluded", False)):
        return False
    required = [
        row.get("close"),
        row.get("ema20"),
        row.get("ema50"),
        row.get("previous_20_high"),
        row.get("atr"),
        row.get("adx_confirm"),
        row.get("btc_adx_regime"),
        row.get("btc_re"),
    ]
    if any(pd.isna(v) for v in required) or row.get("atr", 0) <= 0:
        return False
    if float(row.get("adx", 0) or 0) < 30.0 or float(row.get("adx_confirm", 0) or 0) < 22.0:
        return False
    btc_adx = float(row.get("btc_adx_regime", 0) or 0)
    btc_re = float(row.get("btc_re", 0) or 0)
    if btc_adx < 30.0 or not (0.20 <= btc_re <= 0.40):
        return False
    return bool(row["close"] > row["ema20"] > row["ema50"] and row["close"] > row["previous_20_high"])


def simulate(config: TfConfig, start_date: str, end_date: str):
    prepared, idx_map, ts_list, whitelist, _ = prepare(config)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    balance = float(INITIAL_BALANCE)
    series = []
    log = []
    pos = None

    for ts in ts_list:
        if ts < start_ts or ts > end_ts:
            continue
        series.append(balance)
        if pos is not None:
            df = prepared[pos["symbol"]]
            idx = idx_map[pos["symbol"]].get(ts)
            if idx is not None:
                row = df.iloc[idx]
                pos["bars"] += 1
                hi, lo, cl = row["high"], row["low"], row["close"]
                pos["mfe_atr"] = max(pos["mfe_atr"], (hi - pos["entry_price"]) / pos["entry_atr"])
                pos["mae_atr"] = min(pos["mae_atr"], (lo - pos["entry_price"]) / pos["entry_atr"])
                sl = pos["entry_price"] - config.sl_atr_mult * pos["entry_atr"]
                tp = pos["entry_price"] + 1.5 * pos["entry_atr"]
                exit_type = None
                exit_px = None
                if hi >= tp:
                    exit_type, exit_px = "TAKE_PROFIT", tp
                elif lo <= sl:
                    exit_type, exit_px = "HARD_SL", sl
                elif cl < sl:
                    exit_type, exit_px = "STRUCT_BREAK", cl
                if exit_type:
                    pnl = pos["notional"] * (exit_px - pos["entry_price"]) / pos["entry_price"]
                    balance += pnl
                    balance *= 1.0 - COMMISSION
                    net_pnl = balance - pos["balance_before_entry"]
                    log.append(
                        {
                            "symbol": pos["symbol"],
                            "entry_time": pos["entry_time"],
                            "exit_time": ts,
                            "entry_idx": pos["entry_idx"],
                            "entry_price": pos["entry_price"],
                            "exit": exit_type,
                            "pnl": pnl,
                            "pnl_portfolio_pct": net_pnl / pos["balance_before_entry"] * 100,
                            "balance": balance,
                            "mfe_atr": pos["mfe_atr"],
                            "mae_atr": pos["mae_atr"],
                            "bars": pos["bars"],
                        }
                    )
                    series.append(balance)
                    pos = None
                    continue

        if pos is not None:
            continue
        wl = whitelist.get(ts.normalize(), [])
        for symbol in wl:
            if symbol not in prepared:
                continue
            idx = idx_map[symbol].get(ts)
            if idx is None:
                continue
            row = prepared[symbol].iloc[idx]
            if not passes_entry(row):
                continue
            entry_balance = balance
            atr = row["atr"]
            risk = balance * RISK_PCT
            notional = risk * row["close"] / (config.sl_atr_mult * atr)
            balance *= 1.0 - COMMISSION
            pos = {
                "symbol": symbol,
                "entry_time": ts,
                "entry_idx": idx,
                "entry_price": row["close"],
                "entry_atr": atr,
                "notional": notional,
                "balance_before_entry": entry_balance,
                "bars": 0,
                "mfe_atr": 0.0,
                "mae_atr": 0.0,
            }
            break
    return log, series, prepared


def max_drawdown(series):
    if not series:
        return 0.0
    s = pd.Series(series, dtype="float64")
    peak = s.cummax()
    return float(((peak - s) / peak).max() * 100)


def stats(log, series):
    if not log:
        return {"trades": 0, "win_pct": 0.0, "expectancy_pct": 0.0, "max_dd_pct": max_drawdown(series), "final": series[-1] if series else INITIAL_BALANCE}
    df = pd.DataFrame(log)
    return {
        "trades": int(len(df)),
        "win_pct": float((df["pnl"] > 0).mean() * 100),
        "expectancy_pct": float(df["pnl_portfolio_pct"].mean()),
        "max_dd_pct": max_drawdown(series),
        "final": float(series[-1]) if series else float(df.iloc[-1]["balance"]),
    }


def false_breakout(log, prepared):
    if not log:
        return {
            "losing_trades_avg_mfe_atr": 0.0,
            "losing_trades_avg_mae_atr": 0.0,
            "pct_positive_after_1_bar": 0.0,
            "pct_positive_after_2_bars": 0.0,
            "pct_positive_after_3_bars": 0.0,
        }
    df = pd.DataFrame(log)
    losing = df[df["pnl_portfolio_pct"] <= 0]
    out = {
        "losing_trades_avg_mfe_atr": float(losing["mfe_atr"].mean()) if len(losing) else 0.0,
        "losing_trades_avg_mae_atr": float(losing["mae_atr"].mean()) if len(losing) else 0.0,
    }
    for n in [1, 2, 3]:
        vals = []
        for t in log:
            entry_idx = int(t["entry_idx"])
            frame = prepared[t["symbol"]]
            if entry_idx + n >= len(frame):
                continue
            future_close = float(frame.iloc[entry_idx + n]["close"])
            vals.append((future_close - float(t["entry_price"])) / float(t["entry_price"]))
        out[f"pct_positive_after_{n}_bar"] = float((np.array(vals) > 0).mean() * 100) if vals else 0.0
    return out


def run():
    results = {}
    for config in CONFIGS:
        full_log, full_series, prepared = simulate(config, START_FULL, END_FULL)
        oos_log, oos_series, _ = simulate(config, START_OOS, END_FULL)
        full = stats(full_log, full_series)
        oos = stats(oos_log, oos_series)
        sample_status = "sufficient"
        if full["trades"] < 30 or oos["trades"] < 15:
            sample_status = "insufficient"
        results[config.name] = {
            "entry_tf": config.entry_tf,
            "confirm_tf": config.confirm_tf,
            "full": full,
            "oos": oos,
            "sample_status": sample_status,
            "false_breakout": false_breakout(oos_log, prepared),
            "limitations": [],
        }
    return results


def main():
    results = run()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
