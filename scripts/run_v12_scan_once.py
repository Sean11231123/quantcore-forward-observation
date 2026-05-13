from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import ENGINE_CONFIG, TradingEngine

HEARTBEAT_PATH = ROOT / "logs" / "v12_observation_heartbeat.csv"
HEARTBEAT_COLUMNS = [
    "run_started_utc",
    "run_completed_utc",
    "completed",
    "heartbeat_state",
    "connector_available",
    "data_fetch_success",
    "scan_executed",
    "signal_found",
    "signals_processed",
    "telegram_sent",
    "google_sheet_written",
    "csv_written",
    "duplicate_skipped",
    "connector_failure_category",
    "binance_testnet_key_present",
    "binance_testnet_secret_present",
    "errors_json",
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_heartbeat_row(row: dict[str, str]) -> dict[str, object]:
    out: dict[str, object] = {col: row.get(col, "") for col in HEARTBEAT_COLUMNS}
    if not out.get("heartbeat_state"):
        connector_available = row.get("connector_available", "")
        signal_found = row.get("signal_found", "")
        errors = row.get("errors_json", "")
        if connector_available == "No":
            out["heartbeat_state"] = "connector_unavailable"
            out["data_fetch_success"] = "No"
            out["scan_executed"] = "No"
            if "binance connector unavailable" in errors:
                out["connector_failure_category"] = "missing_or_unavailable_connector"
        elif signal_found == "Yes":
            out["heartbeat_state"] = "signal_found"
            out["data_fetch_success"] = "Unknown"
            out["scan_executed"] = "Unknown"
        elif connector_available == "Yes":
            out["heartbeat_state"] = "valid_no_signal"
            out["data_fetch_success"] = "Unknown"
            out["scan_executed"] = "Unknown"
    return out


def ensure_heartbeat_schema() -> None:
    if not HEARTBEAT_PATH.exists() or HEARTBEAT_PATH.stat().st_size == 0:
        return
    with HEARTBEAT_PATH.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        existing = reader.fieldnames or []
        if existing == HEARTBEAT_COLUMNS:
            return
        rows = [normalize_heartbeat_row(row) for row in reader]
    with HEARTBEAT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEARTBEAT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def append_heartbeat(row: dict[str, object]) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_heartbeat_schema()
    write_header = not HEARTBEAT_PATH.exists() or HEARTBEAT_PATH.stat().st_size == 0
    with HEARTBEAT_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEARTBEAT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in HEARTBEAT_COLUMNS})


async def main() -> int:
    run_started = utc_iso()
    config = deepcopy(ENGINE_CONFIG)
    config["execute_orders"] = False
    config["symbols"] = config.get("symbols") or ["BTC/USDT:USDT"]

    summary = {
        "completed": "Yes",
        "heartbeat_state": "connector_unavailable",
        "data_fetch_success": "No",
        "scan_executed": "No",
        "signal_found": "No",
        "signals_processed": 0,
        "telegram_sent": 0,
        "google_sheet_written": 0,
        "csv_written": 0,
        "duplicate_skipped": 0,
        "connector_failure_category": "",
        "errors": [],
    }
    connector_available = "Unknown"
    exit_code = 0

    engine = TradingEngine(config)
    try:
        if "binance" not in engine.connectors:
            connector_available = "No"
            key_present = bool(os.getenv("BINANCE_TESTNET_KEY", ""))
            secret_present = bool(os.getenv("BINANCE_TESTNET_SECRET", ""))
            summary["connector_failure_category"] = "missing_binance_testnet_secret" if not (key_present and secret_present) else "connector_initialization_failed"
            summary["errors"].append(
                "binance connector unavailable; no scan executed; "
                f"BINANCE_TESTNET_KEY_present={key_present}; "
                f"BINANCE_TESTNET_SECRET_present={secret_present}"
            )
            print("v12_scan_once:")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        connector_available = "Yes"
        before = len(engine._signal_log)
        await engine._regime_detection_once()
        if not engine._regime_cache:
            summary["heartbeat_state"] = "data_fetch_failed"
            summary["data_fetch_success"] = "No"
            summary["scan_executed"] = "No"
            summary["errors"].append("binance connector initialized but no regime data was fetched")
        else:
            summary["data_fetch_success"] = "Yes"
            await engine._signal_generation_once()
            summary["scan_executed"] = "Yes"
            after = len(engine._signal_log)
            processed = max(after - before, 0)
            summary["signals_processed"] = processed
            summary["signal_found"] = "Yes" if processed else "No"
            summary["heartbeat_state"] = "signal_found" if processed else "valid_no_signal"
    except Exception as exc:
        summary["completed"] = "No"
        if connector_available == "Yes":
            summary["heartbeat_state"] = "data_fetch_failed"
            summary["connector_failure_category"] = "runtime_exception"
        summary["errors"].append(str(exc))
        print("v12_scan_once:")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        exit_code = 1
        return exit_code
    finally:
        await engine._cleanup()
        append_heartbeat({
            "run_started_utc": run_started,
            "run_completed_utc": utc_iso(),
            "completed": summary["completed"],
            "heartbeat_state": summary["heartbeat_state"],
            "connector_available": connector_available,
            "data_fetch_success": summary["data_fetch_success"],
            "scan_executed": summary["scan_executed"],
            "signal_found": summary["signal_found"],
            "signals_processed": summary["signals_processed"],
            "telegram_sent": summary["telegram_sent"],
            "google_sheet_written": summary["google_sheet_written"],
            "csv_written": summary["csv_written"],
            "duplicate_skipped": summary["duplicate_skipped"],
            "connector_failure_category": summary["connector_failure_category"],
            "binance_testnet_key_present": "Yes" if os.getenv("BINANCE_TESTNET_KEY", "") else "No",
            "binance_testnet_secret_present": "Yes" if os.getenv("BINANCE_TESTNET_SECRET", "") else "No",
            "errors_json": json.dumps(summary["errors"], ensure_ascii=False),
        })

    print("v12_scan_once:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
