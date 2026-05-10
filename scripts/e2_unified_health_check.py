from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "data" / "forward"
CRYPTO = FORWARD / "crypto_derivatives"
FUTURES = FORWARD / "traditional_futures" / "daily" / "traditional_futures_daily.csv"
HEALTH = FORWARD / "health"
REPORT = HEALTH / "e2_unified_daily_health_report.txt"

CRYPTO_TYPES = {
    "funding": CRYPTO / "funding",
    "open_interest": CRYPTO / "open_interest",
    "mark_index_premium": CRYPTO / "mark_index_premium",
}
CRYPTO_SYMBOLS = [
    "ADA_USDT", "APT_USDT", "ARB_USDT", "AVAX_USDT", "BCH_USDT",
    "BNB_USDT", "DOGE_USDT", "DOT_USDT", "ETH_USDT", "FTM_USDT",
    "LINK_USDT", "LTC_USDT", "NEAR_USDT", "OP_USDT", "POL_USDT",
    "SOL_USDT", "SUI_USDT", "TRX_USDT", "XRP_USDT",
]
KNOWN_MISSING_SYMBOLS = {"FTM_USDT"}
PRODUCTION_CRYPTO_SYMBOLS = [s for s in CRYPTO_SYMBOLS if s not in KNOWN_MISSING_SYMBOLS]
EXPECTED_RUN_INTERVAL_HOURS = 1
FUTURES_SYMBOLS = ["ES=F", "NQ=F", "RTY=F", "CL=F", "GC=F", "HG=F", "ZN=F", "ZB=F", "BTC=F", "ETH=F"]


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
        with path.open("r", newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def duplicate_count(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    for row in rows:
        key = tuple(row.get(k, "") for k in keys)
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def crypto_section(hours: int) -> tuple[list[str], list[str]]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    lines = ["Crypto derivatives module"]
    warnings: list[str] = []
    blocked = False
    expected_runs = max(1, hours // EXPECTED_RUN_INTERVAL_HOURS)
    expected_rows = len(PRODUCTION_CRYPTO_SYMBOLS) * expected_runs
    for name, folder in CRYPTO_TYPES.items():
        rows = read_rows(folder)
        if not rows:
            lines.extend([f"- {name}: missing files or no rows"])
            warnings.append(f"crypto {name} missing")
            continue
        success = [r for r in rows if str(r.get("request_success", "")).lower() == "true"]
        bybit_success = [r for r in success if r.get("exchange") == "bybit"]
        binance_success = [r for r in success if r.get("exchange") == "binance"]
        errors = [r for r in rows if str(r.get("request_success", "")).lower() != "true"]
        bybit_errors = [r for r in errors if r.get("exchange") == "bybit"]
        binance_errors = [r for r in errors if r.get("exchange") == "binance"]
        known_binance_region_block = [
            r for r in binance_errors
            if "known_binance_region_block" in str(r.get("error_message", ""))
            or "HTTP Error 451" in str(r.get("error_message", ""))
        ]
        latest_ts = max((parse_ts(r.get("fetch_timestamp_utc", "")) for r in success), default=None)
        latest_bybit_ts = max((parse_ts(r.get("fetch_timestamp_utc", "")) for r in bybit_success), default=None)
        recent = [r for r in success if (parse_ts(r.get("fetch_timestamp_utc", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        recent_bybit = [r for r in bybit_success if (parse_ts(r.get("fetch_timestamp_utc", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        symbols_updated = sorted({r.get("symbol", "") for r in recent_bybit if r.get("symbol")})
        missing_symbols = [s for s in PRODUCTION_CRYPTO_SYMBOLS if s not in symbols_updated]
        dupes = duplicate_count(rows, ["exchange", "symbol", "data_timestamp_utc", "source_name"])
        if missing_symbols:
            warnings.append(f"crypto {name} missing symbols: {','.join(missing_symbols)}")
        if dupes:
            warnings.append(f"crypto {name} duplicate rows: {dupes}")
        stale_hours = None
        if latest_bybit_ts:
            stale_hours = (now - latest_bybit_ts).total_seconds() / 3600
            if stale_hours > 6 * EXPECTED_RUN_INTERVAL_HOURS:
                warnings.append(f"crypto {name} latest Bybit data stale >6 intervals: {stale_hours:.2f}h")
                blocked = True
            elif stale_hours > 2 * EXPECTED_RUN_INTERVAL_HOURS:
                warnings.append(f"crypto {name} latest Bybit data stale >2 intervals: {stale_hours:.2f}h")
        else:
            warnings.append(f"crypto {name} has no Bybit success rows")
            blocked = True
        latest_text = latest_ts.isoformat().replace("+00:00", "Z") if latest_ts else ""
        latest_bybit_text = latest_bybit_ts.isoformat().replace("+00:00", "Z") if latest_bybit_ts else ""
        lines.extend([
            f"- {name}:",
            f"  latest_data_timestamp: {latest_text}",
            f"  latest_bybit_success_timestamp: {latest_bybit_text}",
            f"  production_exchange: bybit",
            f"  production_eligible_symbols: {len(PRODUCTION_CRYPTO_SYMBOLS)}",
            f"  known_missing_symbols: {','.join(sorted(KNOWN_MISSING_SYMBOLS))}",
            f"  expected_rows_last_{hours}h: {expected_rows}",
            f"  bybit_success_rows_last_{hours}h: {len(recent_bybit)}",
            f"  bybit_success_rows_total: {len(bybit_success)}",
            f"  bybit_error_rows: {len(bybit_errors)}",
            f"  binance_success_rows: {len(binance_success)}",
            f"  binance_error_rows: {len(binance_errors)}",
            f"  known_binance_region_block_count: {len(known_binance_region_block)}",
            f"  symbols_updated_last_{hours}h: {','.join(symbols_updated)}",
            f"  missing_symbols: {','.join(missing_symbols)}",
            f"  stale_hours_bybit: {stale_hours if stale_hours is not None else ''}",
            f"  duplicate_count: {dupes}",
        ])
    if blocked:
        warnings.append("__CRYPTO_BLOCKED__")
    return lines, warnings


def futures_section() -> tuple[list[str], list[str]]:
    lines = ["Traditional futures module"]
    warnings: list[str] = []
    if not FUTURES.exists():
        note = "traditional futures daily CSV missing; module is conditional until user ToS confirmation"
        lines.append(f"- {note}")
        warnings.append(note)
        return lines, warnings
    with FUTURES.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        note = "traditional futures CSV exists but has no rows"
        lines.append(f"- {note}")
        warnings.append(note)
        return lines, warnings
    latest_date = max((r.get("date", "") for r in rows), default="")
    updated = sorted({r.get("symbol", "") for r in rows if r.get("date") == latest_date})
    missing = [s for s in FUTURES_SYMBOLS if s not in updated]
    dupes = duplicate_count(rows, ["date", "symbol"])
    if missing:
        warnings.append(f"traditional futures missing latest symbols: {','.join(missing)}")
    if dupes:
        warnings.append(f"traditional futures duplicate rows: {dupes}")
    lines.extend([
        f"- latest_daily_date: {latest_date}",
        f"- symbols_updated: {','.join(updated)}",
        f"- symbols_missing: {','.join(missing)}",
        f"- duplicate_count: {dupes}",
    ])
    return lines, warnings


def run(hours: int) -> str:
    HEALTH.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    crypto_lines, crypto_warnings = crypto_section(hours)
    futures_lines, futures_warnings = futures_section()
    warnings = crypto_warnings + futures_warnings
    blocked = "__CRYPTO_BLOCKED__" in warnings
    display_warnings = [w for w in warnings if w != "__CRYPTO_BLOCKED__"]
    final_status = "BLOCKED" if blocked else ("HEALTHY" if not display_warnings else "WARNING")
    lines = [
        "E2 Unified Daily Health Report",
        f"timestamp: {now.isoformat().replace('+00:00', 'Z')}",
        "",
        *crypto_lines,
        "",
        *futures_lines,
        "",
        "warning list:",
        *(f"- {w}" for w in display_warnings),
        "",
        f"final status: {final_status}",
    ]
    text = "\n".join(lines) + "\n"
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return final_status


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 unified health check.")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    run(args.hours)


if __name__ == "__main__":
    main()
