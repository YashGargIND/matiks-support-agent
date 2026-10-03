from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from uuid import uuid4

from support.actions import propose
from support.branches import auto_allowed
from support.branches import investigate as investigate_branch
from support.channels.base import ChannelAdapter
from support.config import llm_enabled, read_config
from support.facts import ticket_facts
from support.guards import ACKS, CRITICAL_SAFETY, INJECTION, SAFETY, check_output
from support.models import (
    ActionType,
    Category,
    Cohort,
    Investigation,
    ProposedAction,
    Ticket,
    Triage,
    now,
)
from support.priority import rank
from support.store import ConflictError, Store
from support.tools import DataProvider, ToolHub

RULES = [
    (Category.PURCHASE, r"purchase|payment|charged|refund|subscription|खरीद|भुगतान|paise"),
    (Category.STREAK, r"streak|shield|स्ट्रीक|शील्ड"),
    (Category.MERCH, r"merch|t.?shirt|hoodie|cake|delivery|parcel|डिलीवरी|केक"),
    (Category.CHEATING, r"cheat|hacker|impossible score|धोखा"),
    (Category.ACCOUNT, r"login|log in|sign in|account|delete|otp|लॉगिन|खाता"),
    (Category.FEATURE, r"feature request|suggestion|please add|could you add|सुझाव|feature chahiye"),
    (Category.GAMEPLAY, r"game|puzzle|answer|score|खेल|पहेली"),
    (Category.APP, r"crash|bug|screen|loading|error|क्रैश|त्रुटि"),
]
BRANCH_TOOLS = {
    Category.ACCOUNT: ["resolve_user", "search_gcp_logs"],
    Category.STREAK: ["get_streak_history", "search_gcp_logs"],
    Category.PURCHASE: ["get_purchases", "search_gcp_logs"],
    Category.MERCH: ["get_merch_orders", "get_merch_delivery_stats"],
    Category.CHEATING: ["get_gameplay_stats"],
    Category.SAFETY: ["get_chat_history"],
    Category.GAMEPLAY: ["search_gcp_logs", "code_search", "get_module_owner"],
    Category.APP: ["search_gcp_logs", "code_search", "get_module_owner"],
    Category.FEATURE: ["code_search", "get_module_owner"],
    Category.OTHER: [],
}


def rules(ticket: Ticket) -> Triage:
    text = f"{ticket.subject}\n{ticket.body}"
    language = (
        "hi"
        if re.search(r"[\u0900-\u097f]", text)
        else "hinglish"
        if re.search(r"\b(?:mera|meri|nahi|hai|kya|kar|chahiye|paise|ho|gaya)\b", text, re.I)
        else "en"
    )
    category = (
        Category.SAFETY
        if SAFETY.search(text) or CRITICAL_SAFETY.search(text)
        else next((cat for cat, pattern in RULES if re.search(pattern, text, re.I)), Category.OTHER)
    )
    negative = bool(re.search(r"angry|ridiculous|terrible|frustrat|worst|बेकार|गुस्सा", text, re.I))
    return Triage(
        category=category,
        subcategory="deletion"
        if category == Category.ACCOUNT and re.search(r"delete|deletion|मिटा", text, re.I)
        else "",
        language=language,
        sentiment="negative" if negative else "neutral",
        urgency="critical" if CRITICAL_SAFETY.search(text) else "normal",
        confidence=0.0 if category == Category.OTHER else 0.65,
        needs_investigation=category != Category.FEATURE,
    )


def ingest(store: Store, adapter: ChannelAdapter) -> dict:
    checkpoint = store.checkpoint(adapter.name)
    messages = adapter.fetch_new(checkpoint)
    inserted = 0
    for raw in messages:
        ticket, mapping = adapter.normalize(raw)
        triage = rules(ticket)
        ticket.category, ticket.language = triage.category, triage.language
        ticket.subcategory = triage.subcategory
        ticket.injection_flag = bool(INJECTION.search(ticket.body + " " + ticket.subject))
        rank(ticket, urgency=triage.urgency, sentiment=triage.sentiment)
        inserted += int(store.ingest(ticket, mapping))
    # Advance only after the entire bounded batch commits. Duplicate retries are safe.
    next_checkpoint = adapter.checkpoint_after_fetch(messages)
    if next_checkpoint is not None:
        store.set_checkpoint(adapter.name, next_checkpoint)
    store.event(
        None, "ingest", {"channel": adapter.name, "inserted": inserted, "fetched": len(messages)}
    )
    return {"inserted": inserted, "fetched": len(messages), "channel": adapter.name}


