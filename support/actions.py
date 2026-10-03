from __future__ import annotations

import json
from uuid import uuid4

from support.config import require_dry_run
from support.models import ProposedAction, now
from support.store import ConflictError, Store


def propose(store: Store, ticket_id: str, run_id: str, action: ProposedAction) -> str:
    require_dry_run()
    ticket = store.get(ticket_id)
    if ticket.active_run != run_id:
        raise ValueError("Cannot attach a proposal to an inactive investigation")
    payload = json.loads(action.payload)
    if not isinstance(payload, dict):
        raise ValueError("Action payload must be a JSON object")
    from support.facts import ticket_facts
    from support.guards import COMPLETED_ACTION, PROMISE

    valid_refs = {e.id for e in store.evidence_for(ticket_id, run_id) if e.available} | set(
        ticket_facts(store, ticket_id).refs()
    )
    if set(action.evidence_refs) - valid_refs:
        raise ValueError("Proposal references unknown or stale evidence")
    if action.type != "send_reply" and not action.evidence_refs:
        raise ValueError("Internal proposals require independent evidence")
    if action.type == "send_reply" and payload.get("text") != ticket.reply_draft:
        raise ValueError("Reply proposal differs from current draft")
    if COMPLETED_ACTION.search(action.reason) or PROMISE.search(action.reason):
        raise ValueError("Proposal contains a promise or completed outcome")
    identifier = uuid4().hex
    with store.connection() as db:
        db.execute(
            "INSERT INTO proposed_actions (id,ticket_id,run_id,type,payload,evidence_refs,reason,created_at,mode) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                ticket_id,
                run_id,
                action.type.value,
                action.payload,
                json.dumps(action.evidence_refs),
                action.reason,
                now(),
                "dry_run",
            ),
        )
    return identifier


def approve_ticket(
    store: Store,
    ticket_id: str,
    reviewer: str,
    expected_revision: int,
    handling_seconds: float | None = None,
    mode: str = "assisted",
):
    """Approval creates a LOCAL outbox entry. It cannot dispatch anything."""
    require_dry_run()
    ticket = store.get(ticket_id)
    if not reviewer.strip():
        raise ValueError("Reviewer identifier is required")
    if ticket.revision != expected_revision:
        raise ConflictError("Ticket changed; refresh before approval")
    if ticket.status == "closed":
        raise ValueError("Reopen a closed ticket before reviewing a reply")
    with store.connection() as db:
        already_approved = db.execute(
            "SELECT 1 FROM outbox o JOIN proposed_actions a ON a.id=o.action_id WHERE o.ticket_id=? AND a.type='send_reply' LIMIT 1",
            (ticket_id,),
        ).fetchone()
    if already_approved:
        return
    if not ticket.reply_draft.strip():
        raise ValueError("Write a reply draft before approval")
    # Mandatory forbidden-outcome check applies to human-edited drafts, too.
    from support.guards import COMPLETED_ACTION, PROMISE

    if COMPLETED_ACTION.search(ticket.reply_draft) or PROMISE.search(ticket.reply_draft):
        raise ValueError(
            "Draft claims a completed action or promises an outcome. Edit before approval."
        )
    stamp = now()
    ticket.status, ticket.resolution_type = "resolved", "assisted"
    ticket.approved_at = ticket.resolved_at = stamp
    ticket.handling_seconds, ticket.handling_mode = handling_seconds, mode
    revision = ticket.revision
    ticket.revision += 1
    with store.connection() as db:
        cur = db.execute(
            "UPDATE tickets SET data=?,revision=? WHERE id=? AND revision=?",
            (ticket.model_dump_json(), ticket.revision, ticket.id, revision),
        )
        if cur.rowcount != 1:
            raise ConflictError("Ticket changed; refresh before approval")
        actions = db.execute(
            "SELECT * FROM proposed_actions WHERE ticket_id=? AND run_id=? AND status='pending'",
            (ticket_id, ticket.active_run),
        ).fetchall()
        # Approval of the draft does not implicitly approve a restore, ban, or refund.
        replies = [a for a in actions if a["type"] == "send_reply"]
        if not replies:
            action_id = uuid4().hex
            db.execute(
                "INSERT INTO proposed_actions (id,ticket_id,run_id,type,payload,evidence_refs,reason,status,created_at,approved_at,reviewer,mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action_id,
                    ticket_id,
                    ticket.active_run or "manual",
                    "send_reply",
                    json.dumps({"text": ticket.reply_draft}),
                    "[]",
                    "Human-approved draft",
                    "approved",
                    stamp,
                    stamp,
                    reviewer,
                    "dry_run",
                ),
            )
        else:
            action_id = replies[0]["id"]
            db.execute(
                "UPDATE proposed_actions SET status='approved',payload=?,approved_at=?,reviewer=? WHERE id=?",
                (json.dumps({"text": ticket.reply_draft}), stamp, reviewer, action_id),
            )
        db.execute(
            "INSERT INTO outbox VALUES (?,?,?,?,?,?)",
            (
                uuid4().hex,
                ticket_id,
                action_id,
                json.dumps({"text": ticket.reply_draft}),
                stamp,
                "dry_run",
            ),
        )
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uuid4().hex,
                ticket_id,
                "human_approval",
                json.dumps({"mode": mode, "revision": revision, "dry_run": True}),
                stamp,
            ),
        )


