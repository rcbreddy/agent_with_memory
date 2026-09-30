"""Shared fixtures.

External services are replaced at their boundaries, so all of our own code runs for real:
- Hindsight: FakeHindsight implements the SDK methods we use, with real per-bank storage, tag
  filtering and keyword-overlap relevance scores (a stand-in for Hindsight's semantic reranker).
- Groq: FakeGroq is an httpx MockTransport, so our HTTP client, retries and JSON parsing are exercised.
"""

import asyncio
import json
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

# Never read the developer's real backend/.env in tests.
os.environ["APP_ENV_FILE"] = ""
GROQ_KEY = "gsk_TESTSECRETgroqkey0123456789abcdef"
HINDSIGHT_KEY = "hs_TESTSECREThindsightkey0123456789"
os.environ.update(
    GROQ_API_KEY=GROQ_KEY,
    HINDSIGHT_API_KEY=HINDSIGHT_KEY,
    GROQ_MODEL="openai/gpt-oss-120b",
    DEMO_PASSWORD="",
    LOG_LEVEL="INFO",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from hindsight_client_api.exceptions import NotFoundException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.groq import client as groq_client  # noqa: E402
from app.hindsight import client as hindsight_client  # noqa: E402
from app.hindsight import preferences  # noqa: E402

DEMO_1 = {
    "title": "Payment API Latency",
    "service": "payment-api",
    "environment": "production",
    "severity": "High",
    "symptoms": "Payment API latency is very high. Payment requests are taking 5-10 seconds.",
    "error_logs": "ERROR RedisConnectionPool: connection pool exhausted (max=50), waited 5000ms for a free connection",
    "recent_changes": "Latest release deployed yesterday.",
    "additional_instructions": "",
}
DEMO_2 = {
    "title": "Payment requests slow again",
    "service": "payment-api",
    "environment": "production",
    "severity": "High",
    "symptoms": "Payment requests are slow again. p95 latency up to 4s during checkout.",
    "error_logs": "WARN redis.clients: Redis timeout after 2000ms, connection pool exhausted",
    "recent_changes": "Traffic increased by 40% after marketing campaign.",
    "additional_instructions": "",
}
RESOLUTION_1 = {
    "root_cause": "Redis connection pool exhaustion",
    "solution": "Increased Redis connection pool size from 50 to 150",
    "outcome": "Latency returned to normal",
    "failed_approaches": "Restarting payment-api pods only helped for 10 minutes",
    "notes": "Alert on Redis pool utilisation above 80%",
}


# ---------------------------------------------------------------- fake Hindsight

_WORDS = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}")


def _raw_kw(text: str) -> set[str]:
    return {w.strip(".-_") for w in _WORDS.findall(text.lower())}


# Words a semantic reranker would not treat as evidence: the recall query's fixed wording and filler.
_FAKE_STOP = _raw_kw(
    "Previous incidents, root causes, solutions, failed fixes and outcomes for service similar to "
    "Symptoms Errors Recent changes the and are was were from with this that into after unless stated otherwise"
)


def _kw(text: str) -> set[str]:
    return _raw_kw(text) - _FAKE_STOP


@dataclass
class StoredDoc:
    content: str
    metadata: dict[str, str]
    tags: list[str]
    context: str = ""
    update_mode: str | None = None


class FakeDocuments:
    def __init__(self, hs: "FakeHindsight"):
        self._hs = hs

    async def get_document(self, bank_id: str, document_id: str) -> Any:
        await self._hs._maybe_fail("get_document", bank_id)
        await asyncio.sleep(self._hs.delays.get("get_document", 0))
        doc = self._hs.banks.get(bank_id, {}).get(document_id)
        if doc is None:
            raise NotFoundException(status=404, reason="Not Found")
        return SimpleNamespace(document_metadata=doc.metadata)


class FakeHindsight:
    def __init__(self) -> None:
        self.banks: dict[str, dict[str, StoredDoc]] = defaultdict(dict)
        self.calls: list[tuple[str, str]] = []  # (method, bank_id)
        self.failures: dict[str, BaseException] = {}
        self.delays: dict[str, float] = {}
        self.documents = FakeDocuments(self)

    async def _maybe_fail(self, method: str, bank_id: str) -> None:
        self.calls.append((method, bank_id))
        if method in self.failures:
            raise self.failures[method]

    async def acreate_bank(self, bank_id: str, **_: Any) -> Any:
        await self._maybe_fail("acreate_bank", bank_id)
        self.banks.setdefault(bank_id, {})
        return SimpleNamespace(bank_id=bank_id)

    async def aretain(self, bank_id: str, content: str, document_id: str, metadata: dict[str, str],
                      tags: list[str], context: str = "", update_mode: str | None = None, **_: Any) -> Any:
        await self._maybe_fail("aretain", bank_id)
        self.banks[bank_id][document_id] = StoredDoc(content, dict(metadata), list(tags), context, update_mode)
        return SimpleNamespace(success=True)

    async def arecall(self, bank_id: str, query: str, tags: list[str] | None = None,
                      tags_match: str = "any", **_: Any) -> Any:
        await self._maybe_fail("arecall", bank_id)
        await asyncio.sleep(self.delays.get("arecall", 0))
        q = _kw(query)
        results = []
        for doc_id, doc in self.banks.get(bank_id, {}).items():
            if tags and not set(tags) & set(doc.tags):
                continue  # any_strict: untagged or differently tagged memories are excluded
            for line in doc.content.splitlines():
                value = line.split(":", 1)[1] if ":" in line else line
                words = _kw(value)
                if not words:
                    continue
                score = len(q & words) / len(words)
                if score >= 0.05:
                    results.append(SimpleNamespace(
                        text=line.strip(), type="world", metadata=doc.metadata, document_id=doc_id,
                        scores=SimpleNamespace(reranker=round(score, 3), final=round(score, 3)),
                    ))
        results.sort(key=lambda r: r.scores.reranker, reverse=True)
        return SimpleNamespace(results=results[:20])

    async def alist_memories(self, bank_id: str, limit: int = 100, **_: Any) -> Any:
        await self._maybe_fail("alist_memories", bank_id)
        total = sum(len(d.content.splitlines()) for d in self.banks.get(bank_id, {}).values())
        return SimpleNamespace(total=total, items=[])

    async def aget_version(self) -> Any:
        await self._maybe_fail("aget_version", "")
        return SimpleNamespace(api_version="test")

    def docs(self, bank_id: str) -> dict[str, StoredDoc]:
        return self.banks.get(bank_id, {})


