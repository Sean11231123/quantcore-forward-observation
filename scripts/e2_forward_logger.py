from __future__ import annotations

import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "forward" / "crypto_derivatives"

FUNDING_COLUMNS = [
    "fetch_timestamp_utc",
    "data_timestamp_utc",
    "exchange",
    "symbol",
    "raw_exchange_symbol",
    "funding_rate",
    "next_funding_time_utc",
    "mark_price_if_available",
    "request_success",
    "error_message",
    "source_name",
]
OI_COLUMNS = [
    "fetch_timestamp_utc",
    "data_timestamp_utc",
    "exchange",
    "symbol",
    "raw_exchange_symbol",
    "open_interest",
    "open_interest_value_usd_if_available",
    "request_success",
    "error_message",
    "source_name",
]
MARK_COLUMNS = [
    "fetch_timestamp_utc",
    "data_timestamp_utc",
    "exchange",
    "symbol",
    "raw_exchange_symbol",
    "mark_price",
    "index_price",
    "premium_abs",
    "premium_pct",
    "request_success",
    "error_message",
    "source_name",
]
HEALTH_COLUMNS = [
    "health_timestamp_utc",
    "run_id",
    "expected_symbol_count",
    "successful_symbol_count",
    "failed_symbol_count",
    "funding_success_count",
    "oi_success_count",
    "mark_index_success_count",
    "missing_symbols",
    "failed_symbols",
    "duplicate_rows_prevented",
    "total_rows_written",
    "run_duration_seconds",
    "overall_status",
    "notes",
]

DEFAULT_SYMBOLS = [
    "ADA_USDT",
    "APT_USDT",
    "ARB_USDT",
    "AVAX_USDT",
    "BCH_USDT",
    "BNB_USDT",
    "DOGE_USDT",
    "DOT_USDT",
    "ETH_USDT",
    "FTM_USDT",
    "LINK_USDT",
    "LTC_USDT",
    "NEAR_USDT",
    "OP_USDT",
    "POL_USDT",
    "SOL_USDT",
    "SUI_USDT",
    "TRX_USDT",
    "XRP_USDT",
]


@dataclass
class RunStats:
    run_id: str
    expected_symbol_count: int
    duplicate_rows_prevented: int = 0
    total_rows_written: int = 0
    funding_success_count: int = 0
    oi_success_count: int = 0
    mark_index_success_count: int = 0
    failed: dict[str, set[str]] | None = None

    def __post_init__(self) -> None:
        if self.failed is None:
            self.failed = {}

    def record_failure(self, symbol: str, data_type: str) -> None:
        assert self.failed is not None
        self.failed.setdefault(symbol, set()).add(data_type)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hour_bucket_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def ms_to_iso(value: Any, fallback: str) -> str:
    try:
        if value in (None, "", 0, "0"):
            return fallback
        return iso_utc(datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc))
    except Exception:
        return fallback


def to_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return math.nan
        return float(value)
    except Exception:
        return math.nan


def month_path(data_type: str, fetch_ts: str) -> Path:
    ym = fetch_ts[:7].replace("-", "_")
    if data_type == "funding":
        return OUT_DIR / "funding" / f"funding_{ym}.csv"
    if data_type == "open_interest":
        return OUT_DIR / "open_interest" / f"open_interest_{ym}.csv"
    if data_type == "mark_index_premium":
        return OUT_DIR / "mark_index_premium" / f"mark_index_premium_{ym}.csv"
    if data_type == "health":
        return OUT_DIR / "health" / f"e2_health_{ym}.csv"
    raise ValueError(f"unknown data_type: {data_type}")


def read_existing_keys(path: Path, key_cols: list[str]) -> set[tuple[str, ...]]:
    if not path.exists():
        return set()
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {tuple(row.get(col, "") for col in key_cols) for row in reader}


def append_rows(path: Path, columns: list[str], rows: list[dict[str, Any]], key_cols: list[str]) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_existing_keys(path, key_cols)
    new_rows: list[dict[str, Any]] = []
    duplicates = 0
    for row in rows:
        key = tuple(str(row.get(col, "")) for col in key_cols)
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        new_rows.append({col: row.get(col, "") for col in columns})
    if not new_rows:
        return 0, duplicates
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows), duplicates


def http_json(url: str, retries: int = 3, timeout: int = 15) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "quantcore-e2-forward-logger/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def bybit_symbol(symbol: str) -> str:
    return symbol.replace("_", "")


