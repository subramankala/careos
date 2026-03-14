from __future__ import annotations

import json
import re
from difflib import get_close_matches
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from careos.settings import settings

ALLOWED_INTENTS = {
    "caregiver_dashboard",
    "schedule_today",
    "schedule_tomorrow",
    "status",
    "critical_missed_today",
    "med_count_today",
    "set_critical_only_today",
    "done",
    "skip",
    "delay",
    "clarify",
}


@dataclass
class IntentParseResult:
    intent: str
    args: dict = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _has_dashboardish_token(tokens: list[str]) -> bool:
    if "dashboard" in tokens:
        return True
    return bool(get_close_matches("dashboard", tokens, n=1, cutoff=0.78))


def _looks_like_dashboard_request(text: str) -> bool:
    lower = text.strip().lower()
    tokens = _tokens(lower)
    if not tokens:
        return False
    if _has_dashboardish_token(tokens):
        return True
    phrases = {
        "patient summary",
        "caregiver summary",
        "care summary",
        "patient dashboard",
        "caregiver dashboard",
        "patient report",
        "care report",
        "patient overview",
        "care overview",
        "my patient summary",
    }
    if any(phrase in lower for phrase in phrases):
        return True
    summary_words = {"summary", "progress", "overview", "report", "dashboard"}
    actor_words = {"patient", "caregiver", "care"}
    request_words = {"show", "open", "view", "give", "need", "want", "check", "see"}
    possession_words = {"my"}
    if summary_words.intersection(tokens) and actor_words.intersection(tokens):
        return True
    if summary_words.intersection(tokens) and possession_words.intersection(tokens) and "patient" in tokens:
        return True
    if "status" in tokens and actor_words.intersection(tokens) and request_words.intersection(tokens):
        return True
    if {"how", "doing"}.intersection(tokens) == {"how", "doing"} and (
        actor_words.intersection(tokens) or {"my", "patient"}.intersection(tokens) == {"my", "patient"}
    ):
        return True
    if {"check", "patient"}.intersection(tokens) == {"check", "patient"}:
        return True
    return False