def assign_cluster(store: Store, ticket: Ticket):
    config = read_config()
    candidates = [
        t
        for t in store.tickets()
        if t.id != ticket.id
        and t.category == ticket.category
        and t.status not in {"closed", "resolved"}
    ]
    best, score = None, 0
    # No cohort/identity evidence is shared across tickets through a cluster.
    for other in candidates:
        similarity = SequenceMatcher(
            None,
            (ticket.subject + " " + ticket.body).lower(),
            (other.subject + " " + other.body).lower(),
        ).ratio()
        if similarity > score:
            best, score = other, similarity
    ticket.cluster_id = (
        best.cluster_id or best.id
        if best and score >= config["thresholds"]["cluster_similarity"]
        else ticket.id
    )


def fallback(ticket: Ticket, reason: str) -> Investigation:
    return Investigation(
        verdict="needs_human_review",
        confidence=0,
        evidence_refs=ticket.evidence_refs,
        root_cause_hypothesis=None,
        proposed_actions=[],
        user_reply_draft=ACKS[ticket.language],
        claims=[],
        internal_summary=f"{ticket.category.value}: evidence is insufficient.\n{reason}",
        escalate=True,
        escalate_reason=reason,
    )


async def _process(
    store: Store,
    ticket_id: str,
    provider: DataProvider | None = None,
    expected_revision: int | None = None,
    reviewer: str | None = None,
) -> Ticket:
    ticket = store.get(ticket_id)
    if expected_revision is not None and ticket.revision != expected_revision:
        raise ConflictError("Ticket changed; refresh before investigating")
    if ticket.status in {"resolved", "closed"}:
        return ticket
    ticket.status, ticket.active_run = "investigating", uuid4().hex
    ticket.evidence_refs = []
    ticket.matiks_user_id, ticket.cohort = None, Cohort()
    ticket.injection_flag = bool(INJECTION.search(ticket.subject + " " + ticket.body))
    store.save(ticket)
    if reviewer:
        store.event(
            ticket.id, "human_investigate", {"reviewer": reviewer, "revision": expected_revision}
        )
    hub = ToolHub(store, ticket.id, ticket.active_run, provider)
    facts = ticket_facts(store, ticket.id)
    triage = rules(ticket)
    if triage.category != Category.SAFETY and ticket.category_override is not None:
        triage.category = ticket.category_override
    if ticket.language_override is not None:
        triage.language = ticket.language_override
    ticket.category, ticket.language, ticket.subcategory = (
        triage.category,
        triage.language,
        triage.subcategory,
    )
    if ticket.injection_flag:
        result = fallback(
            ticket, "Potential prompt injection; ticket text was not executed as instructions"
        )
    elif triage.category == Category.SAFETY and triage.urgency == "critical":
        result = fallback(
            ticket, "Critical safety keywords: immediate human escalation; no AI severity judgment"
        )
    else:
        resolution = hub.fetch("resolve_user")
        if resolution.available and resolution.data.get("identity_verified") is True:
            ticket.matiks_user_id = resolution.data.get("matiks_user_id")
        cohort = hub.fetch("get_user_cohort", ticket.matiks_user_id)
        if (
            cohort.available
            and ticket.matiks_user_id
            and cohort.data.get("user_id") == ticket.matiks_user_id
        ):
            ticket.cohort = Cohort(
                is_paying=cohort.data.get("is_paying"),
                streak_days=cohort.data.get("streak_days"),
                source_ref=cohort.id,
            )
        if llm_enabled() and (ticket.provenance == "synthetic" or ticket.pii_reviewed):
            try:
                from support.agents_flow import run_triage

                triage = await run_triage(store, ticket)
            except Exception as error:
                store.event(
                    ticket.id,
                    "model_failure",
                    {"step": "triage", "error_type": type(error).__name__},
                )
                triage.confidence = 0
        # Deterministic safety rules outrank the model classification.
        if rules(ticket).category == Category.SAFETY:
            triage.category = Category.SAFETY
        elif ticket.category_override is not None:
            triage.category = ticket.category_override
        if ticket.language_override is not None:
            triage.language = ticket.language_override
        ticket.category, ticket.subcategory, ticket.language = (
            triage.category,
            triage.subcategory,
            triage.language,
        )
        for topic in BRANCH_TOOLS[ticket.category]:
            hub.fetch(topic, ticket.matiks_user_id)
        available = [e for e in store.evidence_for(ticket.id, ticket.active_run) if e.available]
        ticket.evidence_refs = [e.id for e in available]
        deterministic = investigate_branch(ticket, available, facts)
        result = deterministic or fallback(
            ticket, "Required account, policy, or investigation data is unavailable"
        )
        if (
            deterministic is None
            and llm_enabled()
            and triage.confidence >= read_config()["thresholds"]["triage"]
            and (ticket.provenance == "synthetic" or ticket.pii_reviewed)
        ):
            try:
                from support.agents_flow import run_specialist

                result = await run_specialist(store, ticket, hub, facts)
            except Exception as error:
                store.event(
                    ticket.id,
                    "model_failure",
                    {"step": "specialist", "error_type": type(error).__name__},
                )
                result = fallback(
                    ticket, "Specialist failed or reached its limit; human review required"
                )
    check = check_output(
        result,
        store.evidence_for(ticket.id, ticket.active_run),
        facts,
        ticket.id,
        ticket.active_run,
        ticket,
    )
    store.event(
        ticket.id,
        "fact_check",
        {
            "passed": check.passed,
            "reasons": check.reasons,
            "claims_found": check.claims_found,
            "supported": check.supported,
            "downgrade": not check.passed,
        },
    )
    if not check.passed:
        result = fallback(
            ticket, "Fact checker withheld the candidate: " + "; ".join(check.reasons)
        )
    ticket.reply_draft, ticket.internal_summary = result.user_reply_draft, result.internal_summary
    ticket.verdict, ticket.root_cause_hypothesis = result.verdict, result.root_cause_hypothesis
    ticket.confidence, ticket.escalation_reason = result.confidence, result.escalate_reason
    ticket.status = "escalated" if result.escalate else "drafted"
    ticket.resolution_type = "escalated" if result.escalate else None
    ticket.drafted_at = now()
    if (
        check.passed
        and read_config().get("auto_resolve_safe_drafts")
        and result.confidence >= read_config()["thresholds"]["auto"]
        and auto_allowed(ticket, result)
    ):
        ticket.status, ticket.resolution_type = "resolved", "auto"
        ticket.resolved_at = ticket.drafted_at
    assign_cluster(store, ticket)
    size = 1 + sum(t.id != ticket.id and t.cluster_id == ticket.cluster_id for t in store.tickets())
    rank(ticket, size, triage.urgency, triage.sentiment)
    store.save(ticket)
    for action in result.proposed_actions:
        if action.type != ActionType.SEND_REPLY:
            propose(store, ticket.id, ticket.active_run, action)
    propose(
        store,
        ticket.id,
        ticket.active_run,
        ProposedAction(
            type=ActionType.SEND_REPLY,
            payload=json.dumps({"text": ticket.reply_draft}, ensure_ascii=False),
            evidence_refs=result.evidence_refs,
            reason="Checked draft; pending human approval in dry-run console",
        ),
    )
    store.event(
        ticket.id,
        "run_finished",
        {
            "run_id": ticket.active_run,
            "status": ticket.status,
            "injection_flag": ticket.injection_flag,
        },
    )
    return ticket


async def process(
    store: Store,
    ticket_id: str,
    provider: DataProvider | None = None,
    expected_revision: int | None = None,
    reviewer: str | None = None,
) -> Ticket:
    owned = None
    if provider is None:
        try:
            from support.data import configured_provider
            from support.demo import DemoProvider, demo_context

            context = demo_context(store, ticket_id)
            owned = DemoProvider(context) if context else configured_provider(store, ticket_id)
            provider = owned
        except Exception as error:
            store.event(ticket_id, "source_setup_failed", {"error_type": type(error).__name__})
    try:
        return await _process(store, ticket_id, provider, expected_revision, reviewer)
    finally:
        if owned is not None:
            owned.close()