def binance_symbol(symbol: str) -> str:
    return symbol.replace("_", "")


def project_symbols() -> tuple[list[str], str]:
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        import config  # type: ignore

        raw_symbols = getattr(config, "SYMBOLS", [])
        converted = [str(s).replace("/", "_") for s in raw_symbols]
        non_btc = [s for s in converted if s != "BTC_USDT"]
        expected = set(DEFAULT_SYMBOLS)
        if set(non_btc) == expected:
            return sorted(non_btc), "config.py SYMBOLS matched E2 19-symbol universe after BTC exclusion."
        return DEFAULT_SYMBOLS, f"config.py mismatch; using Claude-approved E2 universe. config_non_btc={sorted(non_btc)}"
    except Exception as exc:
        return DEFAULT_SYMBOLS, f"config.py unavailable; using Claude-approved E2 universe. error={exc}"


def fetch_bybit_ticker(symbol: str, fetch_ts: str) -> tuple[dict[str, Any] | None, str]:
    raw = bybit_symbol(symbol)
    query = urllib.parse.urlencode({"category": "linear", "symbol": raw})
    url = f"https://api.bybit.com/v5/market/tickers?{query}"
    data = http_json(url)
    if data.get("retCode") != 0:
        return None, f"bybit retCode={data.get('retCode')} retMsg={data.get('retMsg')}"
    result = data.get("result", {}).get("list", [])
    if not result:
        return None, "bybit ticker returned empty list"
    return result[0], ""


def fetch_binance_premium(symbol: str) -> tuple[dict[str, Any] | None, str]:
    raw = binance_symbol(symbol)
    query = urllib.parse.urlencode({"symbol": raw})
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?{query}"
    data = http_json(url)
    if not isinstance(data, dict) or "symbol" not in data:
        return None, f"binance unexpected response={data}"
    return data, ""


