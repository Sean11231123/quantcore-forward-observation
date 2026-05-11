from __future__ import annotations

import asyncio
import csv
import json
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
    "connector_available",
    "signal_found",
    "signals_processed",
    "telegram_sent",
    "google_sheet_written",
    "csv_written",
    "duplicate_skipped",
    "errors_json",
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_heartbeat(row: dict[str, object]) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        "signal_found": "No",
        "signals_processed": 0,
        "telegram_sent": 0,
        "google_sheet_written": 0,
        "csv_written": 0,
        "duplicate_skipped": 0,
        "errors": [],
    }
    connector_available = "Unknown"
    exit_code = 0

    engine = TradingEngine(config)
    try:
        if "binance" not in engine.connectors:
            connector_available = "No"
            summary["errors"].append("binance connector unavailable; no scan executed")
            print("v12_scan_once:")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        connector_available = "Yes"
        before = len(engine._signal_log)
        await engine._regime_detection_once()
        await engine._signal_generation_once()
        after = len(engine._signal_log)
        processed = max(after - before, 0)
        summary["signals_processed"] = processed
        summary["signal_found"] = "Yes" if processed else "No"
    except Exception as exc:
        summary["completed"] = "No"
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
            "connector_available": connector_available,
            "signal_found": summary["signal_found"],
            "signals_processed": summary["signals_processed"],
            "telegram_sent": summary["telegram_sent"],
            "google_sheet_written": summary["google_sheet_written"],
            "csv_written": summary["csv_written"],
            "duplicate_skipped": summary["duplicate_skipped"],
            "errors_json": json.dumps(summary["errors"], ensure_ascii=False),
        })

    print("v12_scan_once:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
