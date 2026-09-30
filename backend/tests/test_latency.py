"""Latency behaviour: independent work runs concurrently, learning is off the critical path, and
every analysis reports safe per-stage metrics."""

import time

from app.config import get_settings
from tests.conftest import DEMO_1, register

DELAY = 0.4


def test_metrics_are_reported_without_content(client):
    headers = register(client)
    body = client.post("/api/incidents/analyze", json=DEMO_1, headers=headers).json()
    m = body["metrics"]
    assert {"hindsight_recall", "preferences_load", "groq_analysis", "preference_learning", "db_write"} <= set(m["stages_ms"])
    assert m["total_ms"] >= m["stages_ms"]["groq_analysis"]
    assert m["prompt_tokens"] > 0 and m["completion_tokens"] == 120
    assert m["memories_recalled"] == 0 and m["prompt_chars"] > 0
    assert DEMO_1["symptoms"] not in str(m)


def test_metrics_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("EXPOSE_METRICS", "false")
    get_settings.cache_clear()
    headers = register(client)
    assert client.post("/api/incidents/analyze", json=DEMO_1, headers=headers).json()["metrics"] is None


def test_recall_and_preference_load_run_concurrently(client, fake_hindsight):
    headers = register(client)
    fake_hindsight.delays.update(arecall=DELAY, get_document=DELAY)
    m = client.post("/api/incidents/analyze", json=DEMO_1, headers=headers).json()["metrics"]
    assert m["stages_ms"]["hindsight_recall"] >= DELAY * 1000 * 0.9
    assert m["stages_ms"]["preferences_load"] >= DELAY * 1000 * 0.9
    assert m["total_ms"] < DELAY * 2 * 1000 - 100  # overlapped, not sequential


def test_preference_learning_runs_concurrently_with_analysis(client, fake_groq):
    headers = register(client)
    fake_groq.delays.update(analysis=DELAY, preferences=DELAY)
    payload = {**DEMO_1, "additional_instructions": "From now on end every summary with OK"}
    m = client.post("/api/incidents/analyze", json=payload, headers=headers).json()["metrics"]
    assert m["stages_ms"]["preference_learning"] >= DELAY * 1000 * 0.9
    assert m["total_ms"] < DELAY * 2 * 1000 - 100


def test_memory_extraction_is_off_the_critical_path(client, fake_groq):
    headers = register(client)
    fake_groq.delays["extraction"] = DELAY
    body = client.post("/api/incidents/analyze", json=DEMO_1, headers=headers).json()
    assert body["memory"]["status"] == "pending"
    assert "memory_extraction" not in body["metrics"]["stages_ms"]
    assert body["metrics"]["total_ms"] < DELAY * 1000  # the response did not wait for extraction
    learning = client.get(f"/api/incidents/{body['incident_id']}/learning", headers=headers).json()
    assert learning["status"] == "stored" and learning["timings_ms"]["memory_extraction"] >= DELAY * 1000 * 0.9


def test_bank_creation_is_deduplicated(client, fake_hindsight):
    headers = register(client)
    for _ in range(3):
        client.post("/api/incidents/analyze", json=DEMO_1, headers=headers)
    assert [m for m, _ in fake_hindsight.calls].count("acreate_bank") == 1


def test_public_health_is_cached(client, fake_hindsight):
    for _ in range(5):
        client.get("/api/health")
    assert [m for m, _ in fake_hindsight.calls].count("aget_version") == 1


def test_login_does_not_wait_for_hindsight(client, fake_hindsight):
    register(client, "alice", "correct-horse-1")
    fake_hindsight.failures["acreate_bank"] = ConnectionError("down")
    start = time.perf_counter()
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse-1"})
    assert resp.status_code == 200 and time.perf_counter() - start < 2
