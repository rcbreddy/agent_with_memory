"""Opt-in end-to-end test against the REAL Groq and Hindsight APIs.

    RUN_LIVE_TESTS=1 pytest -m live -s

Reads keys from backend/.env, creates a throwaway user (and therefore a fresh, private Hindsight
bank), runs the two demo incidents and prints the per-stage latency of each analysis.
"""

import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.config import get_settings
from app.groq import client as groq_client
from app.hindsight import client as hindsight_client
from tests.conftest import DEMO_1, DEMO_2, RESOLUTION_1

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call the real APIs"),
]


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    for key in ("GROQ_API_KEY", "GROQ_MODEL", "HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "HINDSIGHT_BANK_ID"):
        if env.get(key):
            monkeypatch.setenv(key, env[key])
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "live.db"))
    get_settings.cache_clear()
    hindsight_client.set_client(None)
    groq_client.set_transport(None)
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_live_memory_loop(live_client):
    c = live_client
    token = c.post("/api/auth/register", json={"username": f"live-{uuid.uuid4().hex[:8]}", "password": "live-test-pass-1"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = c.post("/api/incidents/analyze", json=DEMO_1, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["recall"]["status"] == "empty"
    print("\nincident 1 metrics:", first.json()["metrics"])

    inc = first.json()["incident_id"]
    resolved = c.post(f"/api/incidents/{inc}/resolve", json=RESOLUTION_1, headers=headers)
    assert resolved.status_code == 200, resolved.text
    print("resolution retain_ms:", resolved.json()["retain_ms"])

    second = c.post("/api/incidents/analyze", json=DEMO_2, headers=headers)
    assert second.status_code == 200, second.text
    body = second.json()
    print("incident 2 metrics:", body["metrics"])
    print("incident 2 recall:", body["recall"]["message"])
    assert body["recall"]["status"] == "ok"
    assert any(m["incident_id"] == inc and m["confirmed"] for m in body["recall"]["memories"])
    assert body["analysis"]["historical_matches"]
