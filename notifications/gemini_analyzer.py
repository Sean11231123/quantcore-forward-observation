from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


GEMINI_MODEL = "gemini-2.5-flash"
ALLOWED_RECOMMENDATIONS = {"watch_only", "cautious_watch", "high_risk_watch"}


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def _normalise_sources(grounding: dict[str, Any], parsed: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    for chunk in grounding.get("groundingChunks", []) or []:
        web = chunk.get("web") if isinstance(chunk, dict) else None
        if not web:
            continue
        uri = str(web.get("uri", "") or "")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append(
            {
                "title": str(web.get("title") or uri),
                "url": uri,
                "publisher": "",
                "published_at": "",
            }
        )

    for item in parsed.get("sources", []) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "title": str(item.get("title") or url),
                "url": url,
                "publisher": str(item.get("publisher") or ""),
                "published_at": str(item.get("published_at") or ""),
            }
        )
    return sources


def validate_leave_a_comment(comment: str) -> dict[str, bool]:
    checks = {
        "has_technical": "技術面" in comment,
        "has_entry_reason": "入場理由" in comment,
        "has_fundamental": "基本面" in comment or "新聞" in comment,
        "has_direction_impact": "基本面方向" in comment,
        "has_risk": "風險" in comment,
    }
    return checks


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _normalise_event_check(parsed: dict[str, Any]) -> dict[str, Any]:
    event = parsed.get("fundamental_event_check")
    if not isinstance(event, dict):
        event = {}

    direction = str(event.get("event_direction") or "none").lower()
    if direction not in {"bullish", "bearish", "mixed", "none"}:
        direction = "none"

    relevance = str(event.get("event_relevance") or "low").lower()
    if relevance not in {"high", "medium", "low"}:
        relevance = "low"

    return {
        "has_major_event": bool(event.get("has_major_event", False)),
        "event_direction": direction,
        "event_relevance": relevance,
        "event_reason": str(event.get("event_reason") or "目前未找到可驗證的重大基本面利多/利空。"),
    }


def _apply_no_source_policy(parsed: dict[str, Any]) -> None:
    parsed["sources"] = []
    parsed["news_summary"] = "未取得外部新聞來源，不能判斷基本面是否支持。"
    parsed["fundamental_event_check"] = {
        "has_major_event": False,
        "event_direction": "none",
        "event_relevance": "low",
        "event_reason": "目前未取得可驗證新聞來源，因此不能判斷基本面是否支持此方向。",
    }
    warnings = _as_list(parsed.get("risk_warnings"))
    if not any("新聞來源不足" in warning for warning in warnings):
        warnings.append("新聞來源不足，不應只依賴技術面。")
    parsed["risk_warnings"] = warnings


def compose_leave_a_comment(parsed: dict[str, Any]) -> str:
    event = _normalise_event_check(parsed)
    technical_summary = str(parsed.get("technical_summary") or "技術面資料不足，僅能保留原始訊號觀察。")
    news_summary = str(parsed.get("news_summary") or "目前未找到可驗證的重大基本面利多/利空。")

    entry_reasons = _as_list(parsed.get("entry_reasons"))
    if not entry_reasons:
        entry_reasons = ["此訊號由 V12_C3 forward observation 技術條件觸發，不代表高勝率或自動下單。"]

    risk_warnings = _as_list(parsed.get("risk_warnings"))
    if not risk_warnings:
        risk_warnings = ["仍需留意突發新聞、流動性變化與波動擴大風險。"]

    entry_block = "\n".join(f"- {reason}" for reason in entry_reasons)
    risk_block = "\n".join(f"- {warning}" for warning in risk_warnings)

    return (
        "【技術面】\n"
        f"{technical_summary}\n\n"
        "【入場理由】\n"
        f"{entry_block}\n\n"
        "【基本面 / 新聞】\n"
        f"{news_summary}\n\n"
        "【基本面對交易方向的影響】\n"
        f"基本面方向：{event['event_direction']}\n"
        f"相關性：{event['event_relevance']}\n"
        f"{event['event_reason']}\n\n"
        "【風險提醒】\n"
        f"{risk_block}"
    )


def _ensure_payload_schema(parsed: dict[str, Any], sources: list[dict[str, str]]) -> dict[str, Any]:
    payload = dict(parsed) if parsed else {}
    payload.setdefault("technical_summary", "")
    payload.setdefault("entry_reasons", [])
    payload.setdefault("risk_warnings", [])
    payload.setdefault("news_summary", "")
    payload["fundamental_event_check"] = _normalise_event_check(payload)
    payload.setdefault("trade_reason_with_fundamentals", "")
    payload.setdefault("confidence", 1)
    payload["sources"] = sources

    recommendation = str(payload.get("recommendation") or "watch_only")
    payload["recommendation"] = recommendation if recommendation in ALLOWED_RECOMMENDATIONS else "watch_only"

    if not sources:
        _apply_no_source_policy(payload)
    elif not payload.get("news_summary"):
        payload["news_summary"] = "Gemini 已取得外部來源，但未能產生明確新聞摘要。"

    comment = str(payload.get("leave_a_comment") or "")
    if not all(validate_leave_a_comment(comment).values()):
        comment = compose_leave_a_comment(payload)
    payload["leave_a_comment"] = comment
    return payload


