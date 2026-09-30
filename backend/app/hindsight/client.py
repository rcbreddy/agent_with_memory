"""Hindsight: the persistent agent memory for incident response (official `hindsight-client` SDK).

Each user has a private memory bank. Historical incident memory held here is *evidence* for the
reasoning step, never the answer itself.

- recall_incident_memory(): semantic RECALL of historical incidents relevant to a new production
  incident, ranked by service, relevance and trust (confirmed resolution > unconfirmed hypothesis)
- retain_incident_resolution(): RETAIN an engineer-confirmed resolution (confirmed knowledge)
- retain_incident_knowledge(): RETAIN automatically extracted analysis knowledge (unconfirmed hypotheses)
"""

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from hindsight_client import Hindsight

from app.config import get_settings
from app.redaction import redact
from app.schemas import (
    AutoMemoryItem,
    HindsightStatus,
    IncidentInput,
    RecallResult,
    RecalledFact,
    RecalledIncident,
    ResolutionInput,
)

log = logging.getLogger(__name__)

# Every incident memory is tagged with this, so recall only ever searches incident knowledge
# (never the user's preference profile).
INCIDENT_TAG = "kind:incident-resolution"
# Metadata "memory_source" values. Memories without it predate auto-memory and came from resolutions.
SOURCE_AUTO = "auto-analysis"
SOURCE_RESOLUTION = "confirmed-resolution"
# Auto-extracted knowledge is retained as document "<incident id>:analysis", separate from the
# confirmed resolution document "<incident id>".
ANALYSIS_DOCUMENT_SUFFIX = ":analysis"
# Ranking bonus for human-confirmed knowledge over auto-extracted hypotheses.
CONFIRMED_TRUST_BONUS = 0.2
HEALTH_CACHE_SECONDS = 30.0

BANK_MISSION = (
    "You are the long-term memory of an SRE / DevOps incident-response agent. "
    "Remember production incidents: affected service and environment, symptoms, error signatures, "
    "confirmed root causes, fixes that worked, fixes that failed, outcomes and lessons learned."
)
RETAIN_MISSION = (
    "Extract durable incident-response knowledge: which service had which symptoms and errors, the "
    "confirmed root cause, the solution applied, approaches that did not work, the outcome, and lessons. "
    "Ignore UI or login activity."
)


class HindsightError(Exception):
    pass


_client: Hindsight | None = None
_ready_banks: set[str] = set()
_pending_banks: dict[str, "asyncio.Task[bool]"] = {}
_health_cache: tuple[float, HindsightStatus] | None = None


def get_client() -> Hindsight:
    global _client
    if _client is not None:
        return _client
    s = get_settings()
    if not s.hindsight_api_key:
        raise HindsightError("HINDSIGHT_API_KEY is not configured on the server.")
    _client = Hindsight(
        base_url=s.hindsight_base_url,
        api_key=s.hindsight_api_key,
        timeout=s.hindsight_timeout_seconds,
        max_attempts=2,
    )
    return _client


def set_client(client: Any) -> None:
    """Test hook: replace the SDK client (None resets all cached state)."""
    global _client, _health_cache
    _client = client
    _health_cache = None
    _ready_banks.clear()
    _pending_banks.clear()


async def aclose() -> None:
    global _client
    if _client is not None and hasattr(_client, "aclose"):
        await _client.aclose()
    _client = None


def describe_error(exc: BaseException) -> str:
    """Short, user-safe description of an SDK error (status/reason only, never response bodies)."""
    if isinstance(exc, HindsightError):
        return str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timed out"
    status = getattr(exc, "status", None)
    if status in (401, 403):
        return f"authentication failed ({status}) - check the server's HINDSIGHT_API_KEY"
    if status:
        return f"HTTP {status} {getattr(exc, 'reason', '') or ''}".strip()
    return type(exc).__name__


