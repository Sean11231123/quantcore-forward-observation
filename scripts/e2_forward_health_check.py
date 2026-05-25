from __future__ import annotations

import argparse
import csv
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "forward" / "crypto_derivatives" / "bybit_hourly.csv"
REPORT_FILE = ROOT / "data" / "forward" / "crypto_derivatives" / "e2_forward_health_report.txt"

EXPECTED_FIELDS = [
    "fetch_timestamp_utc",
    "data_timestamp_utc",
    "symbol",
    "last_price",
    "mark_price",
    "index_price",
    "open_interest",
    "funding_rate",
]

EXPECTED_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "SUIUSDT",
    "POLUSDT",
    "NEARUSDT",
    "DOTUSDT",
    "TRXUSDT",
]

NUMERIC_FIELDS = [
    "last_price",
    "mark_price",
    "index_price",
    "open_interest",
    "funding_rate",
]


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def hour_floor(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def git_value(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def expected_hours(start: datetime, end: datetime) -> list[datetime]:
    hours: list[datetime] = []
    current = hour_floor(start)
    final = hour_floor(end)
    while current <= final:
        hours.append(current)
        current += timedelta(hours=1)
    return hours


def analyze(data_file: Path = DATA_FILE, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    expected_symbol_set = set(EXPECTED_SYMBOLS)
    result: dict[str, object] = {
        "generated_at_utc": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_file": str(data_file.relative_to(ROOT) if data_file.is_relative_to(ROOT) else data_file),
        "expected_symbol_count": len(EXPECTED_SYMBOLS),
        "total_rows": 0,
        "first_data_timestamp_utc": "",
        "latest_data_timestamp_utc": "",
        "latest_fetch_timestamp_utc": "",
        "latest_data_lag_hours": None,
        "complete_hours_last_24h": 0,
        "missing_hours_last_24h": 0,
        "incomplete_hours_last_24h": 0,
        "duplicate_rows_last_24h": 0,
        "malformed_rows": 0,
        "unexpected_symbols": 0,
        "unexpected_symbol_values": [],
        "missing_hour_values_last_24h": [],
        "incomplete_hour_values_last_24h": [],
        "duplicate_row_keys_last_24h": [],
        "current_git_commit": git_value(["rev-parse", "--short", "HEAD"]),
        "data_file_git_commit": "",
        "data_file_git_commit_time_utc": "",
        "push_lag_hours": None,
        "schema_valid": False,
        "classification": "E2_FORWARD_BLOCKED_DATA_FILE_MISSING",
    }

    if not data_file.exists():
        return result

    rows: list[dict[str, str]] = []
    with data_file.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        result["schema_valid"] = reader.fieldnames == EXPECTED_FIELDS
        if not result["schema_valid"]:
            result["classification"] = "E2_FORWARD_BLOCKED_SCHEMA_INVALID"
            return result
        rows = list(reader)

    result["total_rows"] = len(rows)
    by_hour: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    seen_keys: dict[tuple[datetime, str], int] = defaultdict(int)
    data_timestamps: list[datetime] = []
    fetch_timestamps: list[datetime] = []
    duplicate_keys: list[str] = []
    malformed_rows = 0
    unexpected_symbols: set[str] = set()

    for row in rows:
        data_ts = parse_timestamp(row.get("data_timestamp_utc", ""))
        fetch_ts = parse_timestamp(row.get("fetch_timestamp_utc", ""))
        symbol = row.get("symbol", "")
        malformed = data_ts is None or fetch_ts is None or not symbol
        for field in NUMERIC_FIELDS:
            try:
                float(row.get(field, ""))
            except (TypeError, ValueError):
                malformed = True
        if malformed:
            malformed_rows += 1
            continue
        assert data_ts is not None
        assert fetch_ts is not None
        data_hour = hour_floor(data_ts)
        by_hour[data_hour].append(row)
        data_timestamps.append(data_hour)
        fetch_timestamps.append(fetch_ts)
        if symbol not in expected_symbol_set:
            unexpected_symbols.add(symbol)
        key = (data_hour, symbol)
        seen_keys[key] += 1
        if seen_keys[key] == 2:
            duplicate_keys.append(f"{data_hour.isoformat().replace('+00:00', 'Z')}:{symbol}")

    result["malformed_rows"] = malformed_rows
    result["unexpected_symbols"] = len(unexpected_symbols)
    result["unexpected_symbol_values"] = sorted(unexpected_symbols)

    if data_timestamps:
        first_data = min(data_timestamps)
        latest_data = max(data_timestamps)
        latest_fetch = max(fetch_timestamps)
        result["first_data_timestamp_utc"] = first_data.isoformat().replace("+00:00", "Z")
        result["latest_data_timestamp_utc"] = latest_data.isoformat().replace("+00:00", "Z")
        result["latest_fetch_timestamp_utc"] = latest_fetch.isoformat().replace("+00:00", "Z")
        result["latest_data_lag_hours"] = round((now - latest_data).total_seconds() / 3600, 3)

        cutoff = hour_floor(now - timedelta(hours=23))
        last_24_hours = expected_hours(cutoff, hour_floor(now))
        missing_hours: list[str] = []
        incomplete_hours: list[str] = []
        duplicate_keys_last_24h: list[str] = []
        complete_hours = 0

        for hour in last_24_hours:
            rows_for_hour = by_hour.get(hour, [])
            symbols_for_hour = [r.get("symbol", "") for r in rows_for_hour]
            expected_rows_for_hour = [s for s in symbols_for_hour if s in expected_symbol_set]
            unique_expected_symbols = set(expected_rows_for_hour)
            if not rows_for_hour:
                missing_hours.append(hour.isoformat().replace("+00:00", "Z"))
            elif len(unique_expected_symbols) == len(EXPECTED_SYMBOLS):
                complete_hours += 1
            else:
                incomplete_hours.append(hour.isoformat().replace("+00:00", "Z"))
            for symbol in expected_symbol_set:
                if seen_keys.get((hour, symbol), 0) > 1:
                    duplicate_keys_last_24h.append(f"{hour.isoformat().replace('+00:00', 'Z')}:{symbol}")

        result["complete_hours_last_24h"] = complete_hours
        result["missing_hours_last_24h"] = len(missing_hours)
        result["incomplete_hours_last_24h"] = len(incomplete_hours)
        result["duplicate_rows_last_24h"] = len(duplicate_keys_last_24h)
        result["missing_hour_values_last_24h"] = missing_hours
        result["incomplete_hour_values_last_24h"] = incomplete_hours
        result["duplicate_row_keys_last_24h"] = duplicate_keys_last_24h

    rel_data_file = str(DATA_FILE.relative_to(ROOT)).replace("\\", "/")
    result["data_file_git_commit"] = git_value(["log", "-1", "--format=%h", "--", rel_data_file])
    commit_time = git_value(["log", "-1", "--format=%cI", "--", rel_data_file])
    result["data_file_git_commit_time_utc"] = commit_time
    commit_ts = parse_timestamp(commit_time)
    if commit_ts:
        result["push_lag_hours"] = round((now - commit_ts).total_seconds() / 3600, 3)

    result["classification"] = classify(result)
    return result


def classify(result: dict[str, object]) -> str:
    if not result.get("schema_valid"):
        return "E2_FORWARD_BLOCKED_SCHEMA_INVALID"
    if result.get("total_rows") == 0:
        return "E2_FORWARD_BLOCKED_NO_RECENT_DATA"
    lag = result.get("latest_data_lag_hours")
    if isinstance(lag, (int, float)) and lag > 3:
        return "E2_FORWARD_BLOCKED_NO_RECENT_DATA"
    push_lag = result.get("push_lag_hours")
    if isinstance(push_lag, (int, float)) and push_lag > 6:
        return "E2_FORWARD_WARNING_PUSH_LAG"
    if int(result.get("missing_hours_last_24h", 0)) > 0:
        return "E2_FORWARD_WARNING_MISSING_HOURS"
    if int(result.get("incomplete_hours_last_24h", 0)) > 0:
        return "E2_FORWARD_WARNING_INCOMPLETE_HOURS"
    if int(result.get("malformed_rows", 0)) > 0:
        return "E2_FORWARD_WARNING_INCOMPLETE_HOURS"
    return "E2_FORWARD_HEALTHY"


def render_health_report(result: dict[str, object]) -> str:
    lines = [
        "E2 Forward Health Report",
        f"generated_at_utc: {result['generated_at_utc']}",
        f"data_file: {result['data_file']}",
        f"expected_symbol_count: {result['expected_symbol_count']}",
        f"total_rows: {result['total_rows']}",
        f"first_data_timestamp_utc: {result['first_data_timestamp_utc']}",
        f"latest_data_timestamp_utc: {result['latest_data_timestamp_utc']}",
        f"latest_fetch_timestamp_utc: {result['latest_fetch_timestamp_utc']}",
        f"latest_data_lag_hours: {result['latest_data_lag_hours']}",
        f"complete_hours_last_24h: {result['complete_hours_last_24h']}",
        f"missing_hours_last_24h: {result['missing_hours_last_24h']}",
        f"incomplete_hours_last_24h: {result['incomplete_hours_last_24h']}",
        f"duplicate_rows_last_24h: {result['duplicate_rows_last_24h']}",
        f"malformed_rows: {result['malformed_rows']}",
        f"unexpected_symbols: {result['unexpected_symbols']}",
        f"unexpected_symbol_values: {','.join(result['unexpected_symbol_values'])}",
        f"current_git_commit: {result['current_git_commit']}",
        f"data_file_git_commit: {result['data_file_git_commit']}",
        f"data_file_git_commit_time_utc: {result['data_file_git_commit_time_utc']}",
        f"push_lag_hours: {result['push_lag_hours']}",
        f"classification: {result['classification']}",
        "",
        "Policy",
        "missing_hours: preserve_as_missing_do_not_backfill",
        "historical_rows: untouched",
        "schema: preserved",
        "pixel4_status: fallback_only",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate E2 forward health report for bybit_hourly.csv.")
    parser.add_argument("--data-file", type=Path, default=DATA_FILE)
    parser.add_argument("--report-file", type=Path, default=REPORT_FILE)
    args = parser.parse_args()

    result = analyze(args.data_file)
    report = render_health_report(result)
    args.report_file.parent.mkdir(parents=True, exist_ok=True)
    args.report_file.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
