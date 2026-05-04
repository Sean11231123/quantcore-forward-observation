from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


SPREADSHEET_ID_ENV = "GOOGLE_SHEET_ID"
SERVICE_ACCOUNT_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
RUNTIME_ERROR_PATH = os.path.join("logs", "runtime_errors.log")

V12_SHEET_NAME = "v12_signals"
MANUAL_REVIEW_SHEET_NAME = "manual_review"

V12_FIELDS = [
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
    "telegram_sent",
    "telegram_error",
    "gemini_status",
    "sources_count",
]

MANUAL_REVIEW_FIELDS = [
    "signal_id",
    "manual_decision",
    "manual_reason",
    "actual_entry_price",
    "actual_exit_price",
    "actual_result",
    "actual_pnl_pct",
    "reviewed_at",
    "reviewed_by",
]

BOT_STATE_SHEET_NAME = "bot_state"
BOT_STATE_FIELDS = [
    "key",
    "value",
    "updated_at",
]


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def log_runtime_error(source: str, error: str) -> None:
    os.makedirs(os.path.dirname(RUNTIME_ERROR_PATH), exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(RUNTIME_ERROR_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{timestamp}\t{source}\t{error}\n")


def _env_status() -> tuple[str, str]:
    _load_env()
    spreadsheet_id = os.getenv(SPREADSHEET_ID_ENV, "")
    service_account_json = os.getenv(SERVICE_ACCOUNT_ENV, "")
    if not spreadsheet_id or not service_account_json:
        return "", "GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON missing"
    return spreadsheet_id, ""


def _build_service():
    spreadsheet_id, error = _env_status()
    if error:
        return None, "", {"status": "skipped_missing_env", "error": error}

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        return None, "", {"status": "skipped_missing_dependency", "error": str(exc)}

    try:
        info = json.loads(os.getenv(SERVICE_ACCOUNT_ENV, ""))
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return service, spreadsheet_id, {"status": "OK", "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_auth", str(exc))
        return None, "", {"status": "ERROR", "error": str(exc)}


def _sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return {sheet["properties"]["title"] for sheet in metadata.get("sheets", [])}


def _ensure_sheet(service, spreadsheet_id: str, title: str, fields: list[str]) -> None:
    titles = _sheet_titles(service, spreadsheet_id)
    if title not in titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!1:1",
    ).execute()
    values = result.get("values", [])
    if not values:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{title}!A1",
            valueInputOption="RAW",
            body={"values": [fields]},
        ).execute()
    elif values[0] != fields:
        current = list(values[0])
        changed = False
        for field in fields:
            if field not in current:
                current.append(field)
                changed = True
        if changed:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{title}!A1",
                valueInputOption="RAW",
                body={"values": [current]},
            ).execute()


def _get_rows(service, spreadsheet_id: str, title: str, fields: list[str]) -> tuple[list[str], list[list[str]]]:
    _ensure_sheet(service, spreadsheet_id, title, fields)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A:ZZ",
    ).execute()
    values = result.get("values", [])
    if not values:
        return fields, []
    return values[0], values[1:]


def _row_dict(header: list[str], row: list[str]) -> dict[str, str]:
    padded = row + [""] * max(len(header) - len(row), 0)
    return {key: padded[idx] for idx, key in enumerate(header)}


def _update_row(service, spreadsheet_id: str, title: str, row_number: int, header: list[str], data: dict[str, Any]) -> None:
    values = [str(data.get(field, "")) for field in header]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A{row_number}",
        valueInputOption="RAW",
        body={"values": [values]},
    ).execute()


