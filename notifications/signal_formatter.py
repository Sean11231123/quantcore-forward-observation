from __future__ import annotations

import html
import json
import re
from typing import Any


HEADING_ENTRY = "\u3010\u5165\u5834\u7406\u7531\u3011"
HEADING_TECH = "\u3010\u6280\u8853\u9762\u3011"
NO_VERIFIED_SOURCE = "\u672a\u53d6\u5f97\u53ef\u9a57\u8b49\u5916\u90e8\u4f86\u6e90"


def _value(signal_data: dict[str, Any], key: str, default: str = "-") -> str:
    value = signal_data.get(key, default)
    if value is None or value == "":
        return default
    return html.escape(str(value))


def _source_items(signal_data: dict[str, Any]) -> list[dict[str, str]]:
    raw = signal_data.get("news_sources") or "[]"
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _short_comment(signal_data: dict[str, Any]) -> str:
    comment = str(signal_data.get("leave_a_comment") or "")
    if not comment:
        return "Gemini comment unavailable."
    first_section = comment.split(HEADING_ENTRY, 1)[0]
    return _plain(first_section.replace(HEADING_TECH, ""))[:220] or _plain(comment)[:220]


def _callback_signal_id(signal_data: dict[str, Any]) -> str:
    return str(signal_data.get("signal_id") or "")[:32]


def build_review_keyboard(signal_data: dict[str, Any]) -> dict[str, Any]:
    signal_id = _callback_signal_id(signal_data)
    return {
        "inline_keyboard": [
            [
                {"text": "\u2705 \u9032\u5834", "callback_data": f"qc_result|{signal_id}|entered"},
                {"text": "\u23ed \u8df3\u904e", "callback_data": f"qc_result|{signal_id}|skipped"},
                {"text": "\ud83d\udc40 \u6c92\u770b\u5230", "callback_data": f"qc_result|{signal_id}|missed"},
            ],
            [
                {"text": "\ud83d\udcdd \u88dc\u5145\u539f\u56e0", "callback_data": f"qc_reason|{signal_id}"},
                {"text": "\ud83d\udcc4 \u5b8c\u6574\u5206\u6790", "callback_data": f"qc_detail|{signal_id}"},
            ],
        ]
    }


def format_signal_message(signal_data: dict[str, Any], analysis: dict[str, Any] | None = None) -> str:
    """Short primary Telegram message."""
    side = str(signal_data.get("side", "")).lower()
    side_label = "LONG" if side in {"buy", "long"} else str(signal_data.get("side", "-"))
    sources_count = len(_source_items(signal_data))
    summary = html.escape(_short_comment(signal_data))

    message = "\n".join(
        [
            f"<b>V12_C3 15m_clean</b> | {_value(signal_data, 'symbol')} | {html.escape(side_label)}",
            "Forward Observation (no auto order)",
            "",
            f"Entry: {_value(signal_data, 'entry_price')} | SL: {_value(signal_data, 'stop_loss')} | TP: {_value(signal_data, 'take_profit')}",
            f"ADX: {_value(signal_data, 'adx_entry_tf')} / {_value(signal_data, 'adx_confirm_tf')} | BTC RE: {_value(signal_data, 'btc_re')}",
            f"Vol: {_value(signal_data, 'volume_ratio')}x | RSI14: {_value(signal_data, 'rsi_14')} | MACD Hist: {_value(signal_data, 'macd_hist')}",
            f"Regime: {_value(signal_data, 'regime')} | executed={_value(signal_data, 'executed')}",
            "",
            f"Gemini: {summary}",
            f"Sources: {sources_count}",
            f"Time: {_value(signal_data, 'signal_timestamp')} UTC",
        ]
    )
    return message[:1800]


def format_signal_comment(signal_data: dict[str, Any], max_sources: int = 5) -> str:
    """Detailed Gemini comment for discussion/comment chat."""
    comment = html.escape(str(signal_data.get("leave_a_comment") or "Gemini comment unavailable."))
    sources = _source_items(signal_data)[:max_sources]
    if sources:
        lines = []
        for idx, source in enumerate(sources, start=1):
            title = html.escape(str(source.get("title") or source.get("url") or "source"))
            url = html.escape(str(source.get("url") or ""))
            lines.append(f'{idx}. <a href="{url}">{title}</a>' if url else f"{idx}. {title}")
        source_block = "\n".join(lines)
    else:
        source_block = NO_VERIFIED_SOURCE

    message = "\n".join(
        [
            f"<b>Gemini Detail</b> | {_value(signal_data, 'symbol')} | {_value(signal_data, 'signal_id')}",
            "",
            comment,
            "",
            "<b>Sources</b>",
            source_block,
        ]
    )
    return message[:3900]
