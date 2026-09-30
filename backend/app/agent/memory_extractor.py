"""Automatic memory extraction: after every analysis, decide what is worth remembering.

Groq distills the incident + analysis into a few short, durable knowledge items. Only those
items (never the raw incident text, logs or conversation) are retained in Hindsight.
"""

import logging
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.groq.client import GroqError, chat_json
from app.redaction import redact
from app.schemas import AutoMemoryItem, IncidentAnalysis, IncidentInput, RecallResult

log = logging.getLogger(__name__)

CATEGORIES = {
    "root_cause",
    "resolution",
    "diagnostic_finding",
    "incident_pattern",
    "service_knowledge",
    "configuration_lesson",
    "team_instruction",
}

SYSTEM_PROMPT = """You curate the long-term memory of an SRE incident-response agent.
Given one incident and its analysis, decide what is worth remembering for FUTURE incident investigations.

Keep only durable, reusable knowledge, for example:
- root_cause: the most likely root cause (it is a hypothesis unless the input says it is confirmed)
- resolution: a fix/remediation that is recommended or known to work
- diagnostic_finding: an important signal, error signature or metric that pointed to the cause
- incident_pattern: a recurring pattern (e.g. "latency spikes on X after traffic increases")
- service_knowledge: technical facts about the service/dependencies (e.g. "payment-api uses a Redis pool of 150")
- configuration_lesson: a configuration-related lesson (limits, pool sizes, timeouts, flags)
- team_instruction: ONLY a standing rule/policy the user explicitly wrote in "User instructions"
  (e.g. "never restart the primary DB during business hours"). If the user instructions contain
  such a rule you MUST store it, quoted faithfully. Your own recommendations are never
  team_instruction. One-off formatting or answer-style requests (e.g. "answer in 3 bullets",
  "be brief") are temporary: do NOT store them.

Response-style preferences (summary endings, language, format, level of detail) are handled by a
separate preference memory: never store them as incident knowledge.

This incident is NOT resolved yet: phrase root_cause and resolution items as suspicions or
recommendations ("suspected", "recommended"), never as established facts.

Do NOT store: raw logs or whole incident text, conversation messages, UI events, temporary
instructions, generic advice that applies to any system, anything already listed under
ALREADY IN MEMORY, or sensitive data (credentials, tokens, keys, passwords, personal data,
emails, customer identifiers). Each item must be one self-contained sentence that names the
service. Prefer 0-5 items. It is fine to store nothing.

Respond with a JSON object:
{
  "worth_remembering": boolean,
  "reason": string,
  "likely_root_cause": string,   // short, "" if unknown
  "recommended_fix": string,     // short, "" if unknown
  "memories": [{"category": string, "content": string}]
}"""


class _Extraction(BaseModel):
    worth_remembering: bool = False
    reason: str = ""
    likely_root_cause: str = ""
    recommended_fix: str = ""
    memories: list[AutoMemoryItem] = Field(default_factory=list)

    @field_validator("memories", mode="before")
    @classmethod
    def keep_known_categories(cls, v: object) -> list:
        items = v if isinstance(v, list) else []
        return [
            i for i in items
            if isinstance(i, dict) and i.get("category") in CATEGORIES and str(i.get("content", "")).strip()
        ]


# Analysis-time root causes and fixes are hypotheses; label them so recall never treats them as facts.
_UNCONFIRMED_PREFIX = {
    "root_cause": "Suspected root cause (unconfirmed):",
    "resolution": "Recommended fix (unconfirmed):",
}


# Near-duplicate threshold (Jaccard similarity of word sets) against memory that already exists.
DUPLICATE_SIMILARITY = 0.8
MAX_ITEMS = 6
_LOG_LINE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}\b|\[?(ERROR|WARN|WARNING|INFO|DEBUG|FATAL|TRACE)\b)")


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_near_duplicate(candidate: str, existing: list[str]) -> bool:
    words = set(candidate.split())
    for other in existing:
        other_words = set(other.split())
        union = words | other_words
        if union and len(words & other_words) / len(union) >= DUPLICATE_SIMILARITY:
            return True
    return False


