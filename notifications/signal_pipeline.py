from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from logs.forward_signal_logger import log_signal, signal_exists as csv_signal_exists
from logs.google_sheets_logger import append_signal as append_signal_to_sheet
from logs.google_sheets_logger import log_runtime_error, signal_exists as sheet_signal_exists
from notifications.gemini_analyzer import analyze_signal
from notifications.signal_formatter import build_review_keyboard, format_signal_comment, format_signal_message
from notifications.telegram_bot import send_message


def _ensure_signal_defaults(signal_data: dict[str, Any]) -> None:
    signal_data.setdefault("signal_id", "")
    signal_data.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    signal_data.setdefault("executed", False)
    signal_data.setdefault("result", "")
    signal_data.setdefault("exit_price", "")
    signal_data.setdefault("exit_type", "")
    signal_data.setdefault("pnl_pct", "")
    signal_data.setdefault("leave_a_comment", "")
    signal_data.setdefault("news_sources", "")


def _fallback_comment(error: str) -> str:
    return (
        "【技術面】\n"
        "AI 分析失敗，僅保留原始 V12 技術訊號。\n\n"
        "【入場理由】\n"
        "- 此訊號由 V12_C3 forward observation 技術條件觸發，不代表自動下單。\n\n"
        "【基本面 / 新聞】\n"
        "未取得外部新聞來源，不能判斷基本面是否支持。\n\n"
        "【基本面對交易方向的影響】\n"
        "基本面方向：none\n"
        "相關性：low\n"
        "AI 分析失敗或來源不可用，因此不能判斷基本面方向。\n\n"
        "【風險提醒】\n"
        f"- AI 分析失敗，新聞來源不足，不應只依賴技術面。error={error}"
    )


async def handle_v12_signal(signal_data: dict[str, Any]) -> dict[str, Any]:
    _ensure_signal_defaults(signal_data)
    signal_id = str(signal_data.get("signal_id", ""))
    if not signal_id:
        return {"status": "ERROR", "error": "signal_id missing"}

    if csv_signal_exists(signal_id):
        return {
            "status": "OK",
            "duplicate_skipped": True,
            "duplicate_source": "csv",
            "gemini_status": "skipped_duplicate",
            "sources_count": 0,
            "logger_written": False,
            "google_sheet_written": False,
            "telegram_sent": False,
            "comment_sent": False,
        }

    sheet_exists = sheet_signal_exists(signal_id)
    if sheet_exists.get("exists"):
        return {
            "status": "OK",
            "duplicate_skipped": True,
            "duplicate_source": "google_sheet",
            "gemini_status": "skipped_duplicate",
            "sources_count": 0,
            "logger_written": False,
            "google_sheet_written": False,
            "telegram_sent": False,
            "comment_sent": False,
        }
    if sheet_exists.get("status") == "ERROR":
        log_runtime_error("signal_pipeline_sheet_precheck", sheet_exists.get("error", "unknown"))

    analysis = analyze_signal(signal_data)
    gemini_status = analysis.get("status", "ERROR")
    gemini_error = analysis.get("error", "")
    sources = analysis.get("sources", []) or []

    if gemini_status == "OK":
        signal_data["leave_a_comment"] = analysis.get("leave_a_comment") or ""
        signal_data["news_sources"] = json.dumps(sources, ensure_ascii=False)
    else:
        signal_data["leave_a_comment"] = _fallback_comment(gemini_error or gemini_status)
        signal_data["news_sources"] = ""

    signal_data["gemini_status"] = gemini_status
    signal_data["sources_count"] = len(sources)
    signal_data["telegram_sent"] = ""
    signal_data["telegram_error"] = ""

    logger_result = log_signal(signal_data)
    sheet_result = append_signal_to_sheet(signal_data)
    if sheet_result.get("status") == "ERROR":
        log_runtime_error("signal_pipeline_sheet_append", sheet_result.get("error", "unknown"))

    comment_chat_id = os.getenv("TG_COMMENT_CHAT_ID", "")
    comment_thread_id = os.getenv("TG_COMMENT_THREAD_ID", "")
    main_message = format_signal_message(signal_data, analysis)
    if not comment_chat_id:
        main_message = (main_message + "\n\n" + format_signal_comment(signal_data))[:3900]
    telegram_result = send_message(main_message, parse_mode="HTML", reply_markup=build_review_keyboard(signal_data))

    comment_result: dict[str, Any]
    if comment_chat_id:
        comment_result = send_message(
            format_signal_comment(signal_data),
            chat_id=comment_chat_id,
            parse_mode="HTML",
            message_thread_id=comment_thread_id or None,
        )
    else:
        comment_result = {"status": "skipped_missing_env", "message_sent": False, "error": "TG_COMMENT_CHAT_ID missing"}

    return {
        "status": "OK" if logger_result.get("status") == "OK" else "ERROR",
        "duplicate_skipped": False,
        "gemini_status": gemini_status,
        "gemini_error": gemini_error,
        "sources_count": len(sources),
        "logger_written": bool(logger_result.get("inserted")),
        "logger_duplicate_skipped": bool(logger_result.get("deduped")),
        "logger_error": logger_result.get("error", ""),
        "google_sheet_status": sheet_result.get("status"),
        "google_sheet_written": bool(sheet_result.get("inserted")),
        "google_sheet_duplicate_skipped": bool(sheet_result.get("deduped")),
        "google_sheet_error": sheet_result.get("error", ""),
        "telegram_status": telegram_result.get("status"),
        "telegram_sent": bool(telegram_result.get("message_sent")),
        "telegram_error": telegram_result.get("error", ""),
        "comment_status": comment_result.get("status"),
        "comment_sent": bool(comment_result.get("message_sent")),
        "comment_error": comment_result.get("error", ""),
    }
