"""API contracts (request validation and typed responses)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(StrEnum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


Likelihood = Literal["Low", "Medium", "High"]


def _level(v: object, default: str = "Medium") -> str:
    s = str(v or default).strip().capitalize()
    return s if s in {"Low", "Medium", "High"} else default


# ---------- requests ----------


class IncidentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    service: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._/-]+$")
    environment: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    severity: Severity
    symptoms: str = Field(min_length=3, max_length=5000)
    error_logs: str = Field(default="", max_length=10000)
    recent_changes: str = Field(default="", max_length=5000)
    additional_instructions: str = Field(default="", max_length=2000)


class ResolutionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    root_cause: str = Field(min_length=3, max_length=2000)
    solution: str = Field(min_length=3, max_length=4000)
    outcome: str = Field(min_length=3, max_length=2000)
    failed_approaches: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=4000)


# ---------- Hindsight recall, shaped for the UI ----------


class RecalledFact(BaseModel):
    text: str
    type: str | None = None
    score: float | None = None


class RecalledIncident(BaseModel):
    """One previous incident recalled from Hindsight, with the facts Hindsight returned for it."""

    incident_id: str | None = None
    title: str | None = None
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    outcome: str | None = None
    failed_approaches: str | None = None
    error_signature: str | None = None
    recent_changes: str | None = None
    resolved_at: str | None = None
    relevance_score: float | None = None
    # True = a human confirmed this resolution. False = auto-extracted hypothesis from an analysis.
    confirmed: bool = True
    why_relevant: list[str] = Field(default_factory=list)
    facts: list[RecalledFact] = Field(default_factory=list)


class RecallResult(BaseModel):
    status: Literal["ok", "empty", "error"]
    message: str
    query: str
    memories: list[RecalledIncident] = Field(default_factory=list)
    other_facts: list[RecalledFact] = Field(default_factory=list)  # relevant facts not tied to an incident


# ---------- Groq analysis (validated with Pydantic) ----------


class PossibleCause(BaseModel):
    cause: str
    likelihood: Likelihood = "Medium"
    evidence: str = ""

    @field_validator("likelihood", mode="before")
    @classmethod
    def normalize_likelihood(cls, v: object) -> str:
        return _level(v)


class HistoricalMatch(BaseModel):
    incident: str
    similarities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    how_it_applies: str = ""


class IncidentAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    possible_causes: list[PossibleCause] = Field(default_factory=list)
    historical_matches: list[HistoricalMatch] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    recommended_solution: str = Field(min_length=1)
    confidence: Likelihood = "Medium"
    confidence_reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: object) -> str:
        return _level(v)


# ---------- learning ----------


class AutoMemoryItem(BaseModel):
    category: str
    content: str


class AutoMemoryResult(BaseModel):
    """What the agent automatically decided to remember after an analysis (runs in the background)."""

    status: Literal["pending", "stored", "skipped", "error"]
    message: str
    items: list[AutoMemoryItem] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class PreferenceChange(BaseModel):
    action: Literal["added", "updated", "removed", "learned"]
    key: str
    preference: str


class PreferenceResult(BaseModel):
    """Long-term preferences recalled from Hindsight and applied, plus what was learned this time."""

    status: Literal["ok", "error"]
    message: str
    applied: list[str] = Field(default_factory=list)
    changes: list[PreferenceChange] = Field(default_factory=list)


class AnalysisMetrics(BaseModel):
    """Safe per-request instrumentation: durations, counts and token usage; no incident content."""

    total_ms: float
    stages_ms: dict[str, float]
    memories_recalled: int
    facts_in_prompt: int
    prompt_chars: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


# ---------- responses ----------


class AnalyzeResponse(BaseModel):
    incident_id: str
    analysis: IncidentAnalysis
    recall: RecallResult
    model: str
    memory: AutoMemoryResult
    preferences: PreferenceResult
    metrics: AnalysisMetrics | None = None


class ResolveResponse(BaseModel):
    incident_id: str
    retained: bool
    message: str
    memory_document: str
    retain_ms: float | None = None


class IncidentSummary(BaseModel):
    id: str
    title: str
    service: str
    environment: str
    severity: str
    status: str
    created_at: str
    root_cause: str | None = None
    outcome: str | None = None
    resolved_at: str | None = None
    retained_in_hindsight: bool


class IncidentMemories(BaseModel):
    incident_id: str
    recall: RecallResult | None
    groq_prompt: str | None


class HindsightStatus(BaseModel):
    ok: bool
    detail: str
    memory_units: int | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    groq: dict[str, str | bool]
    hindsight: HindsightStatus
    hindsight_configured: bool


class MeResponse(BaseModel):
    user_id: str
    username: str
    hindsight: HindsightStatus
    preferences: list[str] | None
