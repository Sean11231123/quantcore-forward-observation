from __future__ import annotations

import glob
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v12_strategy import compute_v12_15m


INTERVALS = ["15m", "1h", "4h", "1d"]
RAW_ROOT = "data/binance_futures"
OUT_ROOT = "data/features"
REPORT_PATH = "data/features/feature_report.json"

INTERVAL_FREQ = {
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

WARMUP_AFTER_GAP = {
    "15m": 200,
    "1h": 200,
    "4h": 100,
    "1d": 50,
}

FEATURES_CREATED = [
    "atr",
    "atr_ma10",
    "adx",
    "ema20",
    "ema50",
    "range_efficiency",
    "volume_ma20",
    "volume_ratio",
    "bb_width",
    "previous_20_high",
    "previous_20_low",
    "candle_close_time",
    "gap_before_current_bar",
    "segment_id",
    "warmup_excluded",
]


def attach_segments(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    out = df.sort_values("timestamp").reset_index(drop=True).copy()
    expected_delta = pd.Timedelta(INTERVAL_FREQ[interval])
    diffs = out["timestamp"].diff()
    out["gap_before_current_bar"] = diffs.gt(expected_delta)
    out.loc[0, "gap_before_current_bar"] = False
    out["segment_id"] = out["gap_before_current_bar"].cumsum().astype(int)
    return out


def add_gap_aware_features(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    segmented = attach_segments(df, interval)
    pieces = []
    for segment_id, part in segmented.groupby("segment_id", sort=True):
        computed = compute_v12_15m(part.copy())
        computed["segment_id"] = int(segment_id)
        computed["gap_before_current_bar"] = part["gap_before_current_bar"].values
        computed["raw_open_timestamp"] = computed["timestamp"]
        if "close_time" in part.columns:
            computed["candle_close_time"] = pd.to_datetime(part["close_time"]).values
        elif "candle_close_time" in part.columns:
            computed["candle_close_time"] = pd.to_datetime(part["candle_close_time"]).values
        else:
            computed["candle_close_time"] = computed["timestamp"] + pd.Timedelta(INTERVAL_FREQ[interval])

        computed["atr_ma10"] = computed["atr"].rolling(10, min_periods=10).mean()
        computed["volume_ma20"] = computed["volume"].rolling(20, min_periods=20).mean()
        computed["volume_ratio"] = computed["volume"] / computed["volume_ma20"].replace(0, pd.NA)
        computed["previous_20_high"] = computed["high"].rolling(20, min_periods=20).max().shift(1)
        computed["previous_20_low"] = computed["low"].rolling(20, min_periods=20).min().shift(1)
        mid = computed["close"].rolling(20, min_periods=20).mean()
        std = computed["close"].rolling(20, min_periods=20).std()
        computed["bb_width"] = ((mid + 2 * std) - (mid - 2 * std)) / mid.replace(0, pd.NA)
        computed["bars_since_segment_start"] = range(len(computed))
        warmup = WARMUP_AFTER_GAP[interval]
        computed["warmup_excluded"] = (int(segment_id) > 0) & (computed["bars_since_segment_start"] < warmup)
        pieces.append(computed)
    return pd.concat(pieces, ignore_index=True).sort_values("timestamp").reset_index(drop=True)


def validate_gap_features(out: pd.DataFrame, interval: str) -> dict:
    expected_delta = pd.Timedelta(INTERVAL_FREQ[interval])
    diffs = out["timestamp"].diff()
    gap_count = int(diffs.gt(expected_delta).sum())
    warmup_expected = 0
    warmup = WARMUP_AFTER_GAP[interval]
    for segment_id, part in out.groupby("segment_id"):
        if int(segment_id) == 0:
            continue
        warmup_expected += min(warmup, len(part))
    return {
        "rows": int(len(out)),
        "first_timestamp": str(out["timestamp"].min()) if len(out) else None,
        "last_timestamp": str(out["timestamp"].max()) if len(out) else None,
        "duplicate_timestamp_count": int(out["timestamp"].duplicated().sum()),
        "gap_count": gap_count,
        "warmup_excluded_count": int(out["warmup_excluded"].sum()),
        "warmup_expected_count": int(warmup_expected),
        "warmup_exclusion_complete": bool(int(out["warmup_excluded"].sum()) == int(warmup_expected)),
    }


def main():
    report = {
        "intervals": INTERVALS,
        "features_created": FEATURES_CREATED,
        "lookahead_safe_breakout_levels": True,
        "rolling_uses_future_data": False,
        "no_fake_fill": True,
        "no_interpolation": True,
        "segment_id_created": True,
        "gap_flag_created": True,
        "rolling_cross_gap_prevented": True,
        "warmup_exclusion_after_gap": WARMUP_AFTER_GAP,
        "issues": [],
        "files_written": 0,
        "gap_flags_present": True,
        "warmup_exclusion_present": True,
        "quality": {},
    }
    for interval in INTERVALS:
        report["quality"][interval] = {}
        in_dir = os.path.join(RAW_ROOT, interval)
        out_dir = os.path.join(OUT_ROOT, interval)
        os.makedirs(out_dir, exist_ok=True)
        for path in glob.glob(os.path.join(in_dir, "*.csv")):
            symbol = os.path.basename(path).replace(".csv", "")
            try:
                df = pd.read_csv(path)
                df.columns = [c.lower() for c in df.columns]
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                if "close_time" in df.columns:
                    df["close_time"] = pd.to_datetime(df["close_time"])
                if "candle_close_time" in df.columns:
                    df["candle_close_time"] = pd.to_datetime(df["candle_close_time"])
                out = add_gap_aware_features(df, interval)
                out_path = os.path.join(out_dir, f"{symbol}_features.csv")
                out.to_csv(out_path, index=False)
                report["files_written"] += 1
                report["quality"][interval][symbol] = validate_gap_features(out, interval)
                print(f"{interval} {symbol} features rows={len(out)}")
            except Exception as exc:
                issue = f"{interval} {symbol}: {exc}"
                report["issues"].append(issue)
                print(f"ISSUE {issue}")
    os.makedirs(OUT_ROOT, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
