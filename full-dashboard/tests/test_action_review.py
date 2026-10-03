from __future__ import annotations

import json

import pytest

from support.actions import approve_action, approve_ticket
from support.facts import Facts
from support.guards import check_output
from support.models import ActionType, ProposedAction
from support.pipeline import fallback, process
from support.store import ConflictError
from tests.test_specialists import EvidenceProvider, history, logs


async def proposed_restore(store, ticket):
    outcome = await process(
        store,
        ticket.id,
        EvidenceProvider(
            {"get_streak_history": history(activity_recorded=True), "search_gcp_logs": logs()}
        ),
    )
    action = next(a for a in store.rows("proposed_actions") if a["type"] == "restore_streak")
    return outcome, action


async def test_reply_and_internal_approvals_are_separate_local_only(store, ticket):
    outcome, action = await proposed_restore(store, ticket)
    approve_ticket(store, outcome.id, "reviewer", outcome.revision)
    assert (
        next(a for a in store.rows("proposed_actions") if a["id"] == action["id"])["status"]
        == "pending"
    )
    current = store.get(outcome.id)
    approve_action(store, action["id"], "reviewer", current.revision)
    assert len(store.rows("outbox")) == 2
    assert all(a["mode"] == "dry_run" for a in store.rows("outbox"))
    approve_action(store, action["id"], "reviewer", current.revision)
    assert len(store.rows("outbox")) == 2


async def test_internal_approval_rejects_stale_and_tampered_proposals(store, ticket):
    outcome, action = await proposed_restore(store, ticket)
    with pytest.raises(ConflictError):
        approve_action(store, action["id"], "reviewer", outcome.revision - 1)
    with store.connection() as db:
        payload = json.loads(action["payload"])
        payload["target_streak"] = 99999
        db.execute(
            "UPDATE proposed_actions SET payload=? WHERE id=?", (json.dumps(payload), action["id"])
        )
    with pytest.raises(ValueError, match="differs"):
        approve_action(store, action["id"], "reviewer", outcome.revision)
    assert store.rows("outbox") == []


async def test_reinvestigation_invalidates_old_actions(store, ticket):
    outcome, action = await proposed_restore(store, ticket)
    current = await process(store, outcome.id)
    with pytest.raises(ValueError, match="current"):
        approve_action(store, action["id"], "reviewer", current.revision)


def test_safe_ack_cannot_smuggle_an_uncomputed_restore(ticket):
    candidate = fallback(ticket, "No evidence")
    candidate.proposed_actions = [
        ProposedAction(
            type=ActionType.RESTORE_STREAK,
            payload='{"target_streak":999}',
            evidence_refs=["fact:random"],
            reason="Pending review",
        )
    ]
    assert not check_output(candidate, [], Facts(), ticket.id, "run", ticket).passed