def signal_exists(signal_id: str) -> dict[str, Any]:
    if not signal_id:
        return {"status": "ERROR", "exists": False, "error": "signal_id missing"}

    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "exists": False, "error": status.get("error", "")}

    try:
        _ensure_sheet(service, spreadsheet_id, V12_SHEET_NAME, V12_FIELDS)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{V12_SHEET_NAME}!A:A",
        ).execute()
        values = result.get("values", [])
        ids = {row[0] for row in values[1:] if row}
        return {"status": "OK", "exists": signal_id in ids, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_signal_exists", str(exc))
        return {"status": "ERROR", "exists": False, "error": str(exc)}


def append_signal(signal: dict[str, Any]) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id", ""))
    if not signal_id:
        return {"status": "ERROR", "inserted": False, "deduped": False, "error": "signal_id missing"}

    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {
            "status": status["status"],
            "inserted": False,
            "deduped": False,
            "error": status.get("error", ""),
        }

    try:
        _ensure_sheet(service, spreadsheet_id, V12_SHEET_NAME, V12_FIELDS)
        _ensure_sheet(service, spreadsheet_id, MANUAL_REVIEW_SHEET_NAME, MANUAL_REVIEW_FIELDS)

        exists = signal_exists(signal_id)
        if exists.get("exists"):
            return {"status": "OK", "inserted": False, "deduped": True, "error": ""}

        row = [signal.get(field, "") for field in V12_FIELDS]
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{V12_SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return {"status": "OK", "inserted": True, "deduped": False, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_append_signal", str(exc))
        return {"status": "ERROR", "inserted": False, "deduped": False, "error": str(exc)}


def get_signal(signal_id: str) -> dict[str, Any]:
    if not signal_id:
        return {"status": "ERROR", "found": False, "signal": {}, "error": "signal_id missing"}

    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "found": False, "signal": {}, "error": status.get("error", "")}

    try:
        header, rows = _get_rows(service, spreadsheet_id, V12_SHEET_NAME, V12_FIELDS)
        for row in rows:
            data = _row_dict(header, row)
            if data.get("signal_id") == signal_id:
                return {"status": "OK", "found": True, "signal": data, "error": ""}
        return {"status": "OK", "found": False, "signal": {}, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_get_signal", str(exc))
        return {"status": "ERROR", "found": False, "signal": {}, "error": str(exc)}


def get_bot_state(key: str) -> dict[str, Any]:
    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "value": "", "error": status.get("error", "")}
    try:
        header, rows = _get_rows(service, spreadsheet_id, BOT_STATE_SHEET_NAME, BOT_STATE_FIELDS)
        for row in rows:
            data = _row_dict(header, row)
            if data.get("key") == key:
                return {"status": "OK", "value": data.get("value", ""), "error": ""}
        return {"status": "OK", "value": "", "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_get_bot_state", str(exc))
        return {"status": "ERROR", "value": "", "error": str(exc)}


def set_bot_state(key: str, value: str) -> dict[str, Any]:
    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "updated": False, "error": status.get("error", "")}
    try:
        header, rows = _get_rows(service, spreadsheet_id, BOT_STATE_SHEET_NAME, BOT_STATE_FIELDS)
        data = {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}
        for idx, row in enumerate(rows, start=2):
            if _row_dict(header, row).get("key") == key:
                _update_row(service, spreadsheet_id, BOT_STATE_SHEET_NAME, idx, header, data)
                return {"status": "OK", "updated": True, "inserted": False, "error": ""}
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{BOT_STATE_SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[data.get(field, "") for field in header]]},
        ).execute()
        return {"status": "OK", "updated": True, "inserted": True, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_set_bot_state", str(exc))
        return {"status": "ERROR", "updated": False, "error": str(exc)}


def delete_bot_state(key: str) -> dict[str, Any]:
    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "deleted": False, "error": status.get("error", "")}
    try:
        header, rows = _get_rows(service, spreadsheet_id, BOT_STATE_SHEET_NAME, BOT_STATE_FIELDS)
        for idx, row in enumerate(rows, start=2):
            if _row_dict(header, row).get("key") == key:
                empty = {field: "" for field in header}
                _update_row(service, spreadsheet_id, BOT_STATE_SHEET_NAME, idx, header, empty)
                return {"status": "OK", "deleted": True, "error": ""}
        return {"status": "OK", "deleted": False, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_delete_bot_state", str(exc))
        return {"status": "ERROR", "deleted": False, "error": str(exc)}


def upsert_manual_review(signal_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not signal_id:
        return {"status": "ERROR", "upserted": False, "error": "signal_id missing"}

    service, spreadsheet_id, status = _build_service()
    if status["status"] != "OK":
        return {"status": status["status"], "upserted": False, "error": status.get("error", "")}
    try:
        header, rows = _get_rows(service, spreadsheet_id, MANUAL_REVIEW_SHEET_NAME, MANUAL_REVIEW_FIELDS)
        now = datetime.now(timezone.utc).isoformat()
        updates = {"signal_id": signal_id, "reviewed_at": now}
        updates.update(fields)

        for idx, row in enumerate(rows, start=2):
            data = _row_dict(header, row)
            if data.get("signal_id") == signal_id:
                data.update({k: v for k, v in updates.items() if v is not None})
                _update_row(service, spreadsheet_id, MANUAL_REVIEW_SHEET_NAME, idx, header, data)
                return {"status": "OK", "upserted": True, "inserted": False, "error": ""}

        row_data = {field: "" for field in header}
        row_data.update(updates)
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{MANUAL_REVIEW_SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[row_data.get(field, "") for field in header]]},
        ).execute()
        return {"status": "OK", "upserted": True, "inserted": True, "error": ""}
    except Exception as exc:
        log_runtime_error("google_sheets_upsert_manual_review", str(exc))
        return {"status": "ERROR", "upserted": False, "error": str(exc)}