def looks_like_raw_log(content: str, error_logs: str) -> bool:
    """Raw log lines (or long verbatim copies of the submitted logs) are not durable knowledge."""
    if _LOG_LINE.match(content):
        return True
    return any(len(chunk) >= 120 and chunk in error_logs for chunk in (content[:160], content[-160:]))


def _already_known(recall: RecallResult) -> list[str]:
    facts = [f.text for m in recall.memories for f in m.facts] + [f.text for f in recall.other_facts]
    return facts[:25]


def _build_input(incident: IncidentInput, analysis: IncidentAnalysis, recall: RecallResult) -> str:
    known = _already_known(recall)
    causes = "\n".join(f"- {c.cause} ({c.likelihood}): {c.evidence}" for c in analysis.possible_causes)
    return f"""INCIDENT:
Title: {incident.title}
Service: {incident.service}
Environment: {incident.environment}
Severity: {incident.severity.value}
Symptoms: {incident.symptoms}
Error logs: {incident.error_logs[:1500] or '(none)'}
Recent changes: {incident.recent_changes or '(none)'}
User instructions given with this incident: {incident.additional_instructions or '(none)'}

ANALYSIS (not yet confirmed by the user):
Summary: {analysis.summary}
Possible causes:
{causes or '(none)'}
Recommended checks: {'; '.join(analysis.recommended_checks) or '(none)'}
Recommended solution: {analysis.recommended_solution}
Confidence: {analysis.confidence}

ALREADY IN MEMORY (do not repeat):
{chr(10).join('- ' + k for k in known) if known else '(nothing yet)'}

Return only the JSON object."""


async def extract_memories(
    incident: IncidentInput, analysis: IncidentAnalysis, recall: RecallResult
) -> tuple[list[AutoMemoryItem], str, str, str]:
    """Returns (items, reason, likely_root_cause, recommended_fix). Raises GroqError on failure."""
    prompt = _build_input(incident, analysis, recall)
    effort = get_settings().groq_aux_reasoning_effort
    try:
        result = await chat_json(SYSTEM_PROMPT, prompt, reasoning_effort=effort)
    except GroqError as exc:
        if not exc.retryable:
            raise
        result = await chat_json(SYSTEM_PROMPT, prompt, reasoning_effort=effort)  # one retry on malformed output
    try:
        ext = _Extraction.model_validate(result.data)
    except ValidationError as exc:
        raise GroqError(f"memory extraction returned invalid data: {exc.error_count()} errors") from exc
    if not ext.worth_remembering:
        return [], ext.reason or "Nothing new worth remembering.", "", ""
    return (
        filter_items(incident, ext.memories, recall),
        ext.reason,
        redact(ext.likely_root_cause)[:300],
        redact(ext.recommended_fix)[:300],
    )


def filter_items(incident: IncidentInput, candidates: list[AutoMemoryItem], recall: RecallResult) -> list[AutoMemoryItem]:
    """Memory-quality gate: redact, label hypotheses, drop raw logs, model advice posing as team rules,
    and exact or near duplicates (within the batch or of what memory already holds)."""
    known = [_normalize(k) for k in _already_known(recall)]
    has_instructions = bool(incident.additional_instructions.strip())
    items: list[AutoMemoryItem] = []
    kept: list[str] = []
    for item in candidates[:MAX_ITEMS]:
        content = redact(item.content)[:500]
        if item.category == "team_instruction" and not has_instructions:
            continue  # the user gave no instructions; this is the model's own advice
        if looks_like_raw_log(content, incident.error_logs):
            continue
        if item.category in _UNCONFIRMED_PREFIX and "unconfirmed" not in content.lower():
            content = f"{_UNCONFIRMED_PREFIX[item.category]} {content}"
        key = _normalize(content)
        if len(key) < 12 or is_near_duplicate(key, kept + known):
            continue
        kept.append(key)
        items.append(AutoMemoryItem(category=item.category, content=content))
    return items
