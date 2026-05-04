from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from logs.google_sheets_logger import (
    delete_bot_state,
    get_bot_state,
    get_signal,
    set_bot_state,
    upsert_manual_review,
)
from notifications.telegram_bot import answer_callback_query, get_updates, send_message


CSV_SIGNAL_PATH = ROOT / "logs" / "v12_signals.csv"
LAST_UPDATE_KEY = "telegram_last_update_id"


@dataclass
class ParsedCallback:
    kind: str
    signal_id: str
    decision: str = ""
    valid: bool = False


@dataclass
class MemoryState:
    state: dict[str, str] = field(default_factory=dict)
    reviews: dict[str, dict[str, Any]] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def parse_callback_data(data: str) -> ParsedCallback:
    parts = (data or "").split("|")
    if len(parts) == 3 and parts[0] == "qc_result" and parts[2] in {"entered", "skipped", "missed"}:
        return ParsedCallback(kind="result", signal_id=parts[1], decision=parts[2], valid=bool(parts[1]))
    if len(parts) == 2 and parts[0] == "qc_reason":
        return ParsedCallback(kind="reason", signal_id=parts[1], valid=bool(parts[1]))
    if len(parts) == 2 and parts[0] == "qc_detail":
        return ParsedCallback(kind="detail", signal_id=parts[1], valid=bool(parts[1]))
    return ParsedCallback(kind="", signal_id="", valid=False)