async def _create_bank(bank_id: str) -> bool:
    try:
        await get_client().acreate_bank(
            bank_id=bank_id, name="Incident Response Agent", mission=BANK_MISSION, retain_mission=RETAIN_MISSION
        )
    except Exception as exc:  # noqa: BLE001 - recall/retain report errors to the user
        log.warning("Could not ensure Hindsight bank: %s", describe_error(exc))
        return False
    _ready_banks.add(bank_id)
    return True


async def ensure_bank(bank_id: str) -> bool:
    """Create/update a user's private memory bank (idempotent upsert), at most once per process.

    Concurrent callers for the same bank share one in-flight request."""
    if bank_id in _ready_banks:
        return True
    task = _pending_banks.get(bank_id)
    if task is None:
        task = _pending_banks[bank_id] = asyncio.ensure_future(_create_bank(bank_id))
        task.add_done_callback(lambda _: _pending_banks.pop(bank_id, None))
    return await asyncio.shield(task)


async def health(bank_id: str | None = None) -> HindsightStatus:
    """Connectivity check. Public check (no bank) is cached; with bank_id, reports that bank's size."""
    global _health_cache
    if bank_id is None and _health_cache and time.monotonic() - _health_cache[0] < HEALTH_CACHE_SECONDS:
        return _health_cache[1]
    try:
        client = get_client()
        if bank_id is None:
            version = await client.aget_version()
            result = HindsightStatus(ok=True, detail=f"reachable (API {version.api_version})")
        else:
            await ensure_bank(bank_id)
            page = await client.alist_memories(bank_id=bank_id, limit=1)
            result = HindsightStatus(
                ok=True, detail=f"your memory bank is reachable ({page.total} memory units)", memory_units=page.total
            )
    except Exception as exc:  # noqa: BLE001
        result = HindsightStatus(ok=False, detail=describe_error(exc))
    if bank_id is None:
        _health_cache = (time.monotonic(), result)
    return result


# ---------------------------------------------------------------- recall


def build_recall_query(incident: IncidentInput) -> str:
    parts = [
        f"Previous incidents, root causes, solutions, failed fixes and outcomes for service {incident.service}",
        f"similar to: {incident.title}.",
        f"Symptoms: {incident.symptoms[:600]}",
    ]
    if incident.error_logs:
        parts.append(f"Errors: {incident.error_logs[:600]}")
    if incident.recent_changes:
        parts.append(f"Recent changes: {incident.recent_changes[:300]}")
    return " ".join(parts)


_WORD = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}")
_STOP = {
    "the", "and", "for", "with", "are", "was", "were", "from", "that", "this", "after", "into", "have",
    "has", "not", "but", "too", "very", "again", "than", "then", "our", "all", "any", "requests", "request",
    "error", "warn", "warning", "info", "debug", "latest", "yesterday", "today", "some", "more",
}


def keywords(text: str) -> set[str]:
    return {w.strip(".-_") for w in _WORD.findall(text.lower()) if w not in _STOP}


def _shared(a: str, b: str | None, exclude: set[str], limit: int = 6) -> list[str]:
    if not a or not b:
        return []
    return sorted((keywords(a) & keywords(b)) - exclude)[:limit]


def _same_service(incident: IncidentInput, m: RecalledIncident) -> bool:
    return m.service is not None and m.service.lower() == incident.service.lower()


def why_relevant(incident: IncidentInput, prev: RecalledIncident) -> list[str]:
    """Human-readable reasons this memory was recalled, from explicit signals plus Hindsight's score."""
    reasons: list[str] = []
    service_words = keywords(incident.service)
    if _same_service(incident, prev):
        reasons.append(f"Same service: {incident.service}")
    if prev.environment and prev.environment.lower() == incident.environment.lower():
        reasons.append(f"Same environment: {incident.environment}")
    if errors := _shared(incident.error_logs, prev.error_signature, service_words):
        reasons.append("Similar error signature: " + ", ".join(errors))
    if changes := _shared(incident.recent_changes, prev.recent_changes, service_words):
        reasons.append("Similar recent change: " + ", ".join(changes))
    previous_text = " ".join(filter(None, [prev.title, prev.root_cause, prev.solution] + [f.text for f in prev.facts]))
    if symptoms := _shared(f"{incident.title} {incident.symptoms}", previous_text, service_words, limit=8):
        reasons.append("Shared symptoms/signals: " + ", ".join(symptoms))
    if prev.relevance_score is not None:
        reasons.append(f"Hindsight semantic relevance: {prev.relevance_score:.2f}")
    return reasons


