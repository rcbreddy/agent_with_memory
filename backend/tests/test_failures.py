"""Graceful degradation: every external dependency can fail without corrupting state or leaking detail."""

import sqlite3

import httpx
import pytest

from app.config import get_settings
from tests.conftest import DEMO_1, DEMO_2, RESOLUTION_1, register

VALID_ANALYSIS = {
    "summary": "ok", "possible_causes": [], "historical_matches": [], "recommended_checks": [],
    "recommended_solution": "fix it", "confidence": "Low", "confidence_reason": "",
}


def _analyze(client, headers, incident=DEMO_1):
    return client.post("/api/incidents/analyze", json=incident, headers=headers)


@pytest.mark.parametrize(
    "missing", ["title", "service", "severity", "symptoms"],
)
def test_missing_required_fields_are_rejected(client, missing):
    headers = register(client)
    payload = {k: v for k, v in DEMO_1.items() if k != missing}
    assert _analyze(client, headers, payload).status_code == 422


@pytest.mark.parametrize(
    "override",
    [{"severity": "Apocalyptic"}, {"service": "payment api; rm -rf /"}, {"title": "x" * 201}, {"error_logs": "x" * 10001}, {"symptoms": 42}],
)
def test_malformed_input_is_rejected(client, override):
    headers = register(client)
    assert _analyze(client, headers, {**DEMO_1, **override}).status_code == 422


def test_groq_down_returns_503_and_stores_nothing(client, fake_groq):
    headers = register(client)
    fake_groq.push("analysis", httpx.ConnectError("connection refused"))
    resp = _analyze(client, headers)
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()
    assert client.get("/api/incidents", headers=headers).json() == []


def test_groq_timeout_returns_504(client, fake_groq):
    headers = register(client)
    fake_groq.push("analysis", httpx.ReadTimeout("slow"))
    resp = _analyze(client, headers)
    assert resp.status_code == 504 and "timed out" in resp.json()["detail"]


def test_malformed_llm_output_is_retried_once(client, fake_groq):
    headers = register(client)
    fake_groq.push("analysis", "this is not json")
    fake_groq.push("analysis", VALID_ANALYSIS)
    resp = _analyze(client, headers)
    assert resp.status_code == 200
    assert len(fake_groq.of("analysis")) == 2


def test_invalid_schema_twice_fails_cleanly(client, fake_groq):
    headers = register(client)
    fake_groq.push("analysis", {"summary": "missing the solution"})
    fake_groq.push("analysis", {"possible_causes": "not a list"})
    resp = _analyze(client, headers)
    assert resp.status_code == 502
    assert len(fake_groq.of("analysis")) == 2  # retried exactly once, not more


def test_non_retryable_groq_errors_are_not_retried(client, fake_groq):
    headers = register(client)
    fake_groq.push("analysis", httpx.Response(401, json={"error": {"message": "invalid key"}}))
    assert _analyze(client, headers).status_code == 502
    assert len(fake_groq.of("analysis")) == 1


def test_hindsight_down_degrades_gracefully(client, fake_hindsight, fake_groq):
    headers = register(client)
    fake_hindsight.failures["arecall"] = ConnectionError("hindsight unreachable")
    fake_groq.push("analysis", {**VALID_ANALYSIS, "historical_matches": [{"incident": "invented"}]})
    resp = _analyze(client, headers, DEMO_2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["recall"]["status"] == "error"
    assert "Historical memory was unavailable" in body["recall"]["message"]
    assert body["analysis"]["historical_matches"] == []  # nothing invented when memory failed
    assert "memory was unavailable" in fake_groq.of("analysis")[-1].user


def test_slow_hindsight_recall_hits_time_budget(client, fake_hindsight, monkeypatch):
    monkeypatch.setenv("HINDSIGHT_RECALL_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()
    headers = register(client)
    fake_hindsight.delays["arecall"] = 1.0
    resp = _analyze(client, headers)
    assert resp.status_code == 200
    assert resp.json()["recall"]["status"] == "error" and "timed out" in resp.json()["recall"]["message"]


def test_resolution_retain_failure_can_be_retried(client, fake_hindsight):
    headers = register(client)
    inc = _analyze(client, headers).json()["incident_id"]
    fake_hindsight.failures["aretain"] = ConnectionError("down")
    failed = client.post(f"/api/incidents/{inc}/resolve", json=RESOLUTION_1, headers=headers)
    assert failed.status_code == 502 and "NOT saved" in failed.json()["detail"]
    assert client.get(f"/api/incidents/{inc}", headers=headers).json()["retained_in_hindsight"] is False

    del fake_hindsight.failures["aretain"]
    assert client.post(f"/api/incidents/{inc}/resolve", json=RESOLUTION_1, headers=headers).status_code == 200


def test_auto_retain_failure_keeps_the_analysis(client, fake_hindsight):
    headers = register(client)
    fake_hindsight.failures["aretain"] = ConnectionError("down")
    resp = _analyze(client, headers)
    assert resp.status_code == 200 and resp.json()["analysis"]["summary"]
    learning = client.get(f"/api/incidents/{resp.json()['incident_id']}/learning", headers=headers).json()
    assert learning["status"] == "error" and learning["items"]


def test_memory_extraction_failure_keeps_the_analysis(client, fake_groq):
    headers = register(client)
    fake_groq.push("extraction", "garbage")
    fake_groq.push("extraction", "still garbage")
    resp = _analyze(client, headers)
    assert resp.status_code == 200
    assert resp.json()["memory"]["status"] == "pending"
    learning = client.get(f"/api/incidents/{resp.json()['incident_id']}/learning", headers=headers).json()
    assert learning["status"] == "error"


def test_preference_store_down_does_not_block_analysis(client, fake_hindsight):
    headers = register(client)
    fake_hindsight.failures["get_document"] = ConnectionError("down")
    resp = _analyze(client, headers, {**DEMO_1, "additional_instructions": "From now on end every summary with OK"})
    assert resp.status_code == 200
    assert resp.json()["preferences"]["status"] == "error"


def test_database_error_returns_503(client, monkeypatch):
    headers = register(client)

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("app.api.incidents._insert_incident", broken)
    resp = _analyze(client, headers)
    assert resp.status_code == 503
    assert "locked" not in resp.text  # internal detail not exposed


def test_missing_groq_key_is_reported_without_crashing(client, monkeypatch):
    headers = register(client)
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    resp = _analyze(client, headers)
    assert resp.status_code == 503 and "GROQ_API_KEY is not configured" in resp.json()["detail"]