def _looks_like_create_request(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return False
    create_verbs = {"add", "create", "plan", "put", "remind", "book"}
    if any(verb in _tokens(lower) for verb in create_verbs):
        return True
    return lower.startswith("schedule ") and any(
        keyword in lower for keyword in {"appointment", "visit", "consult", "reminder", "med", "medication"}
    )


def _pre_llm_read_intent(text: str) -> IntentParseResult | None:
    lower = text.strip().lower()
    if not lower:
        return None
    if _looks_like_create_request(lower):
        return None
    tokens = _tokens(lower)
    if "tomorrow" in lower:
        return IntentParseResult(intent="schedule_tomorrow", confidence=0.93, rationale="schedule_tomorrow_pre_llm")
    schedule_phrases = {
        "today schedule",
        "today's schedule",
        "todays schedule",
        "what is my schedule today",
        "what's my schedule today",
        "what is today's schedule",
        "what's today's schedule",
        "what do i have today",
    }
    if lower == "schedule" or any(phrase in lower for phrase in schedule_phrases):
        return IntentParseResult(intent="schedule_today", confidence=0.93, rationale="schedule_today_pre_llm")
    if "schedule" in tokens and "today" in tokens:
        return IntentParseResult(intent="schedule_today", confidence=0.91, rationale="schedule_today_tokens_pre_llm")
    if "status" in tokens or "adherence" in tokens:
        return IntentParseResult(intent="status", confidence=0.9, rationale="status_pre_llm")
    if ("how many" in lower or "count" in lower or "total" in lower) and (
        "med" in lower or "medication" in lower
    ):
        return IntentParseResult(intent="med_count_today", confidence=0.9, rationale="med_count_pre_llm")
    if "critical" in lower and ("missed" in lower or "miss any" in lower or "did i miss" in lower):
        return IntentParseResult(intent="critical_missed_today", confidence=0.9, rationale="critical_missed_pre_llm")
    return None


def _rule_parse(text: str) -> IntentParseResult:
    lower = text.strip().lower()
    if not lower:
        return IntentParseResult(intent="clarify", confidence=0.1, rationale="empty_text")
    if _looks_like_dashboard_request(lower):
        return IntentParseResult(intent="caregiver_dashboard", confidence=0.9, rationale="dashboard_request")
    if _looks_like_create_request(lower):
        return IntentParseResult(intent="clarify", confidence=0.35, rationale="create_request_deferred")
    if "tomorrow" in lower:
        return IntentParseResult(intent="schedule_tomorrow", confidence=0.85, rationale="contains_tomorrow")
    if "schedule" in lower or "pending" in lower or "left today" in lower:
        return IntentParseResult(intent="schedule_today", confidence=0.82, rationale="schedule_keyword")
    if "status" in lower or "adherence" in lower:
        return IntentParseResult(intent="status", confidence=0.82, rationale="status_keyword")
    if ("how many" in lower or "count" in lower or "total" in lower) and (
        "med" in lower or "medication" in lower
    ):
        return IntentParseResult(intent="med_count_today", confidence=0.84, rationale="med_count_phrase")
    if "critical" in lower and (
        "missed" in lower
        or "miss any" in lower
        or "did i miss" in lower
        or "due" in lower
    ):
        return IntentParseResult(intent="critical_missed_today", confidence=0.84, rationale="critical_missed_phrase")
    if (
        ("only critical" in lower or "critical reminders" in lower or "send critical" in lower)
        and ("today" in lower or "for today" in lower)
    ):
        return IntentParseResult(intent="set_critical_only_today", confidence=0.86, rationale="critical_only_today_phrase")
    if "critical reminders" in lower and "only" in lower:
        return IntentParseResult(intent="set_critical_only_today", confidence=0.84, rationale="critical_only_phrase")
    done_match = re.search(r"\b(?:done|mark)\s+(\d+)\b", lower)
    if done_match:
        return IntentParseResult(intent="done", args={"item_no": int(done_match.group(1))}, confidence=0.88, rationale="done_item_no")
    skip_match = re.search(r"\bskip\s+(\d+)\b", lower)
    if skip_match:
        return IntentParseResult(intent="skip", args={"item_no": int(skip_match.group(1))}, confidence=0.88, rationale="skip_item_no")
    delay_match = re.search(r"\b(?:delay|snooze)\s+(\d+)\s+(\d+)\b", lower)
    if delay_match:
        return IntentParseResult(
            intent="delay",
            args={"item_no": int(delay_match.group(1)), "minutes": int(delay_match.group(2))},
            confidence=0.88,
            rationale="delay_item_minutes",
        )
    return IntentParseResult(intent="clarify", confidence=0.3, rationale="rule_no_match")


def _llm_parse(text: str, context: dict, today: dict, status: dict) -> IntentParseResult | None:
    if not settings.openai_api_key:
        return None
    payload = {
        "text": text,
        "context": context,
        "today": today,
        "status": status,
        "allowed_intents": sorted(ALLOWED_INTENTS),
        "now_utc": datetime.now(UTC).isoformat(),
    }
    system = (
        "You are an intent parser. Return JSON only with fields: intent, args, confidence, rationale. "
        "intent must be one of allowed_intents. confidence must be 0..1."
    )
    req_payload = {
        "model": settings.openai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ],
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        method="POST",
        data=json.dumps(req_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.openai_api_key}"},
    )
    try:
        with urlopen(req, timeout=max(getattr(settings, "openai_timeout_seconds", 15), 1)) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError, TimeoutError):
        return None
    try:
        raw = body["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        intent = str(parsed.get("intent", "")).strip()
        if intent not in ALLOWED_INTENTS:
            return None
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        args = parsed.get("args") or {}
        rationale = str(parsed.get("rationale", "")).strip()
        return IntentParseResult(intent=intent, args=dict(args), confidence=confidence, rationale=rationale)
    except Exception:
        return None


def parse_intent(text: str, *, context: dict, today: dict, status: dict) -> IntentParseResult:
    if _looks_like_dashboard_request(text):
        return IntentParseResult(intent="caregiver_dashboard", confidence=0.95, rationale="dashboard_request_pre_llm")
    read_intent = _pre_llm_read_intent(text)
    if read_intent is not None:
        return read_intent
    llm = _llm_parse(text, context, today, status)
    threshold = float(getattr(settings, "gateway_intent_min_confidence", 0.72))
    if llm is not None:
        if llm.confidence >= threshold:
            return llm
        return IntentParseResult(intent="clarify", confidence=llm.confidence, rationale=f"low_confidence:{llm.rationale}")
    return _rule_parse(text)
