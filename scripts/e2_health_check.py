from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "forward" / "crypto_derivatives"
REPORT = ROOT / "data" / "forward" / "health" / "e2_crypto_derivatives_health_report.txt"

DATA_TYPES = {
    "funding": BASE / "funding",
    "open_interest": BASE / "open_interest",
    "mark_index_premium": BASE / "mark_index_premium",
}
HEALTH_DIR = BASE / "health"

SYMBOLS = [
    "ADA_USDT", "APT_USDT", "ARB_USDT", "AVAX_USDT", "BCH_USDT",
    "BNB_USDT", "DOGE_USDT", "DOT_USDT", "ETH_USDT", "FTM_USDT",
    "LINK_USDT", "LTC_USDT", "NEAR_USDT", "OP_USDT", "POL_USDT",
    "SOL_USDT", "SUI_USDT", "TRX_USDT", "XRP_USDT",
]
KNOWN_MISSING_SYMBOLS = {"FTM_USDT"}
PRODUCTION_SYMBOLS = [s for s in SYMBOLS if s not in KNOWN_MISSING_SYMBOLS]
EXPECTED_RUN_INTERVAL_HOURS = 1


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def read_rows(folder: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.csv")):
        with path.open("r", newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def longest_gap_hours(timestamps: list[datetime]) -> float | None:
    if len(timestamps) < 2:
        return None
    ordered = sorted(timestamps)
    return max((b - a).total_seconds() / 3600 for a, b in zip(ordered, ordered[1:]))


def health_summary(hours: int = 24) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    expected_runs = max(1, hours // EXPECTED_RUN_INTERVAL_HOURS)
    expected_per_type = len(PRODUCTION_SYMBOLS) * expected_runs
    lines = [
        "E2 Daily Health Report",
        f"generated_utc: {now.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}",
        f"lookback_hours: {hours}",
        "",
    ]
    total_errors = 0
    total_known_binance_region_block = 0
    duplicate_count = 0

    health_rows = read_rows(HEALTH_DIR)
    recent_health = [r for r in health_rows if (parse_ts(r.get("health_timestamp_utc", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    for row in recent_health:
        try:
            duplicate_count += int(float(row.get("duplicate_rows_prevented", "0") or 0))
        except Exception:
            pass

    for data_type, folder in DATA_TYPES.items():
        rows = read_rows(folder)
        recent = [r for r in rows if (parse_ts(r.get("fetch_timestamp_utc", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        success = [r for r in recent if str(r.get("request_success", "")).lower() == "true"]
        errors = [r for r in recent if str(r.get("request_success", "")).lower() != "true"]
        bybit_success = [r for r in success if r.get("exchange") == "bybit"]
        bybit_errors = [r for r in errors if r.get("exchange") == "bybit"]
        binance_success = [r for r in success if r.get("exchange") == "binance"]
        binance_errors = [r for r in errors if r.get("exchange") == "binance"]
        known_binance_region_block = [
            r for r in binance_errors
            if "known_binance_region_block" in str(r.get("error_message", ""))
            or "HTTP Error 451" in str(r.get("error_message", ""))
        ]
        unknown_errors = [r for r in errors if r not in known_binance_region_block]
        total_errors += len(unknown_errors)
        total_known_binance_region_block += len(known_binance_region_block)
        by_symbol: dict[str, int] = defaultdict(int)
        latest_by_symbol: dict[str, datetime] = {}
        ts_by_symbol: dict[str, list[datetime]] = defaultdict(list)
        for row in bybit_success:
            symbol = row.get("symbol", "")
            by_symbol[symbol] += 1
            ts = parse_ts(row.get("fetch_timestamp_utc", ""))
            if ts:
                latest_by_symbol[symbol] = max(latest_by_symbol.get(symbol, datetime.min.replace(tzinfo=timezone.utc)), ts)
                ts_by_symbol[symbol].append(ts)
        missing_symbols = [s for s in PRODUCTION_SYMBOLS if by_symbol.get(s, 0) == 0]
        coverage = len(bybit_success) / expected_per_type if expected_per_type else 0.0
        longest_gap = max((longest_gap_hours(v) or 0.0) for v in ts_by_symbol.values()) if ts_by_symbol else None
        latest_ts = max(latest_by_symbol.values()).isoformat().replace("+00:00", "Z") if latest_by_symbol else ""
        lines.extend([
            f"data_type: {data_type}",
            f"  rows_collected_last_{hours}h: {len(bybit_success)}",
            f"  expected_rows_last_{hours}h: {expected_per_type}",
            f"  coverage_pct: {coverage:.4f}",
            f"  production_exchange: bybit",
            f"  known_missing_symbols: {','.join(sorted(KNOWN_MISSING_SYMBOLS))}",
            f"  bybit_success_rows: {len(bybit_success)}",
            f"  bybit_error_rows: {len(bybit_errors)}",
            f"  binance_success_rows: {len(binance_success)}",
            f"  binance_error_rows: {len(binance_errors)}",
            f"  known_binance_region_block_count: {len(known_binance_region_block)}",
            f"  missing_symbols: {','.join(missing_symbols)}",
            f"  error_rows_ex_known_binance_region_block: {len(unknown_errors)}",
            f"  longest_missing_gap_hours_if_feasible: {longest_gap}",
            f"  last_successful_timestamp: {latest_ts}",
            "",
        ])

    lines.extend([
        f"recent_health_runs: {len(recent_health)}",
        f"duplicate_rows_prevented: {duplicate_count}",
        f"known_binance_region_block_count: {total_known_binance_region_block}",
        f"api_error_count_ex_known_binance_region_block: {total_errors}",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 derivatives forward logger health check.")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    text = health_summary(args.hours)
    REPORT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