# ---------------------------------------------------------------- fake Groq


@dataclass
class GroqCall:
    kind: str  # "analysis" | "extraction" | "preferences"
    system: str
    user: str
    body: dict[str, Any]


@dataclass
class FakeGroq:
    calls: list[GroqCall] = field(default_factory=list)
    queued: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    delays: dict[str, float] = field(default_factory=dict)

    def push(self, kind: str, item: Any) -> None:
        """Queue a scripted reply for the next call of `kind`: a dict (JSON reply), str (raw
        content), httpx.Response, or an exception to raise."""
        self.queued[kind].append(item)

    def of(self, kind: str) -> list[GroqCall]:
        return [c for c in self.calls if c.kind == kind]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        kind = "extraction" if system.startswith("You curate") else "preferences" if system.startswith("You maintain") else "analysis"
        self.calls.append(GroqCall(kind, system, user, body))
        await asyncio.sleep(self.delays.get(kind, 0))
        if self.queued[kind]:
            item = self.queued[kind].popleft()
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, httpx.Response):
                return item
            content = item if isinstance(item, str) else json.dumps(item)
        else:
            content = json.dumps(getattr(self, f"_default_{kind}")(user))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": len(system + user) // 4, "completion_tokens": 120},
        })

    @staticmethod
    def _default_analysis(user: str) -> dict[str, Any]:
        memory = user.split("<historical_memory>")[1].split("</historical_memory>")[0]
        matches = []
        if "[Memory 1" in memory:
            title = memory.split("] ", 1)[1].split(" (service=")[0]
            matches = [{"incident": title, "similarities": ["Redis", "payment-api latency"],
                        "differences": ["Traffic is 40% higher now"], "how_it_applies": "Check pool sizing for the new load"}]
        return {
            "summary": "Payment latency caused by Redis connection pressure.",
            "possible_causes": [{"cause": "Redis connection pool exhaustion", "likelihood": "High", "evidence": "pool exhausted logs"}],
            "historical_matches": matches,
            "recommended_checks": ["Check Redis pool utilisation"],
            "recommended_solution": "Increase the Redis pool and add an alert.",
            "confidence": "high",
            "confidence_reason": "Clear error signature.",
        }

    @staticmethod
    def _default_extraction(user: str) -> dict[str, Any]:
        def field_(name: str) -> str:
            m = re.search(rf"^{name}: (.*)$", user, re.M)
            return m.group(1) if m else ""

        service, title, errors = field_("Service"), field_("Title"), field_("Error logs")
        return {
            "worth_remembering": True,
            "reason": "Useful diagnostic signal",
            "likely_root_cause": f"Suspected cause of {title}",
            "recommended_fix": f"Mitigate {title}",
            "memories": [
                {"category": "diagnostic_finding", "content": f"On {service}, the signal '{errors[:80]}' pointed to the cause of {title}."},
                {"category": "root_cause", "content": f"{service}: {title} is suspected to come from {errors[:60]}."},
            ],
        }

    @staticmethod
    def _default_preferences(user: str) -> dict[str, Any]:
        instruction = user.split("USER INSTRUCTION WITH THIS REPORT:\n")[1].split("\n\nReturn only")[0]
        low = instruction.lower()
        if "stop" in low:
            return {"changes": [{"action": "remove", "key": "summary-ending", "preference": ""}], "one_time_requests": [], "reason": "cancelled"}
        if "from now on" in low:
            word = instruction.rstrip(". ").split()[-1].strip("'\"")
            return {"changes": [{"action": "add", "key": "summary-ending", "preference": f"End every summary with '{word}'.",
                                 "category": "formatting"}], "one_time_requests": [], "reason": "lasting"}
        return {"changes": [], "one_time_requests": [{"key": "detail-level", "preference": "Keep responses brief.",
                                                      "category": "detail_level"}], "reason": "one-off"}


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_hindsight() -> FakeHindsight:
    return FakeHindsight()


@pytest.fixture
def fake_groq() -> FakeGroq:
    return FakeGroq()


@pytest.fixture
def services(tmp_path, monkeypatch, fake_hindsight, fake_groq):
    """Isolated DB + fake external services for one test."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    hindsight_client.set_client(fake_hindsight)
    groq_client.set_transport(httpx.MockTransport(fake_groq.handler))
    preferences._locks.clear()
    yield
    hindsight_client.set_client(None)
    groq_client.set_transport(None)
    get_settings.cache_clear()


@pytest.fixture
def client(services):
    from app.main import app

    with TestClient(app) as c:
        yield c


def register(client: TestClient, username: str = "alice", password: str = "correct-horse-1") -> dict[str, str]:
    resp = client.post("/api/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def bank_of(client: TestClient, headers: dict[str, str]) -> str:
    user_id = client.get("/api/auth/me", headers=headers).json()["user_id"]
    return f"{get_settings().hindsight_bank_id}-u-{user_id}"