def _fallback_payload(reason: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "technical_summary": "AI 分析失敗，僅保留原始技術訊號。",
        "entry_reasons": ["此訊號由 V12_C3 forward observation 技術條件觸發。"],
        "risk_warnings": ["AI 分析失敗或新聞來源不足，不應只依賴技術面。"],
        "news_summary": "未取得外部新聞來源，不能判斷基本面是否支持。",
        "fundamental_event_check": {
            "has_major_event": False,
            "event_direction": "none",
            "event_relevance": "low",
            "event_reason": reason,
        },
        "trade_reason_with_fundamentals": "AI 分析失敗，不能判斷基本面是否支持此方向。",
        "recommendation": "watch_only",
        "confidence": 1,
        "sources": [],
    }
    payload["leave_a_comment"] = compose_leave_a_comment(payload)
    return payload


def _build_prompt(test_signal: dict[str, Any]) -> str:
    symbol = str(test_signal.get("symbol", "BTC/USDT"))
    return f"""
你是 QuantCore 的 Gemini 新聞與基本面分析器。請用繁體中文分析這筆 V12 forward observation 訊號，並嘗試查詢最近 24 小時與 {symbol} 或整體 crypto market 相關的新聞與基本面事件。

必查方向：
- {symbol} crypto news last 24 hours
- {symbol} Binance announcement
- {symbol} hack exploit lawsuit unlock delisting outage
- Bitcoin crypto market news last 24 hours
- crypto market regulation ETF macro news last 24 hours

請只輸出可解析 JSON，不要 markdown，不要額外說明。JSON schema 必須完全包含：
{{
  "technical_summary": "...",
  "entry_reasons": ["...", "..."],
  "risk_warnings": ["...", "..."],
  "news_summary": "...",
  "fundamental_event_check": {{
    "has_major_event": true,
    "event_direction": "bullish/bearish/mixed/none",
    "event_relevance": "high/medium/low",
    "event_reason": "..."
  }},
  "trade_reason_with_fundamentals": "...",
  "recommendation": "watch_only/cautious_watch/high_risk_watch",
  "confidence": 1,
  "sources": [
    {{"title": "...", "url": "...", "publisher": "...", "published_at": "..."}}
  ],
  "leave_a_comment": "..."
}}

leave_a_comment 必須是繁體中文，並且必須包含以下 5 個段落標題：
【技術面】
用 1 到 2 句總結 ADX、BTC RE、volume_ratio、RSI/MACD、價格行為。

【入場理由】
說明為什麼這筆 V12 signal 觸發；只能根據 signal_data，不可誇大成高勝率訊號。

【基本面 / 新聞】
根據 grounding 搜尋結果摘要最近 24 小時事件。如果沒有重大事件，必須明確寫：「目前未找到可驗證的重大基本面利多/利空。」

【基本面對交易方向的影響】
必須包含兩行：
基本面方向：bullish / bearish / mixed / none
相關性：high / medium / low
並補一句原因。

【風險提醒】
若有重大利空要明確提醒；若來源不足，必須提醒「新聞來源不足，不應只依賴技術面」。

重要規則：
1. 不可捏造來源；sources 只能填真實可查來源。
2. 若 sources 為空，news_summary 必須寫「未取得外部新聞來源，不能判斷基本面是否支持」，fundamental_event_check.has_major_event=false，leave_a_comment 必須包含「目前未取得可驗證新聞來源」。
3. recommendation 只能是 watch_only、cautious_watch、high_risk_watch；不可寫強烈進場或上線建議。

signal_data:
{json.dumps(test_signal, ensure_ascii=False, indent=2)}
""".strip()


def analyze_signal(test_signal: dict[str, Any]) -> dict[str, Any]:
    _load_env()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        payload = _fallback_payload("GEMINI_API_KEY missing")
        return {
            "status": "skipped_missing_env",
            "uses_gemini_not_claude": True,
            "grounding_attempted": False,
            "text": json.dumps(payload, ensure_ascii=False),
            "parsed": payload,
            "sources": [],
            "leave_a_comment": payload["leave_a_comment"],
            "error": "GEMINI_API_KEY missing",
        }

    body = {
        "contents": [{"parts": [{"text": _build_prompt(test_signal)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidate = data["candidates"][0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        parsed = _extract_json(text)
        grounding = candidate.get("groundingMetadata", {})
        sources = _normalise_sources(grounding, parsed)

        if not parsed:
            parsed = _fallback_payload("Gemini JSON parse failed")
            sources = []

        payload = _ensure_payload_schema(parsed, sources)
        return {
            "status": "OK",
            "uses_gemini_not_claude": True,
            "grounding_attempted": True,
            "text": json.dumps(payload, ensure_ascii=False),
            "parsed": payload,
            "sources": payload.get("sources", []),
            "leave_a_comment": payload.get("leave_a_comment", ""),
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        payload = _fallback_payload(f"grounding_unavailable HTTP {exc.code}: {exc.reason}")
        return {
            "status": "ERROR",
            "uses_gemini_not_claude": True,
            "grounding_attempted": True,
            "text": json.dumps(payload, ensure_ascii=False),
            "parsed": payload,
            "sources": [],
            "leave_a_comment": payload["leave_a_comment"],
            "error": f"HTTP Error {exc.code}: {exc.reason}",
        }
    except Exception as exc:
        payload = _fallback_payload(str(exc))
        return {
            "status": "ERROR",
            "uses_gemini_not_claude": True,
            "grounding_attempted": True,
            "text": json.dumps(payload, ensure_ascii=False),
            "parsed": payload,
            "sources": [],
            "leave_a_comment": payload["leave_a_comment"],
            "error": str(exc),
        }


if __name__ == "__main__":
    sample = {
        "strategy_name": "V12_C3",
        "strategy_version": "15m_clean",
        "symbol": "BTC/USDT",
        "side": "buy",
    }
    print(json.dumps(analyze_signal(sample), ensure_ascii=False, indent=2))