def rows_for_symbol(symbol: str, fetch_ts: str, fetch_bucket_ts: str, prefer_exchange: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    funding_rows: list[dict[str, Any]] = []
    oi_rows: list[dict[str, Any]] = []
    mark_rows: list[dict[str, Any]] = []

    bybit_data: dict[str, Any] | None = None
    bybit_error = ""
    if prefer_exchange in ("bybit", "both"):
        try:
            bybit_data, bybit_error = fetch_bybit_ticker(symbol, fetch_ts)
        except Exception as exc:
            bybit_error = str(exc)
        raw = bybit_symbol(symbol)
        if bybit_data:
            mark = to_float(bybit_data.get("markPrice"))
            index = to_float(bybit_data.get("indexPrice"))
            premium_abs = mark - index if math.isfinite(mark) and math.isfinite(index) else math.nan
            premium_pct = mark / index - 1 if math.isfinite(mark) and math.isfinite(index) and index > 0 else math.nan
            data_ts = fetch_bucket_ts
            next_funding = ms_to_iso(bybit_data.get("nextFundingTime"), fetch_ts)
            funding_rows.append({
                "fetch_timestamp_utc": fetch_ts,
                "data_timestamp_utc": data_ts,
                "exchange": "bybit",
                "symbol": symbol,
                "raw_exchange_symbol": raw,
                "funding_rate": bybit_data.get("fundingRate", ""),
                "next_funding_time_utc": next_funding,
                "mark_price_if_available": bybit_data.get("markPrice", ""),
                "request_success": True,
                "error_message": "",
                "source_name": "bybit_v5_market_tickers",
            })
            oi_rows.append({
                "fetch_timestamp_utc": fetch_ts,
                "data_timestamp_utc": data_ts,
                "exchange": "bybit",
                "symbol": symbol,
                "raw_exchange_symbol": raw,
                "open_interest": bybit_data.get("openInterest", ""),
                "open_interest_value_usd_if_available": bybit_data.get("openInterestValue", ""),
                "request_success": True,
                "error_message": "",
                "source_name": "bybit_v5_market_tickers",
            })
            mark_rows.append({
                "fetch_timestamp_utc": fetch_ts,
                "data_timestamp_utc": data_ts,
                "exchange": "bybit",
                "symbol": symbol,
                "raw_exchange_symbol": raw,
                "mark_price": bybit_data.get("markPrice", ""),
                "index_price": bybit_data.get("indexPrice", ""),
                "premium_abs": premium_abs,
                "premium_pct": premium_pct,
                "request_success": True,
                "error_message": "",
                "source_name": "bybit_v5_market_tickers",
            })
        else:
            err = bybit_error or "bybit ticker unavailable"
            funding_rows.append(failure_row(fetch_ts, fetch_bucket_ts, "bybit", symbol, raw, "funding", err, "bybit_v5_market_tickers"))
            oi_rows.append(failure_row(fetch_ts, fetch_bucket_ts, "bybit", symbol, raw, "open_interest", err, "bybit_v5_market_tickers"))
            mark_rows.append(failure_row(fetch_ts, fetch_bucket_ts, "bybit", symbol, raw, "mark_index_premium", err, "bybit_v5_market_tickers"))

    if prefer_exchange in ("binance", "both"):
        raw = binance_symbol(symbol)
        binance_data: dict[str, Any] | None = None
        binance_error = ""
        try:
            binance_data, binance_error = fetch_binance_premium(symbol)
        except Exception as exc:
            binance_error = str(exc)
        if binance_data:
            data_ts = ms_to_iso(binance_data.get("time"), fetch_ts)
            mark = to_float(binance_data.get("markPrice"))
            index = to_float(binance_data.get("indexPrice"))
            premium_abs = mark - index if math.isfinite(mark) and math.isfinite(index) else math.nan
            premium_pct = mark / index - 1 if math.isfinite(mark) and math.isfinite(index) and index > 0 else math.nan
            funding_rows.append({
                "fetch_timestamp_utc": fetch_ts,
                "data_timestamp_utc": data_ts,
                "exchange": "binance",
                "symbol": symbol,
                "raw_exchange_symbol": raw,
                "funding_rate": binance_data.get("lastFundingRate", ""),
                "next_funding_time_utc": ms_to_iso(binance_data.get("nextFundingTime"), fetch_ts),
                "mark_price_if_available": binance_data.get("markPrice", ""),
                "request_success": True,
                "error_message": "",
                "source_name": "binance_fapi_premiumIndex",
            })
            mark_rows.append({
                "fetch_timestamp_utc": fetch_ts,
                "data_timestamp_utc": data_ts,
                "exchange": "binance",
                "symbol": symbol,
                "raw_exchange_symbol": raw,
                "mark_price": binance_data.get("markPrice", ""),
                "index_price": binance_data.get("indexPrice", ""),
                "premium_abs": premium_abs,
                "premium_pct": premium_pct,
                "request_success": True,
                "error_message": "",
                "source_name": "binance_fapi_premiumIndex",
            })
        else:
            err = binance_error or "binance premiumIndex unavailable"
            funding_rows.append(failure_row(fetch_ts, fetch_bucket_ts, "binance", symbol, raw, "funding", err, "binance_fapi_premiumIndex"))
            mark_rows.append(failure_row(fetch_ts, fetch_bucket_ts, "binance", symbol, raw, "mark_index_premium", err, "binance_fapi_premiumIndex"))
    return funding_rows, oi_rows, mark_rows


def failure_row(fetch_ts: str, data_ts: str, exchange: str, symbol: str, raw: str, data_type: str, error: str, source: str) -> dict[str, Any]:
    base = {
        "fetch_timestamp_utc": fetch_ts,
        "data_timestamp_utc": data_ts,
        "exchange": exchange,
        "symbol": symbol,
        "raw_exchange_symbol": raw,
        "request_success": False,
        "error_message": error[:500],
        "source_name": source,
    }
    if data_type == "funding":
        return {**base, "funding_rate": "", "next_funding_time_utc": "", "mark_price_if_available": ""}
    if data_type == "open_interest":
        return {**base, "open_interest": "", "open_interest_value_usd_if_available": ""}
    if data_type == "mark_index_premium":
        return {**base, "mark_price": "", "index_price": "", "premium_abs": "", "premium_pct": ""}
    return base


def write_health(fetch_ts: str, stats: RunStats, started: float, notes: str) -> Path:
    assert stats.failed is not None
    failed_symbols = sorted(stats.failed)
    successful_symbols = stats.expected_symbol_count - len(failed_symbols)
    missing_symbols = failed_symbols
    status = "OK"
    if successful_symbols == 0:
        status = "FAILED"
    elif failed_symbols:
        status = "PARTIAL"
    row = {
        "health_timestamp_utc": fetch_ts,
        "run_id": stats.run_id,
        "expected_symbol_count": stats.expected_symbol_count,
        "successful_symbol_count": successful_symbols,
        "failed_symbol_count": len(failed_symbols),
        "funding_success_count": stats.funding_success_count,
        "oi_success_count": stats.oi_success_count,
        "mark_index_success_count": stats.mark_index_success_count,
        "missing_symbols": ";".join(missing_symbols),
        "failed_symbols": json.dumps({k: sorted(v) for k, v in stats.failed.items()}, sort_keys=True),
        "duplicate_rows_prevented": stats.duplicate_rows_prevented,
        "total_rows_written": stats.total_rows_written,
        "run_duration_seconds": round(time.time() - started, 3),
        "overall_status": status,
        "notes": notes,
    }
    path = month_path("health", fetch_ts)
    append_rows(path, HEALTH_COLUMNS, [row], ["run_id"])
    return path


def run_logger(exchange: str, dry_run: bool = False) -> int:
    started = time.time()
    fetch_dt = utc_now()
    fetch_ts = iso_utc(fetch_dt)
    fetch_bucket_ts = hour_bucket_iso(fetch_dt)
    run_id = fetch_dt.strftime("e2_%Y%m%dT%H%M%SZ")
    symbols, symbol_note = project_symbols()
    stats = RunStats(run_id=run_id, expected_symbol_count=len(symbols))

    all_funding: list[dict[str, Any]] = []
    all_oi: list[dict[str, Any]] = []
    all_mark: list[dict[str, Any]] = []
    for symbol in symbols:
        funding_rows, oi_rows, mark_rows = rows_for_symbol(symbol, fetch_ts, fetch_bucket_ts, exchange)
        all_funding.extend(funding_rows)
        all_oi.extend(oi_rows)
        all_mark.extend(mark_rows)
        if not any(str(r.get("request_success")).lower() == "true" or r.get("request_success") is True for r in funding_rows):
            stats.record_failure(symbol, "funding")
        if not any(str(r.get("request_success")).lower() == "true" or r.get("request_success") is True for r in oi_rows):
            stats.record_failure(symbol, "open_interest")
        if not any(str(r.get("request_success")).lower() == "true" or r.get("request_success") is True for r in mark_rows):
            stats.record_failure(symbol, "mark_index_premium")

    stats.funding_success_count = sum(1 for r in all_funding if r.get("request_success") is True)
    stats.oi_success_count = sum(1 for r in all_oi if r.get("request_success") is True)
    stats.mark_index_success_count = sum(1 for r in all_mark if r.get("request_success") is True)

    if not dry_run:
        for data_type, columns, rows in [
            ("funding", FUNDING_COLUMNS, all_funding),
            ("open_interest", OI_COLUMNS, all_oi),
            ("mark_index_premium", MARK_COLUMNS, all_mark),
        ]:
            path = month_path(data_type, fetch_ts)
            written, duplicates = append_rows(
                path,
                columns,
                rows,
                ["exchange", "symbol", "data_timestamp_utc", "source_name"],
            )
            stats.total_rows_written += written
            stats.duplicate_rows_prevented += duplicates
        health_path = write_health(fetch_ts, stats, started, symbol_note)
    else:
        health_path = Path("(dry-run-no-file)")

    summary = {
        "run_id": run_id,
        "exchange_mode": exchange,
        "dry_run": dry_run,
        "symbols": symbols,
        "funding_rows": len(all_funding),
        "oi_rows": len(all_oi),
        "mark_rows": len(all_mark),
        "funding_success_count": stats.funding_success_count,
        "oi_success_count": stats.oi_success_count,
        "mark_index_success_count": stats.mark_index_success_count,
        "rows_written": stats.total_rows_written,
        "duplicates_prevented": stats.duplicate_rows_prevented,
        "health_path": str(health_path),
        "failed_symbols": {k: sorted(v) for k, v in (stats.failed or {}).items()},
        "notes": symbol_note,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if stats.funding_success_count or stats.oi_success_count or stats.mark_index_success_count else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 Layer 1 derivatives forward logger.")
    parser.add_argument("--exchange", choices=["bybit", "binance", "both"], default="bybit")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize without writing CSV rows.")
    args = parser.parse_args()
    raise SystemExit(run_logger(exchange=args.exchange, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
