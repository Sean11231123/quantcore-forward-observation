from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def send_message(
    text: str,
    chat_id: str | None = None,
    parse_mode: str | None = "HTML",
    message_thread_id: str | int | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _load_env()
    token = os.getenv("TG_BOT_TOKEN", "")
    target_chat_id = chat_id or os.getenv("TG_CHAT_ID", "")
    if not token or not target_chat_id:
        return {
            "status": "skipped_missing_env",
            "message_sent": False,
            "error": "TG_BOT_TOKEN or target chat_id missing",
        }

    payload_data: dict[str, Any] = {"chat_id": target_chat_id, "text": text}
    if parse_mode:
        payload_data["parse_mode"] = parse_mode
        payload_data["disable_web_page_preview"] = "true"
    if message_thread_id not in {None, ""}:
        payload_data["message_thread_id"] = str(message_thread_id)
    if reply_markup:
        payload_data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    payload = urllib.parse.urlencode(payload_data).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        ok = bool(body.get("ok"))
        return {"status": "OK" if ok else "ERROR", "message_sent": ok, "error": "" if ok else str(body)}
    except Exception as exc:
        return {"status": "ERROR", "message_sent": False, "error": str(exc)}


async def send_message_async(
    text: str,
    chat_id: str | None = None,
    parse_mode: str | None = "HTML",
    message_thread_id: str | int | None = None,
) -> dict[str, Any]:
    return send_message(text, chat_id=chat_id, parse_mode=parse_mode, message_thread_id=message_thread_id)


def send_telegram_message(message: str, parse_mode: str | None = None) -> dict[str, Any]:
    return send_message(message, parse_mode=parse_mode)


def get_updates(offset: int | None = None, timeout: int = 0) -> dict[str, Any]:
    _load_env()
    token = os.getenv("TG_BOT_TOKEN", "")
    if not token:
        return {"status": "skipped_missing_env", "updates": [], "error": "TG_BOT_TOKEN missing"}

    payload_data: dict[str, Any] = {"timeout": str(timeout)}
    if offset is not None:
        payload_data["offset"] = str(offset)
    payload = urllib.parse.urlencode(payload_data).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            return {"status": "ERROR", "updates": [], "error": str(body)}
        return {"status": "OK", "updates": body.get("result", []), "error": ""}
    except Exception as exc:
        return {"status": "ERROR", "updates": [], "error": str(exc)}


def answer_callback_query(callback_query_id: str, text: str = "") -> dict[str, Any]:
    _load_env()
    token = os.getenv("TG_BOT_TOKEN", "")
    if not token:
        return {"status": "skipped_missing_env", "answered": False, "error": "TG_BOT_TOKEN missing"}
    payload = urllib.parse.urlencode({"callback_query_id": callback_query_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        ok = bool(body.get("ok"))
        return {"status": "OK" if ok else "ERROR", "answered": ok, "error": "" if ok else str(body)}
    except Exception as exc:
        return {"status": "ERROR", "answered": False, "error": str(exc)}


if __name__ == "__main__":
    print(json.dumps(send_message("QuantCore Bot Online OK"), ensure_ascii=False, indent=2))
