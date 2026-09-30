"""Long-term preference memory: explicit preferences persist, changes replace, cancellations remove,
and one-off instructions do not become permanent until repeated."""

from app.agent.preference_learner import _Decision, _Item, apply_decision
from app.hindsight.preferences import PREFERENCE_TAG, PROFILE_DOCUMENT_ID, PROMOTE_AFTER, PreferenceProfile
from tests.conftest import DEMO_1, bank_of, register
from tests.fake_secrets import FAKE_PASSWORD


def _analyze(client, headers, instructions=""):
    resp = client.post("/api/incidents/analyze", json={**DEMO_1, "additional_instructions": instructions}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _prefs_section(fake_groq) -> str:
    return fake_groq.of("analysis")[-1].user.split("<user_preferences>")[1].split("</user_preferences>")[0]


def test_explicit_preference_is_stored_and_applied_later(client, fake_hindsight, fake_groq):
    headers = register(client)
    body = _analyze(client, headers, "From now on, end every summary with OK")
    assert [c["action"] for c in body["preferences"]["changes"]] == ["added"]

    doc = fake_hindsight.docs(bank_of(client, headers))[PROFILE_DOCUMENT_ID]
    assert doc.update_mode == "replace" and doc.tags == [PREFERENCE_TAG]

    later = _analyze(client, headers)  # no instruction this time
    assert "End every summary with 'OK'." in _prefs_section(fake_groq)
    assert later["preferences"]["applied"] == ["End every summary with 'OK'."]


def test_changing_a_preference_replaces_the_old_one(client, fake_groq):
    headers = register(client)
    _analyze(client, headers, "From now on, end every summary with OK")
    body = _analyze(client, headers, "From now on, end every summary with DONE")
    assert body["preferences"]["changes"][0]["action"] == "updated"
    _analyze(client, headers)
    section = _prefs_section(fake_groq)
    assert "'DONE'" in section and "'OK'" not in section


def test_cancelled_preference_is_removed(client, fake_groq):
    headers = register(client)
    _analyze(client, headers, "From now on, end every summary with OK")
    body = _analyze(client, headers, "Stop ending summaries with OK")
    assert body["preferences"]["changes"][0]["action"] == "removed"
    _analyze(client, headers)
    assert "(none stored)" in _prefs_section(fake_groq)


def test_temporary_instruction_is_not_permanent_until_repeated(client, fake_groq):
    headers = register(client)
    for _ in range(PROMOTE_AFTER - 1):
        assert _analyze(client, headers, "Be brief this time")["preferences"]["changes"] == []
    _analyze(client, headers)
    assert "(none stored)" in _prefs_section(fake_groq)

    learned = _analyze(client, headers, "Be brief this time")
    assert learned["preferences"]["changes"][0]["action"] == "learned"


def test_current_instruction_is_sent_and_overrides_stored_preferences(client, fake_groq):
    headers = register(client)
    _analyze(client, headers, "From now on, end every summary with OK")
    _analyze(client, headers, "Answer in Spanish for this one")
    call = fake_groq.of("analysis")[-1]
    assert "<current_instructions>\nAnswer in Spanish for this one" in call.user
    assert "<current_instructions> override them" in call.system


def test_no_instruction_means_no_learning_call(client, fake_groq):
    headers = register(client)
    _analyze(client, headers)
    assert fake_groq.of("preferences") == []


def test_preference_learning_does_not_enter_incident_memory(client, fake_hindsight):
    headers = register(client)
    body = _analyze(client, headers, "From now on, end every summary with OK")
    auto = fake_hindsight.docs(bank_of(client, headers)).get(f"{body['incident_id']}:analysis")
    assert auto is None or "End every summary" not in auto.content


def test_apply_decision_ignores_unknown_actions_and_redacts():
    profile = PreferenceProfile()
    decision = _Decision(changes=[
        _Item(action="explode", key="x", preference="nope"),
        _Item(action="add", key="Language Choice!", preference=f"Respond in Spanish. password={FAKE_PASSWORD}"),
    ])
    changes = apply_decision(profile, decision)
    assert [c.key for c in changes] == ["language-choice"]
    assert FAKE_PASSWORD not in profile.preferences[0].preference
