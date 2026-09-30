"""Incident endpoints. Every query is scoped to the authenticated user's user_id, and every
Hindsight recall/retain goes to that user's private memory bank."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from fastapi.concurrency import run_in_threadpool

from app.agent import incident_agent
from app.auth import User, current_user
from app.config import get_settings
from app.db import connect, now_iso, row_to_incident
from app.groq.client import GroqError
from app.hindsight.client import HindsightError, retain_incident_resolution
from app.observability import StageTimer
from app.schemas import (
    AnalysisMetrics,
    AnalyzeResponse,
    AutoMemoryResult,
    IncidentAnalysis,
    IncidentInput,
    IncidentMemories,
    IncidentSummary,
    RecallResult,
    ResolutionInput,
    ResolveResponse,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/incidents", tags=["incidents"])

IncidentId = Annotated[str, Path(pattern=r"^INC-[0-9A-F]{8}$")]
PENDING = AutoMemoryResult(status="pending", message="Learning from this analysis in the background...")


# ---------------------------------------------------------------- persistence helpers (sync, threadpool)


def _load(incident_id: str, user: User) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ? AND user_id = ?", (incident_id, user.id)).fetchone()
    if row is None:  # also for incidents owned by other users: never reveal they exist
        raise HTTPException(404, "Incident not found")
    return row_to_incident(row)


def _insert_incident(incident_id: str, user: User, body: IncidentInput, outcome: incident_agent.AnalysisOutcome) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO incidents (id, user_id, title, service, environment, severity, symptoms, error_logs,
               recent_changes, created_by, created_at, status, analysis_json, recall_json, groq_prompt, groq_model,
               learning_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?, ?, ?, ?)""",
            (
                incident_id, user.id, body.title, body.service, body.environment, body.severity.value, body.symptoms,
                body.error_logs, body.recent_changes, user.username, now_iso(),
                outcome.analysis.model_dump_json(), outcome.recall.model_dump_json(), outcome.prompt,
                get_settings().groq_model, PENDING.model_dump_json(),
            ),
        )


def _save_learning(incident_id: str, user_id: str, result: AutoMemoryResult) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE incidents SET learning_json = ? WHERE id = ? AND user_id = ?",
            (result.model_dump_json(), incident_id, user_id),
        )


async def _learn_in_background(
    body: IncidentInput, incident_id: str, analysis: IncidentAnalysis, recall: RecallResult, user: User
) -> None:
    try:
        result = await incident_agent.learn_from_analysis(body, incident_id, analysis, recall, user.bank_id)
    except Exception as exc:  # noqa: BLE001 - background work must always record a final status
        log.error("Background learning crashed for %s: %s", incident_id, type(exc).__name__)
        result = AutoMemoryResult(status="error", message="Learning failed unexpectedly; nothing was stored.")
    await run_in_threadpool(_save_learning, incident_id, user.id, result)


# ---------------------------------------------------------------- routes


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_incident(
    body: IncidentInput, background: BackgroundTasks, user: User = Depends(current_user)
) -> AnalyzeResponse:
    timer = StageTimer()
    incident_id = "INC-" + uuid.uuid4().hex[:8].upper()
    try:
        outcome = await incident_agent.analyze(body, user.bank_id, timer)
    except GroqError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    with timer.stage("db_write"):
        await run_in_threadpool(_insert_incident, incident_id, user, body, outcome)
    # LEARN -> RETAIN happens after the response is sent; its status is persisted and pollable.
    background.add_task(_learn_in_background, body, incident_id, outcome.analysis, outcome.recall, user)

    metrics = AnalysisMetrics(
        total_ms=timer.total_ms(),
        stages_ms=timer.ms,
        memories_recalled=len(outcome.recall.memories),
        facts_in_prompt=outcome.facts_in_prompt,
        prompt_chars=len(incident_agent.SYSTEM_PROMPT) + len(outcome.prompt),
        prompt_tokens=outcome.usage.prompt_tokens,
        completion_tokens=outcome.usage.completion_tokens,
    )
    log.info(
        "analysis %s total=%.0fms stages=%s recall=%s memories=%d facts=%d prompt_tokens=%s",
        incident_id, metrics.total_ms, metrics.stages_ms, outcome.recall.status,
        metrics.memories_recalled, metrics.facts_in_prompt, metrics.prompt_tokens,
    )
    return AnalyzeResponse(
        incident_id=incident_id,
        analysis=outcome.analysis,
        recall=outcome.recall,
        model=get_settings().groq_model,
        memory=PENDING,
        preferences=outcome.preferences,
        metrics=metrics if get_settings().expose_metrics else None,
    )


@router.post("/{incident_id}/resolve", response_model=ResolveResponse)
async def resolve_incident(incident_id: IncidentId, body: ResolutionInput, user: User = Depends(current_user)) -> ResolveResponse:
    incident = await run_in_threadpool(_load, incident_id, user)
    if incident["retained_in_hindsight"]:
        raise HTTPException(409, "This incident's resolution is already stored in Hindsight")
    timer = StageTimer()
    try:
        with timer.stage("hindsight_retain"):
            document = await retain_incident_resolution(incident, body, user.bank_id)
    except HindsightError as exc:
        raise HTTPException(502, f"{exc}. The resolution was NOT saved to memory - please retry.") from exc

    def _mark_resolved() -> None:
        with connect() as conn:
            conn.execute(
                """UPDATE incidents SET status='resolved', root_cause=?, solution=?, outcome=?, failed_approaches=?,
                   notes=?, resolved_at=?, retained_in_hindsight=1 WHERE id=? AND user_id=?""",
                (body.root_cause, body.solution, body.outcome, body.failed_approaches, body.notes, now_iso(), incident_id, user.id),
            )

    await run_in_threadpool(_mark_resolved)
    return ResolveResponse(
        incident_id=incident_id,
        retained=True,
        message="Confirmed resolution retained in your Hindsight memory. Similar future incidents will recall it "
        "as trusted evidence.",
        memory_document=document,
        retain_ms=timer.ms.get("hindsight_retain"),
    )


@router.get("", response_model=list[IncidentSummary])
def list_incidents(user: User = Depends(current_user)) -> list[IncidentSummary]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, service, environment, severity, status, created_at, root_cause, outcome,
               resolved_at, retained_in_hindsight FROM incidents WHERE user_id = ? ORDER BY created_at DESC""",
            (user.id,),
        ).fetchall()
    return [IncidentSummary.model_validate(dict(r)) for r in rows]


@router.get("/{incident_id}")
def get_incident(incident_id: IncidentId, user: User = Depends(current_user)) -> dict[str, Any]:
    return _load(incident_id, user)


@router.get("/{incident_id}/learning", response_model=AutoMemoryResult)
def get_incident_learning(incident_id: IncidentId, user: User = Depends(current_user)) -> AutoMemoryResult:
    """Status of the background LEARN -> RETAIN step for this incident (poll while 'pending')."""
    learning = _load(incident_id, user)["learning"]
    if learning is None:
        return AutoMemoryResult(status="skipped", message="No automatic learning record for this incident.")
    return AutoMemoryResult.model_validate(learning)


@router.get("/{incident_id}/memories", response_model=IncidentMemories)
def get_incident_memories(incident_id: IncidentId, user: User = Depends(current_user)) -> IncidentMemories:
    """What Hindsight recalled for this incident, and the exact prompt Groq received."""
    incident = _load(incident_id, user)
    return IncidentMemories(incident_id=incident_id, recall=incident["recall"], groq_prompt=incident["groq_prompt"])
