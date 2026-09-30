"""Recall shaping (grouping, relevance filtering, trust ranking, explanations) and the memory-quality gate."""

from types import SimpleNamespace

import pytest

from app.agent.incident_agent import build_prompt
from app.agent.memory_extractor import filter_items, is_near_duplicate, looks_like_raw_log
from app.hindsight.client import (
    SOURCE_AUTO,
    SOURCE_RESOLUTION,
    group_recall_results,
    select_relevant,
    why_relevant,
)
from app.schemas import AutoMemoryItem, IncidentInput, RecallResult, RecalledFact, RecalledIncident
from tests.conftest import DEMO_2


@pytest.fixture
def incident(services) -> IncidentInput:
    return IncidentInput.model_validate(DEMO_2)


def _result(text, doc, score, source=SOURCE_RESOLUTION, service="payment-api", **meta):
    metadata = {"incident_id": doc, "service": service, "memory_source": source, "title": doc, **meta}
    return SimpleNamespace(text=text, type="world", metadata=metadata, document_id=doc,
                           scores=SimpleNamespace(reranker=score, final=score))


def _memory(doc, score, confirmed=True, service="payment-api"):
    return RecalledIncident(incident_id=doc, service=service, relevance_score=score, confirmed=confirmed,
                            facts=[RecalledFact(text=f"fact {doc}", score=score)])


def test_grouping_prefers_confirmed_details_and_dedupes_facts():
    results = [
        _result("Redis pool exhausted", "INC-1", 0.7, source=SOURCE_AUTO, root_cause="Suspected (unconfirmed): pool"),
        _result("Redis pool exhausted", "INC-1", 0.6, root_cause="Redis pool exhaustion"),
        _result("Pool raised to 150", "INC-1", 0.5, root_cause="Redis pool exhaustion"),
        _result("loose fact", None, 0.4),
    ]
    results[-1].metadata = {}
    grouped, loose = group_recall_results(results)
    assert len(grouped) == 1 and len(loose) == 1
    only = grouped[0]
    assert only.confirmed is True and only.root_cause == "Redis pool exhaustion"
    assert [f.text for f in only.facts] == ["Redis pool exhausted", "Pool raised to 150"]
    assert only.relevance_score == 0.7


def test_low_relevance_other_service_is_dropped(incident):
    kept = select_relevant(incident, [_memory("INC-A", 0.9), _memory("INC-B", 0.2, service="auth-service")])
    assert [m.incident_id for m in kept] == ["INC-A"]


def test_strong_other_service_match_is_kept(incident):
    kept = select_relevant(incident, [_memory("INC-B", 0.8, service="checkout-api")])
    assert [m.incident_id for m in kept] == ["INC-B"]


def test_same_service_below_floor_is_dropped(incident):
    assert select_relevant(incident, [_memory("INC-A", 0.01)]) == []


def test_confirmed_ranks_above_equally_relevant_hypothesis(incident):
    kept = select_relevant(incident, [_memory("HYP", 0.6, confirmed=False), _memory("CONF", 0.6)])
    assert [m.incident_id for m in kept] == ["CONF", "HYP"]


def test_much_more_relevant_hypothesis_can_still_rank_first(incident):
    kept = select_relevant(incident, [_memory("CONF", 0.3), _memory("HYP", 0.95, confirmed=False)])
    assert kept[0].incident_id == "HYP"


def test_recall_is_capped(incident, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("RECALL_MAX_INCIDENTS", "2")
    get_settings.cache_clear()
    assert len(select_relevant(incident, [_memory(f"INC-{i}", 0.5) for i in range(5)])) == 2


def test_why_relevant_explains_each_signal(incident):
    prev = RecalledIncident(
        service="payment-api", environment="production", title="Payment API Latency",
        error_signature="RedisConnectionPool: connection pool exhausted", recent_changes="Traffic increased after release",
        relevance_score=0.82,
    )
    reasons = why_relevant(incident, prev)
    assert "Same service: payment-api" in reasons
    assert "Same environment: production" in reasons
    assert any(r.startswith("Similar error signature") and "exhausted" in r for r in reasons)
    assert any(r.startswith("Similar recent change") and "traffic" in r for r in reasons)
    assert "Hindsight semantic relevance: 0.82" in reasons


def test_prompt_labels_trust_and_counts_facts(incident):
    recall = RecallResult(status="ok", message="", query="", memories=[_memory("A", 0.9), _memory("B", 0.8, confirmed=False)])
    prompt, n_facts = build_prompt(incident, recall)
    assert "CONFIRMED resolution" in prompt and "UNCONFIRMED hypothesis" in prompt
    assert n_facts == 2


def test_prompt_truncates_huge_logs(incident):
    big = incident.model_copy(update={"error_logs": "x" * 9000})
    prompt, _ = build_prompt(big, RecallResult(status="empty", message="", query=""))
    assert "[truncated" in prompt and len(prompt) < 6000


# ---------------------------------------------------------------- memory-quality gate


def test_near_duplicates_are_detected():
    assert is_near_duplicate("payment api redis pool exhausted under load", ["payment api redis pool exhausted under heavy load"])
    assert not is_near_duplicate("payment api redis pool exhausted", ["auth service disk full"])


def test_raw_log_lines_are_detected():
    assert looks_like_raw_log("2026-09-30 10:00:01 ERROR boom", "")
    assert looks_like_raw_log("[WARN] redis timeout", "")
    assert not looks_like_raw_log("On payment-api, Redis timeouts indicate pool pressure.", "")


def test_filter_items_applies_every_rule(incident):
    known = RecallResult(status="ok", message="", query="", memories=[
        RecalledIncident(facts=[RecalledFact(text="payment-api uses a Redis pool of 150 connections")])])
    candidates = [
        AutoMemoryItem(category="service_knowledge", content="payment-api uses a Redis pool of 150 connections."),  # known
        AutoMemoryItem(category="team_instruction", content="Always page the DBA first."),  # no user instruction given
        AutoMemoryItem(category="diagnostic_finding", content="2026-09-30 WARN redis timeout"),  # raw log
        AutoMemoryItem(category="root_cause", content="payment-api pool too small for 40% more traffic"),
        AutoMemoryItem(category="root_cause", content="payment-api pool too small for 40% more traffic."),  # dup in batch
        AutoMemoryItem(category="resolution", content="Raise payment-api pool; token=abc123def456"),
    ]
    items = filter_items(incident, candidates, known)
    assert [i.category for i in items] == ["root_cause", "resolution"]
    assert items[0].content.startswith("Suspected root cause (unconfirmed):")
    assert items[1].content.startswith("Recommended fix (unconfirmed):")
    assert "abc123def456" not in items[1].content


def test_team_instruction_kept_when_user_gave_one(incident):
    with_rule = incident.model_copy(update={"additional_instructions": "Never restart the primary DB during business hours"})
    items = filter_items(with_rule, [AutoMemoryItem(category="team_instruction", content="Never restart the primary DB during business hours.")],
                         RecallResult(status="empty", message="", query=""))
    assert len(items) == 1
