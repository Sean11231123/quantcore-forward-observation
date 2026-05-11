from __future__ import annotations

import csv
import os
from typing import Any


CSV_PATH = os.path.join("logs", "v12_signals.csv")

FIELDS = [
    "signal_id",
    "logged_at",
    "signal_timestamp",
    "strategy_name",
    "strategy_version",
    "timeframe",
    "research_tier",
    "symbol",
    "side",
    "entry_price",
    "stop_loss",
    "take_profit",
    "atr",
    "adx_entry_tf",
    "adx_confirm_tf",
    "btc_re",
    "btc_adx_confirm_tf",
    "volume_ratio",
    "atr_expansion_ratio",
    "candle_close_position",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "whitelist_score",
    "regime",
    "executed",
    "result",
    "exit_price",
    "exit_type",
    "pnl_pct",
    "leave_a_comment",
    "news_sources",
]


def _existing_signal_ids(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return {row.get("signal_id", "") for row in reader if row.get("signal_id")}


def signal_exists(signal_id: str, path: str = CSV_PATH) -> bool:
    if not signal_id:
        return False
    return signal_id in _existing_signal_ids(path)


def log_signal(signal: dict[str, Any], path: str = CSV_PATH) -> dict[str, Any]:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    signal_id = str(signal.get("signal_id", ""))
    if not signal_id:
        return {"status": "ERROR", "inserted": False, "deduped": False, "error": "signal_id missing"}

    existing_ids = _existing_signal_ids(path)
    file_exists = os.path.exists(path)
    if signal_id in existing_ids:
        return {"status": "OK", "inserted": False, "deduped": True, "error": ""}

    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: signal.get(field, "") for field in FIELDS})
    return {"status": "OK", "inserted": True, "deduped": False, "error": ""}


def header_correct(path: str = CSV_PATH) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
    return header == FIELDS