def _score(r: Any) -> float | None:
    scores = getattr(r, "scores", None)
    if scores is None:
        return None
    return scores.reranker if scores.reranker is not None else scores.final


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _incident_from_metadata(doc: str, meta: dict[str, Any], confirmed: bool) -> RecalledIncident:
    return RecalledIncident(
        incident_id=meta.get("incident_id", doc),
        title=meta.get("title"),
        service=meta.get("service"),
        environment=meta.get("environment"),
        severity=meta.get("severity"),
        root_cause=meta.get("root_cause") or None,
        solution=meta.get("solution") or None,
        outcome=meta.get("outcome") or None,
        failed_approaches=meta.get("failed_approaches") or None,
        error_signature=meta.get("error_signature") or None,
        recent_changes=meta.get("recent_changes") or None,
        resolved_at=meta.get("resolved_at") or None,
        confirmed=confirmed,
    )


def is_confirmed_resolution(meta: dict[str, Any], document_id: str | None) -> bool:
    """Only an engineer-confirmed resolution counts as confirmed knowledge.

    Auto-extracted analysis knowledge is an unconfirmed hypothesis. It is recognised by its
    `memory_source` metadata or, if metadata is missing, by its `<incident id>:analysis` document id,
    so a hypothesis can never be shown as a confirmed resolution. Memories that predate
    `memory_source` came only from resolutions."""
    if meta.get("memory_source") == SOURCE_AUTO:
        return False
    return not (document_id or "").endswith(ANALYSIS_DOCUMENT_SUFFIX)


def group_recall_results(results: list[Any]) -> tuple[list[RecalledIncident], list[RecalledFact]]:
    """Group recalled facts by source incident. An incident can have an auto-extracted analysis memory
    and a confirmed resolution memory; the confirmed details take precedence."""
    grouped: dict[str, RecalledIncident] = {}
    seen_text: dict[str, set[str]] = {}
    loose: list[RecalledFact] = []
    for r in results:
        fact = RecalledFact(text=r.text, type=r.type, score=_score(r))
        meta = r.metadata or {}
        doc = meta.get("incident_id") or r.document_id
        if not doc:
            loose.append(fact)
            continue
        confirmed = is_confirmed_resolution(meta, r.document_id)
        item = grouped.get(doc)
        if item is None or (confirmed and not item.confirmed):
            details = _incident_from_metadata(doc, meta, confirmed)
            if item is not None:
                details.facts, details.relevance_score = item.facts, item.relevance_score
            item = grouped[doc] = details
        key = _normalize(fact.text)
        if key in seen_text.setdefault(doc, set()):
            continue  # same fact recalled from both the analysis and the resolution memory
        seen_text[doc].add(key)
        item.facts.append(fact)
        if fact.score is not None and (item.relevance_score is None or fact.score > item.relevance_score):
            item.relevance_score = fact.score
    return list(grouped.values()), loose