def _allowed_user_ids() -> set[str]:
    raw = os.getenv("REVIEW_ALLOWED_USER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _user_allowed(user: dict[str, Any]) -> bool:
    allowed = _allowed_user_ids()
    if not allowed:
        return True
    return str(user.get("id", "")) in allowed


def _reviewed_by(user: dict[str, Any]) -> str:
    username = user.get("username")
    return f"{user.get('id', '')}:{username}" if username else str(user.get("id", ""))


def _send_chunks(text: str, chat_id: str | int | None, dry_store: MemoryState | None = None) -> None:
    chunks = [text[idx : idx + 3500] for idx in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        if dry_store is not None:
            dry_store.messages.append(chunk)
        else:
            send_message(chunk, chat_id=str(chat_id) if chat_id is not None else None, parse_mode=None)


def _get_signal_from_csv(signal_id: str) -> dict[str, str]:
    if not CSV_SIGNAL_PATH.exists():
        return {}
    with open(CSV_SIGNAL_PATH, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("signal_id") == signal_id:
            return row
    for row in rows:
        if row.get("signal_id", "").startswith(signal_id):
            return row
    return {}


def _get_signal_detail(signal_id: str) -> dict[str, str]:
    sheet_result = get_signal(signal_id)
    if sheet_result.get("found"):
        return sheet_result.get("signal", {})
    return _get_signal_from_csv(signal_id)


def _state_get(key: str, dry_store: MemoryState | None = None) -> str:
    if dry_store is not None:
        return dry_store.state.get(key, "")
    result = get_bot_state(key)
    return str(result.get("value", ""))


def _state_set(key: str, value: str, dry_store: MemoryState | None = None) -> dict[str, Any]:
    if dry_store is not None:
        dry_store.state[key] = value
        return {"status": "OK", "updated": True}
    return set_bot_state(key, value)


def _state_delete(key: str, dry_store: MemoryState | None = None) -> dict[str, Any]:
    if dry_store is not None:
        dry_store.state.pop(key, None)
        return {"status": "OK", "deleted": True}
    return delete_bot_state(key)


def _review_upsert(signal_id: str, fields: dict[str, Any], dry_store: MemoryState | None = None) -> dict[str, Any]:
    if dry_store is not None:
        current = dry_store.reviews.setdefault(signal_id, {"signal_id": signal_id})
        current.update(fields)
        return {"status": "OK", "upserted": True}
    return upsert_manual_review(signal_id, fields)


def process_callback(update: dict[str, Any], dry_store: MemoryState | None = None) -> dict[str, Any]:
    callback = update.get("callback_query", {})
    parsed = parse_callback_data(callback.get("data", ""))
    user = callback.get("from", {})
    message = callback.get("message", {})
    chat_id = (message.get("chat") or {}).get("id")
    if not parsed.valid:
        return {"status": "ignored", "reason": "unsupported_callback"}
    if not _user_allowed(user):
        return {"status": "ignored", "reason": "unauthorized_user"}

    reviewed_by = _reviewed_by(user)
    now = datetime.now(timezone.utc).isoformat()

    if dry_store is None:
        answer_callback_query(callback.get("id", ""), text="Received")

    if parsed.kind == "result":
        result = _review_upsert(
            parsed.signal_id,
            {
                "manual_decision": parsed.decision,
                "reviewed_at": now,
                "reviewed_by": reviewed_by,
            },
            dry_store=dry_store,
        )
        _send_chunks(f"已記錄 {parsed.signal_id}: {parsed.decision}", chat_id, dry_store=dry_store)
        return {"status": result.get("status", "OK"), "processed": "result", "signal_id": parsed.signal_id}

    if parsed.kind == "reason":
        _state_set(f"pending_reason:{user.get('id')}", parsed.signal_id, dry_store=dry_store)
        _send_chunks(f"請直接傳送你的判斷原因，我會寫入 signal_id={parsed.signal_id}", chat_id, dry_store=dry_store)
        return {"status": "OK", "processed": "reason", "signal_id": parsed.signal_id}

    if parsed.kind == "detail":
        signal = _get_signal_detail(parsed.signal_id)
        detail = signal.get("leave_a_comment") or "No detail found for this signal."
        _send_chunks(detail, chat_id, dry_store=dry_store)
        return {"status": "OK", "processed": "detail", "signal_id": parsed.signal_id}

    return {"status": "ignored", "reason": "unknown_kind"}


def process_text(update: dict[str, Any], dry_store: MemoryState | None = None) -> dict[str, Any]:
    message = update.get("message", {})
    text = str(message.get("text", "") or "").strip()
    user = message.get("from", {})
    chat_id = (message.get("chat") or {}).get("id")
    if not text:
        return {"status": "ignored", "reason": "empty_text"}
    if not _user_allowed(user):
        return {"status": "ignored", "reason": "unauthorized_user"}

    key = f"pending_reason:{user.get('id')}"
    signal_id = _state_get(key, dry_store=dry_store)
    if not signal_id:
        _send_chunks("目前沒有等待補充原因的 signal。請先按補充原因。", chat_id, dry_store=dry_store)
        return {"status": "ignored", "reason": "no_pending_reason"}

    result = _review_upsert(
        signal_id,
        {
            "manual_reason": text,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": _reviewed_by(user),
        },
        dry_store=dry_store,
    )
    _state_delete(key, dry_store=dry_store)
    _send_chunks(f"已記錄原因：{signal_id}", chat_id, dry_store=dry_store)
    return {"status": result.get("status", "OK"), "processed": "text_reason", "signal_id": signal_id}


def process_update(update: dict[str, Any], dry_store: MemoryState | None = None) -> dict[str, Any]:
    if "callback_query" in update:
        return process_callback(update, dry_store=dry_store)
    if "message" in update:
        return process_text(update, dry_store=dry_store)
    return {"status": "ignored", "reason": "unsupported_update"}


def poll_once() -> dict[str, Any]:
    _load_env()
    last_raw = get_bot_state(LAST_UPDATE_KEY)
    if last_raw.get("status") != "OK":
        return {"status": last_raw.get("status"), "processed": 0, "error": last_raw.get("error", "")}
    try:
        offset = int(last_raw.get("value") or "0") + 1
    except ValueError:
        offset = None

    updates_result = get_updates(offset=offset, timeout=0)
    if updates_result.get("status") != "OK":
        return {"status": updates_result.get("status"), "processed": 0, "error": updates_result.get("error", "")}

    processed = 0
    max_update_id = None
    errors: list[str] = []
    for update in updates_result.get("updates", []):
        max_update_id = max(max_update_id or update.get("update_id", 0), update.get("update_id", 0))
        result = process_update(update)
        if result.get("status") == "ERROR":
            errors.append(result.get("error", "unknown"))
        else:
            processed += 1

    if max_update_id is not None:
        set_bot_state(LAST_UPDATE_KEY, str(max_update_id))

    return {"status": "OK", "processed": processed, "last_update_id": max_update_id, "errors": errors}


def run_dry_tests() -> dict[str, Any]:
    store = MemoryState()
    user = {"id": 123, "username": "tester"}
    chat = {"id": 999}
    result_cb = {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "from": user,
            "message": {"chat": chat},
            "data": "qc_result|test_signal_123|entered",
        },
    }
    reason_cb = {
        "update_id": 2,
        "callback_query": {
            "id": "cb2",
            "from": user,
            "message": {"chat": chat},
            "data": "qc_reason|test_signal_123",
        },
    }
    text_update = {
        "update_id": 3,
        "message": {
            "from": user,
            "chat": chat,
            "text": "因為新聞偏空，跳過",
        },
    }
    r1 = process_update(result_cb, dry_store=store)
    r2 = process_update(reason_cb, dry_store=store)
    r3 = process_update(text_update, dry_store=store)
    return {
        "status": "OK" if all(r.get("status") == "OK" for r in [r1, r2, r3]) else "ERROR",
        "mock_result_callback_processed": r1.get("processed") == "result",
        "mock_reason_callback_processed": r2.get("processed") == "reason",
        "mock_text_reason_processed": r3.get("processed") == "text_reason",
    }


def main() -> int:
    result = poll_once()
    print(json.dumps({"telegram_review_poll_once": result}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"OK", "skipped_missing_env"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
