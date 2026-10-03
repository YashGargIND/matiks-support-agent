"""Explicit synthetic examples exercising the production pipeline and guards.

Fixture evidence and policy can only be attached through this local registration.
Inbound ticket text cannot select or modify the trusted evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from support.models import RawMessage, Ticket, now
from support.privacy import normalize
from support.store import Store

SCENARIOS = {
    "dm-safety": (
        "DM harassment report",
        "I am reporting abusive direct messages from another player.",
    ),
    "dm-critical": ("Urgent DM safety report", "Someone sent a death threat in direct messages."),
    "merch-reply": ("Tshirt delivery question", "Where is my merch delivery?"),
    "merch-delayed": ("Tshirt delivery delayed", "My merch delivery still has not arrived."),
    "streak-restore": (
        "Streak broke after playing",
        "My streak broke on the disputed day despite completing play.",
    ),
    "streak-unclear": ("Streak shield question", "My streak broke and I think I had a shield."),
    "streak-paid": (
        "Streak restoration request",
        "My streak broke on a day I did not play. What are the options?",
    ),
    "feature-request": ("Feature request", "Please add a dark theme for evening practice."),
}


def signature(ticket: Ticket) -> str:
    return hashlib.sha256((ticket.subject + "\n" + ticket.body).encode()).hexdigest()


def table(store: Store):
    with store.connection() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS demo_examples (ticket_id TEXT PRIMARY KEY, scenario TEXT NOT NULL, signature TEXT NOT NULL, anchor TEXT NOT NULL)"
        )


def create_demo(store: Store, scenario: str, reviewer: str) -> Ticket:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown demo example")
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    from support.pipeline import rules
    from support.priority import rank

    subject, body = SCENARIOS[scenario]
    raw = RawMessage(
        channel="demo",
        channel_ref=uuid4().hex,
        created_at=now(),
        subject=subject,
        body=body,
        user_identifier="demo-player",
        provenance="synthetic",
    )
    ticket, mapping = normalize(raw)
    triage = rules(ticket)
    ticket.category, ticket.language = triage.category, triage.language
    rank(ticket, urgency=triage.urgency)
    store.ingest(ticket, mapping)
    table(store)
    with store.connection() as db:
        db.execute(
            "INSERT INTO demo_examples VALUES (?,?,?,?)",
            (ticket.id, scenario, signature(ticket), ticket.created_at),
        )
    store.event(
        ticket.id,
        "demo_example_created",
        {"reviewer": reviewer, "scenario": scenario, "synthetic": True, "policy": "demo-only"},
    )
    return ticket


def demo_context(store: Store, ticket_id: str) -> dict | None:
    ticket = store.get(ticket_id)
    if ticket.provenance != "synthetic" or ticket.channel != "demo":
        return None
    table(store)
    with store.connection() as db:
        row = db.execute("SELECT * FROM demo_examples WHERE ticket_id=?", (ticket_id,)).fetchone()
    if row is None or row["signature"] != signature(ticket) or row["scenario"] not in SCENARIOS:
        return None
    anchor = datetime.fromisoformat(row["anchor"])
    scenario = row["scenario"]
    incident = (anchor - timedelta(days=1)).date().isoformat()
    facts, tools = (
        [],
        {
            "resolve_user": {"matiks_user_id": "demo-player", "identity_verified": True},
            "get_user_cohort": {"user_id": "demo-player", "is_paying": True, "streak_days": 214},
        },
    )
    if scenario == "dm-safety":
        facts.append(
            {
                "id": "demo-severity2",
                "category": "dm_safety",
                "topic": "severity_2",
                "status": "verified",
                "source": "synthetic-demo-policy; not a Matiks policy",
                "checked_at": row["anchor"],
                "values": {"min_days": 7, "max_days": 30},
            }
        )
        tools["get_chat_history"] = {
            "reporter_id": "demo-player",
            "reported_id": "demo-reported-player",
            "severity": 2,
            "severity_verified": True,
            "violation_found": True,
            "reporter_aggressor": False,
            "policy_ref": "fact:demo-severity2",
            "excerpts": [
                {
                    "sender_id": "demo-reported-player",
                    "text": "You are worthless. Stop playing here.",
                    "synthetic": True,
                },
                {
                    "sender_id": "demo-player",
                    "text": "Please stop sending me these messages.",
                    "synthetic": True,
                },
            ],
        }
    if scenario.startswith("merch"):
        age = 20 if scenario == "merch-delayed" else 2
        active = {
            "order_id": "demo-active-order",
            "user_id": "demo-player",
            "item_type": "TSHIRT",
            "ordered_at": (anchor - timedelta(days=age)).isoformat(),
            "status": "processing",
            "order_confirmed": True,
            "delivery_confirmed": False,
            "delivered_at": None,
        }
        samples = [
            {
                **active,
                "order_id": f"demo-delivery-{i}",
                "user_id": "demo-population",
                "ordered_at": (anchor - timedelta(days=30)).isoformat(),
                "status": "delivered",
                "delivered_at": (anchor - timedelta(days=30 - (6 + i))).isoformat(),
                "delivery_confirmed": True,
            }
            for i in range(5)
        ]
        tools.update(
            {
                "get_merch_orders": {
                    "user_id": "demo-player",
                    "orders": [active],
                    "complete": True,
                },
                "get_merch_delivery_stats": {
                    "item_type": "TSHIRT",
                    "orders": samples,
                    "sample_description": "5 synthetic delivery records; demo only",
                },
            }
        )
    if scenario.startswith("streak"):
        tools["get_streak_history"] = {
            "user_id": "demo-player",
            "incident_date": incident,
            "timezone": "Asia/Kolkata",
            "date_range_complete": scenario != "streak-unclear",
            "streak_broke": True,
            "prior_streak": 214,
            "activity_recorded": scenario == "streak-restore",
            "shield_available_at_incident": 0,
            "shield_consumed": False,
            "auto_apply_shield_at_incident": True,
        }
        tools["search_gcp_logs"] = {
            "user_id": "demo-player",
            "incident_date": incident,
            "coverage_complete": scenario != "streak-unclear",
            "errors": [],
        }
        if scenario == "streak-paid":
            facts.append(
                {
                    "id": "demo-restore-price",
                    "category": "streak",
                    "topic": "restore_price",
                    "status": "verified",
                    "source": "synthetic-demo-price; not a Matiks price",
                    "checked_at": row["anchor"],
                    "values": {"amount": 250, "currency": "demo credits", "eligible": True},
                }
            )
    return {"scenario": scenario, "facts": facts, "tools": tools}


class DemoProvider:
    def __init__(self, context: dict):
        self.context = context

    def fetch(self, topic: str, user_id: str | None):
        if topic not in self.context["tools"]:
            raise LookupError("This demo snapshot does not contain that source")
        if topic != "resolve_user" and user_id != "demo-player":
            raise LookupError("Wrong demo user")
        return json.loads(
            json.dumps(self.context["tools"][topic])
        ), f"synthetic-demo:{self.context['scenario']}:{topic}"

    def close(self):
        pass
