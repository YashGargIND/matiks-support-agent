from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from support.branches import delivery_stats, investigate
from support.contracts import DeliverySamples
from support.facts import Facts
from support.guards import check_output
from support.models import Category, Evidence
from support.pipeline import process


class EvidenceProvider:
    def __init__(self, facts: dict):
        self.facts = facts

    def fetch(self, topic, user_id):
        if topic == "resolve_user":
            return {"matiks_user_id": "user1", "identity_verified": True}, "synthetic:identity"
        if topic == "get_user_cohort":
            return {"user_id": "user1", "is_paying": True, "streak_days": 214}, "synthetic:cohort"
        if topic not in self.facts:
            raise LookupError
        return self.facts[topic], f"synthetic:{topic}"


def history(**changes):
    base = {
        "user_id": "user1",
        "incident_date": "2026-10-02",
        "timezone": "Asia/Kolkata",
        "date_range_complete": True,
        "streak_broke": True,
        "prior_streak": 214,
        "activity_recorded": False,
        "shield_available_at_incident": 0,
        "shield_consumed": False,
        "auto_apply_shield_at_incident": True,
    }
    return base | changes


def logs(**changes):
    return {
        "user_id": "user1",
        "incident_date": "2026-10-02",
        "coverage_complete": True,
        "errors": [],
    } | changes


def fact_registry(tmp_path, items=None):
    path = tmp_path / "facts.yaml"
    path.write_text(yaml.safe_dump({"facts": items or []}))
    return Facts(path)


@pytest.mark.parametrize("case", [{"activity_recorded": True}, {"shield_available_at_incident": 1}])
async def test_confirmed_streak_bug_proposes_free_restore(store, ticket, case):
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider({"get_streak_history": history(**case), "search_gcp_logs": logs()}),
    )
    assert outcome.verdict == "bug_confirmed"
    assert outcome.status == "drafted"  # human approval, never auto-restoration
    actions = store.rows("proposed_actions", ticket.id)
    restore = next(a for a in actions if a["type"] == "restore_streak")
    assert json.loads(restore["payload"])["target_streak"] == 214
    assert json.loads(restore["payload"])["free"] is True
    assert restore["status"] == "pending"
    assert store.rows("outbox") == []


@pytest.mark.parametrize(
    "change",
    [
        {"date_range_complete": False},
        {"incident_date": None},
        {"timezone": None},
        {"streak_broke": None},
        {"shield_available_at_incident": None},
        {"user_id": "other_user"},
        {"activity_recorded": None},
    ],
)
async def test_streak_missing_or_wrong_user_data_cannot_offer_restore(store, ticket, change):
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider({"get_streak_history": history(**change), "search_gcp_logs": logs()}),
    )
    assert outcome.status == "escalated"
    assert outcome.verdict == "data_unclear"
    assert {a["type"] for a in store.rows("proposed_actions")} == {"send_reply"}


async def test_current_inventory_is_not_historical_inventory(store, ticket):
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {
                "get_streak_history": history(shield_available_at_incident=None)
                | {"diagnostics": {"current_shields": 9}},
                "search_gcp_logs": logs(),
            }
        ),
    )
    assert outcome.verdict == "data_unclear"


async def test_no_errors_without_complete_coverage_is_not_no_bug(store, ticket):
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {"get_streak_history": history(), "search_gcp_logs": logs(coverage_complete=False)}
        ),
    )
    assert outcome.verdict == "data_unclear"


def test_paid_restore_requires_verified_price_and_complete_records(ticket, tmp_path):
    ticket.active_run, ticket.matiks_user_id, ticket.category = "run", "user1", Category.STREAK
    evidence = [
        Evidence(
            id="h",
            ticket_id=ticket.id,
            run_id="run",
            tool="get_streak_history",
            data=history(),
            source="synthetic",
        ),
        Evidence(
            id="l",
            ticket_id=ticket.id,
            run_id="run",
            tool="search_gcp_logs",
            data=logs(),
            source="synthetic",
        ),
    ]
    facts = fact_registry(tmp_path)
    result = investigate(ticket, evidence, facts)
    assert result.verdict == "not_a_bug" and result.escalate
    assert result.proposed_actions == []
    facts = fact_registry(
        tmp_path,
        [
            {
                "id": "price",
                "category": "streak",
                "topic": "restore_price",
                "status": "verified",
                "source": "synthetic-test-policy",
                "checked_at": "2026-10-03T04:00:00Z",
                "values": {"amount": 250, "currency": "pies", "eligible": True},
            }
        ],
    )
    result = investigate(ticket, evidence, facts)
    assert not result.escalate
    assert result.proposed_actions[0].type == "offer_paid_restore"
    assert "250 pies" in result.user_reply_draft
    assert check_output(result, evidence, facts, ticket.id, "run", ticket).passed
    result.user_reply_draft = result.user_reply_draft.replace("250", "999")
    assert not check_output(result, evidence, facts, ticket.id, "run", ticket).passed


