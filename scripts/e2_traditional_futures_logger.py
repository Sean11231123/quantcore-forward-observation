from __future__ import annotations

import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "forward" / "traditional_futures"
DAILY_PATH = BASE / "daily" / "traditional_futures_daily.csv"
METADATA_DIR = BASE / "metadata"
HEALTH_DIR = ROOT / "data" / "forward" / "health"

SOURCE = "Yahoo Finance chart endpoint"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"

FUTURES = {
    "ES=F": ("equity_index", "E-mini S&P 500 continuous/front-month proxy"),
    "NQ=F": ("equity_index", "Nasdaq 100 continuous/front-month proxy"),
    "RTY=F": ("equity_index", "Russell 2000 continuous/front-month proxy"),
    "CL=F": ("energy", "WTI crude oil continuous/front-month proxy"),
    "GC=F": ("metals", "Gold continuous/front-month proxy"),
    "HG=F": ("metals", "Copper continuous/front-month proxy"),
    "ZN=F": ("rates", "10Y Treasury Note continuous/front-month proxy"),
    "ZB=F": ("rates", "30Y Treasury Bond continuous/front-month proxy"),
    "BTC=F": ("crypto_cme", "CME Bitcoin futures continuous/front-month proxy"),
    "ETH=F": ("crypto_cme", "CME Ether futures continuous/front-month proxy"),
}

COLUMNS = [
    "timestamp",
    "date",
    "source",
    "symbol",
    "raw_symbol",
    "asset_class",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "fetch_time_utc",
    "data_status",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    for path in [
        BASE / "daily",
        BASE / "equity_index",
        BASE / "rates",
        BASE / "fx",
        BASE / "metals",
        BASE / "energy",
        BASE / "crypto_cme",
        METADATA_DIR,
        HEALTH_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open("r", newline="", encoding="utf-8") as handle:
        return {(row.get("date", ""), row.get("symbol", "")) for row in csv.DictReader(handle)}


def append_rows(path: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = existing_keys(path)
    write_header = not path.exists() or path.stat().st_size == 0
    written = 0
    duplicates = 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        for row in rows:
            key = (str(row.get("date", "")), str(row.get("symbol", "")))
            if key in keys:
                duplicates += 1
                continue
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
            keys.add(key)
            written += 1
    return written, duplicates


def fetch_symbol(symbol: str, fetch_time: str, timeout: int = 20) -> dict[str, Any]:
    query = urllib.parse.urlencode({"range": "10d", "interval": "1d", "events": "history"})
    url = YAHOO_CHART.format(symbol=urllib.parse.quote(symbol, safe=""), query=query)
    request = urllib.request.Request(url, headers={"User-Agent": "quantcore-e2-data-availability/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("chart", {}).get("result", [])
    if not result:
        raise RuntimeError(payload.get("chart", {}).get("error") or "empty Yahoo chart result")
    block = result[0]
    timestamps = block.get("timestamp") or []
    quote = (block.get("indicators", {}).get("quote") or [{}])[0]
    adj = (block.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    if not timestamps:
        raise RuntimeError("no daily timestamps returned")

    idx = len(timestamps) - 1
    dt = datetime.fromtimestamp(timestamps[idx], tz=timezone.utc).replace(microsecond=0)
    asset_class, _ = FUTURES[symbol]

    def val(name: str) -> float | int | str:
        values = quote.get(name) or []
        if idx >= len(values) or values[idx] is None:
            return ""
        value = values[idx]
        if isinstance(value, float) and math.isnan(value):
            return ""
        return value

    adj_value: float | str = ""
    if idx < len(adj) and adj[idx] is not None and not (isinstance(adj[idx], float) and math.isnan(adj[idx])):
        adj_value = adj[idx]

    return {
        "timestamp": iso(dt),
        "date": dt.date().isoformat(),
        "source": SOURCE,
        "symbol": symbol,
        "raw_symbol": symbol,
        "asset_class": asset_class,
        "open": val("open"),
        "high": val("high"),
        "low": val("low"),
        "close": val("close"),
        "adj_close": adj_value,
        "volume": val("volume"),
        "fetch_time_utc": fetch_time,
        "data_status": "SUCCESS",
    }


def write_metadata(status: str, rows: list[dict[str, Any]], failures: dict[str, str], duplicate_count: int, notes: str) -> None:
    fetch_time = iso(utc_now())
    metadata = {
        "timestamp_utc": fetch_time,
        "status": status,
        "source": SOURCE,
        "symbols_requested": sorted(FUTURES),
        "symbols_succeeded": sorted(row["symbol"] for row in rows),
        "symbols_failed": failures,
        "duplicates_prevented": duplicate_count,
        "notes": notes,
        "governance": "Infrastructure only. No crypto merge, return calculation, signal, alpha label, or backtest.",
    }
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    (METADATA_DIR / "traditional_futures_logger_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def write_health(status: str, rows: list[dict[str, Any]], failures: dict[str, str], written: int, duplicates: int, notes: str) -> None:
    lines = [
        "E2 Traditional Futures Logger Health",
        f"timestamp_utc: {iso(utc_now())}",
        f"status: {status}",
        f"source: {SOURCE}",
        f"rows_written: {written}",
        f"duplicates_prevented: {duplicates}",
        f"symbols_succeeded: {','.join(sorted(row['symbol'] for row in rows))}",
        f"symbols_failed: {json.dumps(failures, sort_keys=True)}",
        f"notes: {notes}",
    ]
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    (HEALTH_DIR / "e2_traditional_futures_health_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(confirm_yahoo_tos: bool, dry_run: bool) -> int:
    ensure_dirs()
    if not confirm_yahoo_tos:
        note = (
            "FUTURES LOGGER CONDITIONAL - USER ToS CONFIRMATION REQUIRED. "
            "Yahoo Finance automated daily retrieval was not executed."
        )
        write_metadata("CONDITIONAL", [], {}, 0, note)
        write_health("WARNING", [], {}, 0, 0, note)
        print(note)
        return 0

    started = time.time()
    fetch_time = iso(utc_now())
    rows: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    for symbol in FUTURES:
        try:
            rows.append(fetch_symbol(symbol, fetch_time))
        except Exception as exc:
            failures[symbol] = str(exc)

    if dry_run:
        written = 0
        duplicates = 0
        status = "DRY_RUN"
    else:
        written, duplicates = append_rows(DAILY_PATH, rows)
        status = "SUCCESS" if rows else "FAILED"
    notes = (
        "Conditional Yahoo Finance futures proxy logger. Continuous/front-month symbols may roll "
        "and are broad risk proxies only. No strategy or outcome testing performed. "
        f"duration_seconds={time.time() - started:.2f}"
    )
    write_metadata(status, rows, failures, duplicates, notes)
    write_health("HEALTHY" if rows and not failures else "WARNING", rows, failures, written, duplicates, notes)
    print(json.dumps({"status": status, "rows": len(rows), "written": written, "failures": failures}, indent=2))
    return 0 if rows else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 conditional traditional futures proxy logger.")
    parser.add_argument("--confirm-yahoo-tos", action="store_true", help="User confirms Yahoo Finance usage is acceptable for this repo.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize without appending rows.")
    args = parser.parse_args()
    raise SystemExit(run(confirm_yahoo_tos=args.confirm_yahoo_tos, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
