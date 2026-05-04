from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import ENGINE_CONFIG, TradingEngine


async def main() -> int:
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

    engine = TradingEngine(config)
    try:
        if "binance" not in engine.connectors:
            summary["errors"].append("binance connector unavailable; no scan executed")
            print("v12_scan_once:")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

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
        return 1
    finally:
        await engine._cleanup()

    print("v12_scan_once:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