def select_relevant(incident: IncidentInput, candidates: list[RecalledIncident]) -> list[RecalledIncident]:
    """Keep only relevant incidents, ranked by (same service, trust-weighted relevance)."""
    s = get_settings()
    relevant: list[RecalledIncident] = []
    for item in candidates:
        same_service = _same_service(incident, item)
        threshold = s.hindsight_min_relevance_same_service if same_service else s.hindsight_min_relevance
        if item.relevance_score is not None and item.relevance_score < threshold:
            continue
        if item.relevance_score is None and not same_service:
            continue
        item.facts = sorted(item.facts, key=lambda f: f.score or 0, reverse=True)[: s.recall_max_facts_per_incident]
        item.why_relevant = why_relevant(incident, item)
        relevant.append(item)

    def rank(m: RecalledIncident) -> tuple[bool, float]:
        return _same_service(incident, m), (m.relevance_score or 0) + (CONFIRMED_TRUST_BONUS if m.confirmed else 0)

    relevant.sort(key=rank, reverse=True)
    return relevant[: s.recall_max_incidents]


async def recall_incident_memory(incident: IncidentInput, bank_id: str) -> RecallResult:
    """RECALL from the authenticated user's own bank only. Never raises: failures degrade to status=error."""
    s = get_settings()
    query = build_recall_query(incident)
    try:
        await ensure_bank(bank_id)
        resp = await asyncio.wait_for(
            get_client().arecall(
                bank_id=bank_id,
                query=query,
                budget="mid",
                max_tokens=s.hindsight_recall_max_tokens,
                tags=[INCIDENT_TAG],
                tags_match="any_strict",
            ),
            timeout=s.hindsight_recall_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Hindsight recall failed: %s", describe_error(exc))
        return RecallResult(
            status="error",
            message=f"Hindsight memory is temporarily unavailable (recall failed: {describe_error(exc)}). "
            "The incident can still be analyzed without historical memory: this analysis uses the current incident only.",
            query=query,
        )

    candidates, loose = group_recall_results(list(resp.results or []))
    relevant = select_relevant(incident, candidates)
    loose = [f for f in loose if f.score is None or f.score >= s.hindsight_min_relevance][: s.recall_max_loose_facts]

    if not relevant and not loose:
        return RecallResult(
            status="empty",
            message="Hindsight was queried: no relevant previous incidents found in memory yet.",
            query=query,
        )
    n = len(relevant)
    confirmed = sum(m.confirmed for m in relevant)
    return RecallResult(
        status="ok",
        message=f"{n} relevant previous incident{'s' if n != 1 else ''} recalled from Hindsight "
        f"({confirmed} confirmed, {n - confirmed} unconfirmed)"
        + (f" (+{len(loose)} related facts)" if loose else ""),
        query=query,
        memories=relevant,
        other_facts=loose,
    )


# ---------------------------------------------------------------- retain

ERROR_SIGNATURE_CHARS = 600


def error_signature(error_logs: str) -> str:
    """A short, redacted error signature: enough to match future incidents, never a raw log dump."""
    return redact(error_logs[:ERROR_SIGNATURE_CHARS])


def build_memory_document(incident: dict[str, Any], resolution: ResolutionInput) -> str:
    lines = [
        f"Resolved production incident report: {incident['title']}",
        f"Service: {incident['service']}",
        f"Environment: {incident['environment']}",
        f"Severity: {incident['severity']}",
        f"Symptoms: {incident['symptoms'][:1000]}",
    ]
    if incident.get("error_logs"):
        lines.append(f"Error signature: {error_signature(incident['error_logs'])}")
    if incident.get("recent_changes"):
        lines.append(f"Recent changes before the incident: {incident['recent_changes'][:500]}")
    lines += [
        f"Confirmed root cause: {resolution.root_cause}",
        f"Solution that resolved it: {resolution.solution}",
        f"Outcome: {resolution.outcome}",
    ]
    if resolution.failed_approaches:
        lines.append(f"Approaches that did NOT work: {resolution.failed_approaches}")
    if resolution.notes:
        lines.append(f"Lessons learned / notes: {resolution.notes}")
    return redact("\n".join(lines))


async def _retain(**kwargs: Any) -> None:
    try:
        await ensure_bank(kwargs["bank_id"])
        resp = await get_client().aretain(**kwargs)
    except Exception as exc:
        log.warning("Hindsight retain failed: %s", describe_error(exc))
        raise HindsightError(f"Hindsight retain failed ({describe_error(exc)})") from exc
    if not resp.success:
        raise HindsightError("Hindsight retain returned success=false")


async def retain_incident_resolution(incident: dict[str, Any], resolution: ResolutionInput, bank_id: str) -> str:
    """Store the confirmed resolution in the user's own bank. Returns the memory document. Raises HindsightError."""
    document = build_memory_document(incident, resolution)
    resolved_at = datetime.now(UTC)
    metadata = {
        "incident_id": incident["id"],
        "title": incident["title"][:200],
        "service": incident["service"],
        "environment": incident["environment"],
        "severity": incident["severity"],
        "root_cause": redact(resolution.root_cause[:500]),
        "solution": redact(resolution.solution[:500]),
        "outcome": redact(resolution.outcome[:500]),
        "failed_approaches": redact(resolution.failed_approaches[:500]),
        "error_signature": error_signature(incident.get("error_logs") or "")[:300],
        "recent_changes": redact((incident.get("recent_changes") or "")[:300]),
        "resolved_at": resolved_at.isoformat(timespec="seconds"),
        "memory_source": SOURCE_RESOLUTION,
    }
    await _retain(
        bank_id=bank_id,
        content=document,
        context="resolved production incident: symptoms, root cause, fix and outcome",
        document_id=incident["id"],  # idempotent: re-saving replaces rather than duplicates
        timestamp=resolved_at,
        metadata=metadata,
        tags=[INCIDENT_TAG, f"service:{incident['service']}", f"env:{incident['environment']}", f"source:{SOURCE_RESOLUTION}"],
        retain_async=False,  # wait until stored so the next incident can recall it immediately
    )
    return document


def build_knowledge_document(incident: IncidentInput, items: list[AutoMemoryItem]) -> str:
    """Only the distilled knowledge items; never the raw incident text or logs."""
    header = (
        f"Incident-response knowledge for service {incident.service} ({incident.environment}), "
        f"from analysis of incident '{incident.title}'. Root causes and fixes are unconfirmed hypotheses "
        "unless stated otherwise."
    )
    return "\n".join([header] + [f"- [{i.category}] {i.content}" for i in items])


async def retain_incident_knowledge(
    incident: IncidentInput,
    incident_id: str,
    items: list[AutoMemoryItem],
    likely_root_cause: str,
    recommended_fix: str,
    bank_id: str,
) -> str:
    """Retain knowledge auto-extracted from an analysis, labelled unconfirmed. Raises HindsightError."""
    document = build_knowledge_document(incident, items)
    now = datetime.now(UTC)
    metadata = {
        "incident_id": incident_id,
        "title": incident.title[:200],
        "service": incident.service,
        "environment": incident.environment,
        "severity": incident.severity.value,
        "root_cause": f"Suspected (unconfirmed): {likely_root_cause}" if likely_root_cause else "",
        "solution": f"Recommended (unconfirmed): {recommended_fix}" if recommended_fix else "",
        "error_signature": error_signature(incident.error_logs)[:300],
        "recent_changes": redact(incident.recent_changes[:300]),
        "memory_source": SOURCE_AUTO,
        "captured_at": now.isoformat(timespec="seconds"),
    }
    await _retain(
        bank_id=bank_id,
        content=document,
        context="incident-response knowledge extracted automatically after an incident analysis",
        # Separate document from a later confirmed resolution (document_id=incident_id),
        # so neither replaces the other.
        document_id=f"{incident_id}{ANALYSIS_DOCUMENT_SUFFIX}",
        timestamp=now,
        metadata=metadata,
        tags=[INCIDENT_TAG, f"service:{incident.service}", f"env:{incident.environment}", f"source:{SOURCE_AUTO}"],
        retain_async=True,  # queue fact extraction server-side
    )
    return document
