from __future__ import annotations

import pytest
import yaml

from support.facts import Facts
from support.guards import check_output
from support.models import Category, Evidence
from support.pipeline import fallback, process
from support.store import ConflictError
from tests.test_specialists import EvidenceProvider, fact_registry


def fact(**changes):
    return {
        "id": "login",
        "category": "account",
        "topic": "login_steps",
        "status": "verified",
        "source": "synthetic-policy-only",
        "checked_at": "2026-10-03T04:00:00Z",
        "answers": {"en": "Use the login method linked to this account."},
        "values": {"login_methods": ["GOOGLE"]},
    } | changes


def registry(monkeypatch, tmp_path, items):
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump({"facts": items}))
    monkeypatch.setattr("support.facts.ROOT", tmp_path)
    return Facts()


def test_fact_editor_rejects_promises_future_dates_and_duplicate_ids(store, tmp_path):
    facts = fact_registry(tmp_path)
    for items in (
        [fact(answers={"en": "We will fix it tomorrow"})],
        [fact(checked_at="2035-01-01T00:00:00Z")],
        [fact(), fact()],
    ):
        with pytest.raises(ValueError):
            facts.save(yaml.safe_dump({"facts": items}), facts.fingerprint(), "reviewer", store)
    assert facts.items == []
    with pytest.raises(ValueError):
        facts.save("facts: [", facts.fingerprint(), "reviewer", store)


def test_fact_editor_logs_and_rejects_stale_changes(store, tmp_path):
    facts = fact_registry(tmp_path)
    fingerprint = facts.fingerprint()
    facts.save(yaml.safe_dump({"facts": [fact()]}), fingerprint, "reviewer", store)
    assert len(Facts(facts.path).verified()) == 1
    assert any(e["kind"] == "facts_updated" for e in store.rows("events"))
    with pytest.raises(ConflictError):
        facts.save("facts: []", fingerprint, "reviewer", store)


def test_invalid_or_unverified_entries_do_not_support_answers(tmp_path):
    facts = fact_registry(
        tmp_path, [fact(status="unverified"), fact(id="future", checked_at="2035-01-01T00:00:00Z")]
    )
    assert facts.verified() == []


class AccountProvider(EvidenceProvider):
    def __init__(self, method="GOOGLE", contact=True):
        super().__init__({})
        self.method, self.contact = method, contact

    def fetch(self, topic, user_id):
        if topic == "resolve_user":
            return {
                "matiks_user_id": "user1",
                "identity_verified": True,
                "contact_verified": self.contact,
                "login_methods": [self.method],
            }, "synthetic:identity"
        return super().fetch(topic, user_id)


async def test_verified_account_howto_can_auto_resolve_locally(
    monkeypatch, tmp_path, store, ticket
):
    registry(monkeypatch, tmp_path, [fact()])
    ticket.subject, ticket.body = "Login help", "I cannot log in"
    store.save(ticket)
    outcome = await process(store, ticket.id, AccountProvider())
    assert outcome.verdict == "account_verified_howto" and outcome.resolution_type == "auto"
    assert store.rows("outbox") == []


async def test_wrong_login_method_withholds_answer(monkeypatch, tmp_path, store, ticket):
    registry(monkeypatch, tmp_path, [fact()])
    ticket.subject, ticket.body = "Login help", "I cannot log in"
    store.save(ticket)
    outcome = await process(store, ticket.id, AccountProvider(method="APPLE"))
    assert outcome.status == "escalated"


async def test_deletion_requires_verified_request_contact(monkeypatch, tmp_path, store, ticket):
    registry(
        monkeypatch,
        tmp_path,
        [
            fact(
                topic="deletion_steps",
                answers={"en": "Open account settings to review the deletion instructions."},
            )
        ],
    )
    ticket.subject, ticket.body = "Delete account", "Please delete my account"
    store.save(ticket)
    outcome = await process(store, ticket.id, AccountProvider(contact=False))
    assert outcome.verdict == "account_identity_unclear" and outcome.status == "escalated"