def order(identifier: str, duration: float = 8, age: float = 2):
    start = datetime.now(UTC) - timedelta(days=age)
    return {
        "order_id": identifier,
        "user_id": "user1",
        "item_type": "TSHIRT",
        "ordered_at": start.isoformat(),
        "status": "processing",
        "order_confirmed": True,
        "delivered_at": (start + timedelta(days=duration)).isoformat(),
        "delivery_confirmed": True,
    }


def merch_provider(age=2, count=5, ambiguous=False):
    active = order("active", age=age) | {"delivered_at": None, "delivery_confirmed": False}
    samples = [
        order(str(i), duration=6 + i, age=30) | {"status": "delivered"} for i in range(count)
    ]
    return EvidenceProvider(
        {
            "get_merch_orders": {
                "user_id": "user1",
                "orders": [active, active | {"order_id": "other"}] if ambiguous else [active],
                "complete": True,
            },
            "get_merch_delivery_stats": {
                "item_type": "TSHIRT",
                "orders": samples,
                "sample_description": "synthetic-test-only",
            },
        }
    )


def test_delivery_stats_are_computed_and_exclude_unconfirmed_samples():
    samples = DeliverySamples.model_validate(merch_provider().facts["get_merch_delivery_stats"])
    assert delivery_stats(samples) == {
        "median_days": 8.0,
        "p90_days": 10.0,
        "mean_days": 8.0,
        "samples": 5,
    }
    samples.orders[0].delivery_confirmed = False
    assert delivery_stats(samples) is None


async def test_within_window_merch_auto_draft_is_not_sent(store, ticket):
    ticket.subject, ticket.body = "Tshirt order", "Where is my delivery?"
    store.save(ticket)
    outcome = await process(store, ticket.id, merch_provider())
    assert outcome.verdict == "merch_within_window"
    assert outcome.status == "resolved" and outcome.resolution_type == "auto"
    assert "8.0" in outcome.reply_draft and "10.0" in outcome.reply_draft
    assert store.rows("outbox") == []
    assert store.rows("llm_calls") == []


async def test_delayed_merch_proposes_vendor_inquiry_and_escalates(store, ticket):
    ticket.subject, ticket.body = "Tshirt order", "Where is my delivery?"
    store.save(ticket)
    outcome = await process(store, ticket.id, merch_provider(age=30))
    assert outcome.verdict == "merch_delayed" and outcome.status == "escalated"
    assert "vendor_ticket" in {a["type"] for a in store.rows("proposed_actions")}


@pytest.mark.parametrize("kwargs", [{"count": 4}, {"ambiguous": True}])
async def test_merch_ambiguity_and_small_samples_escalate(store, ticket, kwargs):
    ticket.subject, ticket.body = "Tshirt order", "Where is my delivery?"
    store.save(ticket)
    outcome = await process(store, ticket.id, merch_provider(**kwargs))
    assert outcome.verdict == "merch_unclear" and outcome.status == "escalated"


async def test_purchase_always_escalates_with_investigation(store, ticket):
    ticket.subject, ticket.body = "Purchase missing", "Payment charged but premium missing"
    store.save(ticket)
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {
                "get_purchases": {
                    "user_id": "user1",
                    "purchases": [{"item": "premium", "verification_status": "pending"}],
                    "complete": True,
                },
                "search_gcp_logs": logs(),
            }
        ),
    )
    assert outcome.verdict == "purchase_human_review" and outcome.status == "escalated"
    assert {a["type"] for a in store.rows("proposed_actions")} == {
        "escalate_purchase",
        "send_reply",
    }
