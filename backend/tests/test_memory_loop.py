"""The core story: Incident A -> analyze -> resolve -> RETAIN; Incident B -> RECALL A -> Groq reasons with A."""

from app.hindsight.client import INCIDENT_TAG, SOURCE_AUTO, SOURCE_RESOLUTION
from tests.conftest import DEMO_1, DEMO_2, RESOLUTION_1, bank_of, register


def _analyze(client, headers, incident):
    resp = client.post("/api/incidents/analyze", json=incident, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_first_incident_has_no_history_and_invents_none(client, fake_groq):
    headers = register(client)
    body = _analyze(client, headers, DEMO_1)

    assert body["recall"]["status"] == "empty"
    assert body["recall"]["memories"] == []
    assert body["analysis"]["historical_matches"] == []
    prompt = fake_groq.of("analysis")[0].user
    assert "No relevant previous incidents exist in memory yet" in prompt


def test_full_memory_loop_second_incident_recalls_confirmed_first(client, fake_hindsight, fake_groq):
    headers = register(client)
    bank = bank_of(client, headers)

    # Incident A: analyze, then confirm the resolution.
    first = _analyze(client, headers, DEMO_1)
    inc_a = first["incident_id"]
    resolved = client.post(f"/api/incidents/{inc_a}/resolve", json=RESOLUTION_1, headers=headers)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["retained"] is True

    stored = fake_hindsight.docs(bank)[inc_a]
    assert stored.metadata["memory_source"] == SOURCE_RESOLUTION
    assert stored.metadata["root_cause"] == RESOLUTION_1["root_cause"]
    assert INCIDENT_TAG in stored.tags

    # Incident B: similar symptoms -> Hindsight recalls A.
    second = _analyze(client, headers, DEMO_2)
    recall = second["recall"]
    assert recall["status"] == "ok"
    top = recall["memories"][0]
    assert top["incident_id"] == inc_a
    assert top["confirmed"] is True
    assert top["root_cause"] == RESOLUTION_1["root_cause"]
    assert top["solution"] == RESOLUTION_1["solution"]
    assert "Same service: payment-api" in top["why_relevant"]
    assert any(r.startswith("Similar error signature") for r in top["why_relevant"])

    # The historical memory is passed to Groq, labelled as confirmed evidence.
    prompt = fake_groq.of("analysis")[-1].user
    memory_section = prompt.split("<historical_memory>")[1].split("</historical_memory>")[0]
    assert "CONFIRMED resolution" in memory_section
    assert RESOLUTION_1["root_cause"] in memory_section
    assert RESOLUTION_1["failed_approaches"] in memory_section
    assert "EVIDENCE, NOT ANSWERS" in fake_groq.of("analysis")[-1].system
    assert second["analysis"]["historical_matches"][0]["incident"] == DEMO_1["title"]

    # Recall only ever read from this user's bank.
    assert {b for m, b in fake_hindsight.calls if m == "arecall"} == {bank}


def test_unconfirmed_hypothesis_is_distinguished_from_confirmed(client, fake_hindsight, fake_groq):
    headers = register(client)
    bank = bank_of(client, headers)

    first = _analyze(client, headers, DEMO_1)  # analyzed, never resolved
    auto_doc = fake_hindsight.docs(bank)[f"{first['incident_id']}:analysis"]
    assert auto_doc.metadata["memory_source"] == SOURCE_AUTO
    assert auto_doc.metadata["root_cause"].startswith("Suspected (unconfirmed)")

    second = _analyze(client, headers, DEMO_2)
    top = second["recall"]["memories"][0]
    assert top["incident_id"] == first["incident_id"]
    assert top["confirmed"] is False
    assert "unconfirmed" in top["root_cause"].lower()
    assert "UNCONFIRMED hypothesis" in fake_groq.of("analysis")[-1].user


def test_confirmed_resolution_takes_precedence_over_hypothesis_for_same_incident(client, fake_hindsight):
    headers = register(client)
    first = _analyze(client, headers, DEMO_1)  # stores the unconfirmed analysis memory
    client.post(f"/api/incidents/{first['incident_id']}/resolve", json=RESOLUTION_1, headers=headers)

    memories = _analyze(client, headers, DEMO_2)["recall"]["memories"]
    same = [m for m in memories if m["incident_id"] == first["incident_id"]]
    assert len(same) == 1  # grouped, not shown twice
    assert same[0]["confirmed"] is True
    assert same[0]["root_cause"] == RESOLUTION_1["root_cause"]


def test_irrelevant_memories_are_not_shown(client, fake_groq):
    headers = register(client)
    unrelated = {
        **DEMO_1,
        "title": "Disk full on auth nodes",
        "service": "auth-service",
        "symptoms": "Login pods crash-looping; volume at 100 percent",
        "error_logs": "No space left on device",
        "recent_changes": "",
    }
    inc = _analyze(client, headers, unrelated)["incident_id"]
    client.post(
        f"/api/incidents/{inc}/resolve",
        json={"root_cause": "Log rotation disabled", "solution": "Re-enabled logrotate", "outcome": "Disk usage normal"},
        headers=headers,
    )
    body = _analyze(client, headers, DEMO_2)
    assert all(m["service"] != "auth-service" for m in body["recall"]["memories"])
    assert "Log rotation disabled" not in fake_groq.of("analysis")[-1].user


def test_memory_is_isolated_per_user(client, fake_hindsight, fake_groq):
    alice = register(client, "alice")
    first = _analyze(client, alice, DEMO_1)
    client.post(f"/api/incidents/{first['incident_id']}/resolve", json=RESOLUTION_1, headers=alice)

    bob = register(client, "bob")
    bob_bank = bank_of(client, bob)
    fake_hindsight.calls.clear()
    body = _analyze(client, bob, DEMO_2)

    assert body["recall"]["status"] == "empty"
    assert RESOLUTION_1["root_cause"] not in fake_groq.of("analysis")[-1].user
    touched = {bank for method, bank in fake_hindsight.calls if bank}
    assert touched == {bob_bank}


def test_resolution_is_not_retained_twice(client, fake_hindsight):
    headers = register(client)
    inc = _analyze(client, headers, DEMO_1)["incident_id"]
    assert client.post(f"/api/incidents/{inc}/resolve", json=RESOLUTION_1, headers=headers).status_code == 200
    retains_before = [m for m, _ in fake_hindsight.calls].count("aretain")
    again = client.post(f"/api/incidents/{inc}/resolve", json=RESOLUTION_1, headers=headers)
    assert again.status_code == 409
    assert [m for m, _ in fake_hindsight.calls].count("aretain") == retains_before  # no second retain call
    history = client.get("/api/incidents", headers=headers).json()
    assert history[0]["retained_in_hindsight"] is True and history[0]["status"] == "resolved"