def test_approved_wording_needs_matching_reference_and_category(ticket, tmp_path):
    facts = fact_registry(tmp_path, [fact()])
    ticket.active_run, ticket.category = "run", Category.ACCOUNT
    result = fallback(ticket, "review")
    result.user_reply_draft = fact()["answers"]["en"]
    assert not check_output(result, [], facts, ticket.id, "run", ticket).passed
    result.evidence_refs = ["fact:login"]
    assert check_output(result, [], facts, ticket.id, "run", ticket).passed
    ticket.category = Category.STREAK
    assert not check_output(result, [], facts, ticket.id, "run", ticket).passed


async def test_safety_needs_verified_severity_and_policy(store, ticket):
    ticket.subject, ticket.body = "Harassment report", "Someone sent abusive DMs"
    store.save(ticket)
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {
                "get_chat_history": {
                    "reporter_id": "user1",
                    "reported_id": "other",
                    "severity": 2,
                    "severity_verified": False,
                    "violation_found": True,
                    "excerpts": [{"text": "redacted excerpt"}],
                }
            }
        ),
    )
    assert outcome.status == "escalated" and outcome.priority_score >= 1000
    assert {a["type"] for a in store.rows("proposed_actions")} == {"send_reply"}


def test_safety_verified_band_proposes_lower_bound_and_rejects_tamper(
    monkeypatch, tmp_path, ticket
):
    from support.branches import investigate
    from support.config import read_config

    facts = fact_registry(
        tmp_path,
        [
            fact(
                id="severity2",
                category="dm_safety",
                topic="severity_2",
                answers={},
                values={"min_days": 3, "max_days": 7},
            )
        ],
    )
    config = read_config()
    config["severity_bands"] = {"2": [3, 7]}
    monkeypatch.setattr("support.branches.read_config", lambda: config)
    ticket.active_run, ticket.matiks_user_id, ticket.category = "run", "user1", Category.SAFETY
    evidence = [
        Evidence(
            id="chat",
            ticket_id=ticket.id,
            run_id="run",
            tool="get_chat_history",
            source="synthetic",
            data={
                "reporter_id": "user1",
                "reported_id": "other",
                "severity": 2,
                "severity_verified": True,
                "policy_ref": "fact:severity2",
                "violation_found": True,
                "reporter_aggressor": True,
                "excerpts": [{"text": "redacted"}],
            },
        )
    ]
    result = investigate(ticket, evidence, facts)
    assert result.verdict == "safety_ban_review" and result.escalate
    assert '"days": 3' in result.proposed_actions[0].payload
    assert check_output(result, evidence, facts, ticket.id, "run", ticket).passed
    result.proposed_actions[0].payload = result.proposed_actions[0].payload.replace(
        '"days": 3', '"days": 99'
    )
    assert not check_output(result, evidence, facts, ticket.id, "run", ticket).passed


@pytest.mark.parametrize(
    "size,complete,reporter,flag",
    [
        (2, True, "user1", False),
        (50, False, "user1", False),
        (50, True, "other", False),
        (50, True, "user1", True),
    ],
)
async def test_cheating_requires_scoped_complete_population_comparison(
    store, ticket, size, complete, reporter, flag
):
    ticket.subject, ticket.body = "Cheating report", "Impossible scores"
    store.save(ticket)
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {
                "get_gameplay_stats": {
                    "reporter_id": reporter,
                    "reported_user_id": "reported",
                    "anomalies": [{"metric": "solve_time", "value": 0.01}],
                    "baseline_sample_size": size,
                    "baseline_source": "synthetic",
                    "comparison_complete": complete,
                }
            }
        ),
    )
    assert outcome.status == "escalated"
    types = {a["type"] for a in store.rows("proposed_actions")}
    assert ("flag_cheating" in types) is flag
    assert "temp_ban_messaging" not in types