def reject_action(store: Store, action_id: str, reviewer: str):
    require_dry_run()
    if not reviewer.strip():
        raise ValueError("Reviewer identifier is required")
    with store.connection() as db:
        db.execute(
            "UPDATE proposed_actions SET status='rejected',reviewer=? WHERE id=? AND status='pending'",
            (reviewer, action_id),
        )


def approve_action(store: Store, action_id: str, reviewer: str, expected_revision: int):
    """Independently validate and approve an internal proposal into the LOCAL outbox."""
    require_dry_run()
    if not reviewer.strip():
        raise ValueError("Reviewer identifier is required")
    from support.branches import investigate
    from support.facts import ticket_facts
    from support.guards import check_output
    from support.models import Ticket

    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        action = db.execute("SELECT * FROM proposed_actions WHERE id=?", (action_id,)).fetchone()
        if action is None:
            raise KeyError(action_id)
        row = db.execute("SELECT data FROM tickets WHERE id=?", (action["ticket_id"],)).fetchone()
        ticket = Ticket.model_validate_json(row["data"])
        if ticket.revision != expected_revision:
            raise ConflictError("Ticket changed; refresh before approval")
        if action["type"] == "send_reply":
            raise ValueError("Approve reply drafts through the ticket review")
        if action["status"] == "approved":
            return
        if action["status"] != "pending" or action["run_id"] != ticket.active_run:
            raise ValueError("Only current, pending proposals can be approved")
        evidence = store.evidence_for(ticket.id, ticket.active_run)
        facts = ticket_facts(store, ticket.id)
        expected = investigate(ticket, evidence, facts)
        if (
            expected is None
            or not check_output(
                expected, evidence, facts, ticket.id, ticket.active_run, ticket
            ).passed
        ):
            raise ValueError("Evidence/policy cannot independently justify this action")
        matching = any(
            p.type.value == action["type"]
            and json.loads(p.payload) == json.loads(action["payload"])
            and p.evidence_refs == json.loads(action["evidence_refs"])
            and p.reason == action["reason"]
            for p in expected.proposed_actions
        )
        if not matching:
            raise ValueError("Proposal differs from independently checked evidence/policy")
        stamp = now()
        if ticket.status not in {"resolved", "closed"}:
            # Internal review never resolves the reply or claims execution.
            ticket.revision += 1
            db.execute(
                "UPDATE tickets SET data=?,revision=? WHERE id=?",
                (ticket.model_dump_json(), ticket.revision, ticket.id),
            )
        db.execute(
            "UPDATE proposed_actions SET status='approved',approved_at=?,reviewer=? WHERE id=?",
            (stamp, reviewer, action_id),
        )
        db.execute(
            "INSERT INTO outbox VALUES (?,?,?,?,?,?)",
            (uuid4().hex, ticket.id, action_id, action["payload"], stamp, "dry_run"),
        )
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uuid4().hex,
                ticket.id,
                "internal_approval",
                json.dumps({"type": action["type"], "reviewer": reviewer, "dry_run": True}),
                stamp,
            ),
        )
