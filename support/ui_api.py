"""Local review API. Every mutation remains a dry-run operation."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime
from statistics import mean
from typing import Literal
from uuid import uuid4

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from support.actions import approve_action, approve_ticket, reject_action
from support.config import ROOT, llm_enabled
from support.demo import create_demo
from support.facts import FactEntry, Facts
from support.metrics import metrics
from support.models import Category, Evidence, RawMessage, Ticket, now
from support.pipeline import ingest, process, rules
from support.priority import rank
from support.privacy import normalize
from support.settings_service import AppSettings, ConfigService, Person, SavedView, SecretProvider
from support.store import ConflictError, Store

router = APIRouter(prefix="/ui")
SAFETY = {"safe_mode": True, "external_dispatch": False, "data_access": "read_only"}


class Reviewed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=100, pattern=r"\S")


class Approval(Reviewed):
    revision: int = Field(ge=0)


class NewReport(Reviewed):
    subject: str = Field(default="", max_length=1000)
    body: str = Field(min_length=1, max_length=100000)
    user_identifier: str = Field(default="", max_length=300)
    language: Literal["en", "hi", "hinglish"] = "en"
    category: Category | None = None
    provenance: Literal["real", "synthetic"] = "real"


class TicketEdit(Approval):
    reply_draft: str | None = Field(default=None, max_length=12000)
    category: Category | None = None
    assigned_to: str | None = None
    status: Literal["open", "escalated", "closed"] | None = None
    escalation_reason: str | None = Field(default=None, max_length=1000)
    pii_reviewed: bool | None = None


class SettingsEdit(Reviewed):
    version: int = Field(ge=1)
    config: dict


class KnowledgeEdit(Reviewed):
    facts: list[FactEntry] = Field(max_length=200)
    fingerprint: str


class SafetyState(BaseModel):
    safe_mode: Literal[True] = True
    external_dispatch: Literal[False] = False
    data_access: Literal["read_only"] = "read_only"
    llm_enabled: bool
    real_data_model_policy: str = "Human PII review required before model use"


class OverviewResponse(BaseModel):
    tickets: list[Ticket]
    metrics: dict
    stats: dict[str, int | float | None]
    people: list[Person]
    saved_views: list[SavedView]
    sources: list[dict]
    safety: SafetyState
    generated_at: str


class EventRow(BaseModel):
    id: str
    ticket_id: str | None
    kind: str
    data: dict
    created_at: str


class ActionRow(BaseModel):
    id: str
    ticket_id: str
    run_id: str
    type: str
    payload: dict
    evidence_refs: list[str]
    reason: str
    status: str
    created_at: str
    approved_at: str | None
    reviewer: str | None
    mode: Literal["dry_run"]


class TicketDetailResponse(BaseModel):
    ticket: Ticket
    evidence: list[Evidence]
    actions: list[ActionRow]
    events: list[EventRow]
    tool_calls: list[dict]
    llm_calls: list[dict]
    fact_checks: list[dict]
    guard_note: str | None


class RegistryField(BaseModel):
    key: str
    label: str
    type: str
    options: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str | None = None
    readonly: bool = False


class Registry(BaseModel):
    id: str
    name: str
    status: str
    fields: list[RegistryField]
    available: bool
    reason: str | None = None
    last_check: str | None = None


class SettingsResponse(BaseModel):
    version: int
    config: AppSettings
    registries: dict[str, list[Registry]]
    secret_status: dict[str, Literal["set", "missing"]]
    safety: SafetyState
    history: list[dict]


class KnowledgeResponse(BaseModel):
    facts: list[FactEntry]
    fingerprint: str


class InsightsResponse(BaseModel):
    tickets: list[Ticket]
    metrics: dict
    daily: list[dict]
    cost_by_model: list[dict]
    escalation_reasons: list[dict]


class ProblemResponse(BaseModel):
    id: str
    title: str
    category: Category
    ticket_ids: list[str]
    ticket_count: int
    users_affected: int | None
    paying_users: int
    power_users: int
    unknown_users: int
    status: str
    owner: str | None
    summary: str
    root_cause_hypothesis: str | None
    confidence: float | None
    shared_reply: str | None
    language: str | None
    trend_percent: float | None = None


class ProblemDetailResponse(BaseModel):
    problem: ProblemResponse
    tickets: list[Ticket]
    evidence: list[Evidence]
    actions: list[ActionRow]


class PipelineStep(BaseModel):
    id: str
    label: str
    count: int | None
    description: str
    settings_section: str


class PipelineResponse(BaseModel):
    steps: list[PipelineStep]
    branches: list[PipelineStep]
    today: str
    safe_mode: Literal[True] = True


def safety_state():
    return {**SAFETY, "llm_enabled": llm_enabled()}


def selected(
    store: Store,
    person="everyone",
    start: date | None = None,
    end: date | None = None,
    provenance="real",
) -> list[Ticket]:
    return [
        t
        for t in store.tickets()
        if (person == "everyone" or t.assigned_to == person)
        and (provenance == "all" or t.provenance == provenance)
        and (start is None or datetime.fromisoformat(t.created_at).date() >= start)
        and (end is None or datetime.fromisoformat(t.created_at).date() <= end)
    ]


def public_rows(store: Store, table: str, ticket_id=None) -> list[dict]:
    rows = store.rows(table, ticket_id)
    for row in rows:
        for key in ("data", "payload", "evidence_refs", "args"):
            if key in row and isinstance(row[key], str):
                row[key] = json.loads(row[key])
    return rows


def get_ticket(store, ticket_id):
    try:
        return store.get(ticket_id)
    except KeyError:
        raise HTTPException(404, "Ticket not found") from None


def action_result(operation):
    try:
        return operation()
    except KeyError:
        raise HTTPException(404, "Record not found") from None
    except ConflictError as error:
        raise HTTPException(409, str(error)) from None
    except ValueError:
        raise HTTPException(
            422, "Review could not be saved. Check the draft, evidence and current revision."
        ) from None


@router.get("/overview", response_model=OverviewResponse)
def overview(
    person: str = "everyone",
    start: date | None = None,
    end: date | None = None,
    provenance: Literal["real", "synthetic", "all"] = "real",
):
    store = Store()
    tickets = selected(store, person, start, end, provenance)
    measured = metrics(store, tickets)
    _, cfg = ConfigService(store).current()
    resolved = [t for t in tickets if t.resolved_at]
    durations = [
        (
            datetime.fromisoformat(t.resolved_at) - datetime.fromisoformat(t.ingested_at)
        ).total_seconds()
        for t in resolved
    ]
    sources = []
    report_path = ROOT / "data/connection-checks.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    # Connection evidence is descriptive; credentials are never returned.
    for name, label in [
        ("mongo", "Matiks records"),
        ("clickup", "Support forms"),
        ("imap", "Support email"),
    ]:
        item = report.get(name, {})
        status = str(item.get("status", "unverified"))
        sources.append(
            {
                "id": name,
                "label": label,
                "status": "connected" if status.startswith("connected") else "unverified",
                "last_checked": report.get("checked_at"),
                "note": "Read-only connection; coverage is limited to the configured source.",
            }
        )
    return {
        "tickets": tickets,
        "metrics": measured,
        "people": cfg["people"],
        "saved_views": cfg["saved_views"],
        "sources": sources,
        "safety": safety_state(),
        "generated_at": now(),
        "stats": {
            "total": len(tickets),
            "open": sum(t.status not in {"resolved", "closed"} for t in tickets),
            "needs_person": sum(t.status == "escalated" for t in tickets),
            "ready_for_review": sum(t.status == "drafted" for t in tickets),
            "vip_waiting": sum(
                t.status not in {"resolved", "closed"}
                and (t.cohort.is_paying is True or t.cohort.is_power_user is True)
                for t in tickets
            ),
            "resolved_today": sum(
                datetime.fromisoformat(t.resolved_at).date() == datetime.now(UTC).date()
                for t in resolved
            ),
            "avg_resolution_seconds": mean(durations) if durations else None,
            "cost_per_resolved": measured["cost_per_resolved"],
        },
    }


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
def detail(ticket_id: str):
    store = Store()
    ticket = get_ticket(store, ticket_id)
    events = public_rows(store, "events", ticket_id)
    return {
        "ticket": ticket,
        "evidence": store.evidence_for(ticket_id, ticket.active_run),
        "actions": [
            a
            for a in public_rows(store, "proposed_actions", ticket_id)
            if a["run_id"] == ticket.active_run
        ],
        "events": events,
        "tool_calls": public_rows(store, "tool_calls", ticket_id),
        "llm_calls": public_rows(store, "llm_calls", ticket_id),
        "fact_checks": [e["data"] for e in events if e["kind"] == "fact_check"],
        "guard_note": next(
            (
                "The fact checker withheld an unsupported draft: "
                + "; ".join(e["data"].get("reasons", []))
                for e in reversed(events)
                if e["kind"] == "fact_check" and not e["data"].get("passed")
            ),
            None,
        ),
    }


@router.post("/reports", response_model=Ticket)
def create_report(request: NewReport):
    store = Store()
    raw = RawMessage(
        channel="console",
        channel_ref=uuid4().hex,
        created_at=now(),
        subject=request.subject,
        body=request.body,
        user_identifier=request.user_identifier,
        provenance=request.provenance,
    )
    ticket, mapping = normalize(raw)
    triage = rules(ticket)
    ticket.category = (
        triage.category
        if triage.category == Category.SAFETY
        else request.category or triage.category
    )
    ticket.language = request.language
    ticket.category_override, ticket.language_override = request.category, request.language
    rank(ticket, urgency=triage.urgency, sentiment=triage.sentiment)
    store.ingest(ticket, mapping)
    store.event(
        ticket.id,
        "report_created",
        {"reviewer": request.reviewer, "provenance": request.provenance},
    )
    return ticket


@router.post("/demo/{scenario}", response_model=Ticket)
def demo_report(scenario: str, request: Reviewed):
    return action_result(lambda: create_demo(Store(), scenario, request.reviewer))


@router.post("/tickets/{ticket_id}/process", response_model=Ticket)
async def investigate(ticket_id: str, request: Approval):
    try:
        return await process(
            Store(), ticket_id, expected_revision=request.revision, reviewer=request.reviewer
        )
    except KeyError:
        raise HTTPException(404, "Ticket not found") from None
    except ConflictError as error:
        raise HTTPException(409, str(error)) from None


@router.patch("/tickets/{ticket_id}", response_model=Ticket)
def edit_ticket(ticket_id: str, request: TicketEdit):
    def edit():
        store = Store()
        ticket = get_ticket(store, ticket_id)
        if ticket.revision != request.revision:
            raise ConflictError("Ticket changed; refresh before editing")
        fields = request.model_dump(exclude_unset=True, exclude={"reviewer", "revision"})
        if "category" in fields:
            if rules(ticket).category == Category.SAFETY and fields["category"] != Category.SAFETY:
                raise ValueError("Safety reports require individual safety review")
            ticket.active_run, ticket.evidence_refs = None, []
            ticket.verdict, ticket.confidence, ticket.reply_draft = None, None, ""
            ticket.category_override = fields["category"]
        if fields.get("assigned_to") and fields["assigned_to"] not in {
            p["id"] for p in ConfigService(store).current()[1]["people"]
        }:
            raise ValueError("Choose a configured owner")
        for field, value in fields.items():
            setattr(ticket, field, value)
        rank(ticket, urgency=rules(ticket).urgency)
        store.save(ticket)
        store.event(ticket.id, "human_edit", {"reviewer": request.reviewer, "fields": list(fields)})
        return ticket

    return action_result(edit)


@router.post("/tickets/{ticket_id}/approve", response_model=Ticket)
def review_reply(ticket_id: str, request: Approval):
    def approve():
        store = Store()
        approve_ticket(store, ticket_id, request.reviewer, request.revision)
        return store.get(ticket_id)

    return action_result(approve)


@router.post("/actions/{action_id}/approve")
def review_action(action_id: str, request: Approval):
    return action_result(
        lambda: approve_action(Store(), action_id, request.reviewer, request.revision)
    ) or {"mode": "dry_run", "external_dispatch": False}


@router.post("/actions/{action_id}/reject")
def decline_action(action_id: str, request: Reviewed):
    return action_result(lambda: reject_action(Store(), action_id, request.reviewer)) or {
        "status": "rejected"
    }


@router.get("/settings", response_model=SettingsResponse)
def settings():
    service = ConfigService()
    version, cfg = service.current()
    # Configuration options are introduced only once their runtime path is supported.
    registries = {
        "agents": [
            {
                "id": key,
                "name": key.replace("specialist:", "").replace("_", " ").title(),
                "status": "active",
                "fields": [],
                "available": False,
                "reason": "Runtime editing is being connected; current policy is shown read-only.",
            }
            for key in cfg["agents"]
        ],
        "connectors": [
            {
                "id": key,
                "name": key.title(),
                "status": "configured" if value["enabled"] else "not_configured",
                "fields": [],
                "available": False,
                "reason": "Use the verified environment connection for this demo.",
            }
            for key, value in cfg["connectors"].items()
        ],
        "channels": [
            {
                "id": key,
                "name": key.title(),
                "status": "enabled" if value["enabled"] else "disabled",
                "fields": [],
                "available": False,
                "reason": "Channel synchronization controls are being connected.",
            }
            for key, value in cfg["channels"].items()
        ],
    }
    registries["channels"].append(
        {
            "id": "in_app",
            "name": "In-app DM reports",
            "status": "manual_read_only",
            "fields": [],
            "available": True,
            "reason": "Fetch pending communication reports from the last seven days. Report creation and moderation stay in Matiks.",
        }
    )
    return {
        "version": version,
        "config": cfg,
        "registries": registries,
        "secret_status": SecretProvider().status(),
        "safety": safety_state(),
        "history": service.history(),
    }


class SyncResponse(BaseModel):
    channel: str
    inserted: int
    fetched: int
    mode: Literal["dry_run"] = "dry_run"
    external_dispatch: Literal[False] = False


@router.post("/channels/in_app/sync", response_model=SyncResponse)
def sync_reports(request: Reviewed):
    from support.channels.in_app import InAppReportAdapter

    store = Store()
    try:
        result = ingest(store, InAppReportAdapter())
    except Exception as error:
        store.event(
            None,
            "channel_sync_failed",
            {"channel": "in_app", "reviewer": request.reviewer, "error_type": type(error).__name__},
        )
        raise HTTPException(
            502, "The in-app report source could not be read; check the read-only Mongo connection."
        ) from None
    store.event(None, "channel_sync_review", {"channel": "in_app", "reviewer": request.reviewer})
    return result


@router.get("/knowledge", response_model=KnowledgeResponse)
def knowledge():
    facts = Facts()
    return {"facts": facts.items, "fingerprint": facts.fingerprint()}


@router.patch("/knowledge", response_model=KnowledgeResponse)
def edit_knowledge(request: KnowledgeEdit):
    def save():
        facts = Facts()
        facts.save(
            yaml.safe_dump(
                {"facts": [f.model_dump(mode="json") for f in request.facts]}, allow_unicode=True
            ),
            request.fingerprint,
            request.reviewer,
            Store(),
        )
        return {"facts": facts.items, "fingerprint": facts.fingerprint()}

    return action_result(save)


@router.get("/activity", response_model=list[EventRow])
def activity(person: str = "everyone", provenance: Literal["real", "synthetic", "all"] = "real"):
    store = Store()
    ids = {t.id for t in selected(store, person, provenance=provenance)}
    return sorted(
        [
            e
            for e in public_rows(store, "events")
            if e["ticket_id"] in ids or (e["ticket_id"] is None and person == "everyone")
        ],
        key=lambda e: e["created_at"],
        reverse=True,
    )


@router.get("/insights", response_model=InsightsResponse)
def insights(
    person: str = "everyone",
    start: date | None = None,
    end: date | None = None,
    provenance: Literal["real", "synthetic", "all"] = "real",
):
    store = Store()
    tickets = selected(store, person, start, end, provenance)
    ids = {t.id for t in tickets}
    calls = [c for c in store.rows("llm_calls") if c["ticket_id"] in ids]
    days = sorted({t.created_at[:10] for t in tickets})
    costs = [
        {
            "model": model,
            "cost_usd": sum(c["cost_usd"] or 0 for c in calls if c["model"] == model),
            "unknown_calls": sum(c["cost_usd"] is None for c in calls if c["model"] == model),
        }
        for model in sorted({c["model"] for c in calls})
    ]
    return {
        "tickets": tickets,
        "metrics": metrics(store, tickets),
        "daily": [
            {
                "date": day,
                "tickets": sum(t.created_at.startswith(day) for t in tickets),
                "resolved": sum(
                    bool(t.resolved_at and t.resolved_at.startswith(day)) for t in tickets
                ),
            }
            for day in days
        ],
        "cost_by_model": costs,
        "escalation_reasons": [
            {"reason": reason, "count": count}
            for reason, count in Counter(
                t.escalation_reason or "Review needed" for t in tickets if t.status == "escalated"
            ).items()
        ],
    }


def grouped_problems(tickets: list[Ticket]) -> list[dict]:
    clusters: dict[str, list[Ticket]] = {}
    for ticket in tickets:
        if ticket.cluster_id:
            clusters.setdefault(ticket.cluster_id, []).append(ticket)
    problems = []
    for identifier, members in clusters.items():
        if len(members) < 2:
            continue
        identities = {t.matiks_user_id for t in members if t.matiks_user_id}
        owners = {t.assigned_to for t in members}
        categories = {t.category for t in members}
        languages = {t.language for t in members}
        drafts = {t.reply_draft for t in members}
        compatible = len(categories) == len(languages) == len(drafts) == 1 and bool(
            members[0].reply_draft
        )
        problems.append(
            {
                "id": identifier,
                "title": members[0].subject or "Shared support issue",
                "category": members[0].category,
                "ticket_ids": [t.id for t in members],
                "ticket_count": len(members),
                "users_affected": len(identities) or None,
                "paying_users": len(
                    {
                        t.matiks_user_id
                        for t in members
                        if t.matiks_user_id and t.cohort.is_paying is True
                    }
                ),
                "power_users": len(
                    {
                        t.matiks_user_id
                        for t in members
                        if t.matiks_user_id and t.cohort.is_power_user is True
                    }
                ),
                "unknown_users": sum(t.matiks_user_id is None for t in members),
                "status": "resolved"
                if all(t.status in {"resolved", "closed"} for t in members)
                else "needs_review",
                "owner": next(iter(owners)) if len(owners) == 1 else None,
                "summary": f"{len(members)} reports share similar text. Account evidence remains specific to each report.",
                "root_cause_hypothesis": None,
                "confidence": None,
                # Bulk review stays unavailable until its atomic per-ticket guard is connected.
                "shared_reply": None,
                "language": members[0].language if compatible else None,
                "trend_percent": None,
            }
        )
    return problems


@router.get("/problems", response_model=list[ProblemResponse])
def problems(person: str = "everyone", provenance: Literal["real", "synthetic", "all"] = "real"):
    return grouped_problems(selected(Store(), person, provenance=provenance))


@router.get("/problems/{problem_id}", response_model=ProblemDetailResponse)
def problem_detail(
    problem_id: str,
    person: str = "everyone",
    provenance: Literal["real", "synthetic", "all"] = "real",
):
    store = Store()
    tickets = selected(store, person, provenance=provenance)
    problem = next((p for p in grouped_problems(tickets) if p["id"] == problem_id), None)
    if problem is None:
        raise HTTPException(404, "Problem not found in this view")
    members = [t for t in tickets if t.id in problem["ticket_ids"]]
    return {
        "problem": problem,
        "tickets": members,
        "evidence": [e for t in members for e in store.evidence_for(t.id, t.active_run)],
        "actions": [
            a
            for t in members
            for a in public_rows(store, "proposed_actions", t.id)
            if a["run_id"] == t.active_run
        ],
    }


@router.get("/pipeline", response_model=PipelineResponse)
def pipeline(person: str = "everyone", provenance: Literal["real", "synthetic", "all"] = "real"):
    store = Store()
    today = datetime.now(UTC).date().isoformat()
    tickets = selected(store, person, provenance=provenance)
    ids = {t.id for t in tickets}
    events = [
        e
        for e in public_rows(store, "events")
        if e["ticket_id"] in ids and e["created_at"].startswith(today)
    ]
    counts = Counter(e["kind"] for e in events)
    ingested = sum(t.ingested_at.startswith(today) for t in tickets)
    steps = [
        (
            "channels",
            "Reports received",
            ingested,
            "Reports added to the local queue today.",
            "channels",
        ),
        (
            "clean",
            "Clean and enrich",
            ingested,
            "Inbound personal details are redacted locally; unknown account facts stay unknown.",
            "sources",
        ),
        (
            "rules",
            "Safety rules and grouping",
            counts["run_finished"],
            "Mandatory safety rules outrank category choices and model predictions.",
            "safety",
        ),
        (
            "sorting",
            "Sorting agent",
            counts["run_finished"],
            "Completed investigations use verified cohort facts for priority.",
            "agents",
        ),
        (
            "specialists",
            "Specialist agents",
            counts["run_finished"],
            "Investigation completion includes deterministic paths; this count is not model calls.",
            "agents",
        ),
        (
            "fact_checker",
            "Fact checker",
            counts["fact_check"],
            "Independent evidence and policy checks run before drafting.",
            "knowledge",
        ),
        (
            "outcomes",
            "Review outcomes",
            counts["run_finished"],
            "Draft, local automatic resolution, or human escalation.",
            "agents",
        ),
        (
            "human_approval",
            "Human approval",
            counts["human_approval"] + counts["internal_approval"],
            "Replies and internal actions have separate human reviews.",
            "safety",
        ),
        (
            "outbox",
            "Safe-mode outbox",
            sum(
                o["ticket_id"] in ids and o["created_at"].startswith(today)
                for o in store.rows("outbox")
            ),
            "Local entries only; external execution is disabled.",
            "safety",
        ),
    ]
    finished = {e["ticket_id"] for e in events if e["kind"] == "run_finished"}
    return {
        "today": today,
        "steps": [
            {
                "id": identifier,
                "label": label,
                "count": count,
                "description": description,
                "settings_section": section,
            }
            for identifier, label, count, description, section in steps
        ],
        "branches": [
            {
                "id": c.value,
                "label": c.value.replace("_", " ").title(),
                "count": sum(t.id in finished and t.category == c for t in tickets),
                "description": "Reports with a completed investigation today. Evidence coverage is shown per report.",
                "settings_section": "agents",
            }
            for c in Category
        ],
    }


@router.patch("/settings", response_model=SettingsResponse)
def edit_settings(request: SettingsEdit):
    def save():
        service = ConfigService()
        _, existing = service.current()
        if any(
            request.config.get(key) != existing[key] for key in ("agents", "connectors", "channels")
        ):
            raise ValueError("Runtime connection editing is not available yet")
        service.save(request.config, request.version, request.reviewer)
        return settings()

    return action_result(save)


class ViewRequest(Reviewed):
    name: str = Field(min_length=1, max_length=80)
    filters: dict[str, str]


class PriorityPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: dict[str, float]


class QueuePreviewRow(BaseModel):
    id: str
    subject: str
    before: float
    after: float


class QueuePreview(BaseModel):
    tickets: list[QueuePreviewRow]


@router.post("/priority-preview", response_model=QueuePreview)
def preview_priority(request: PriorityPreview):
    store = Store()
    _, config = ConfigService(store).current()
    config["priority"] = request.priority
    try:
        AppSettings.model_validate(config)
    except ValueError:
        raise HTTPException(
            422, "Use finite, nonnegative weights and keep safety above all other cases."
        ) from None
    preview = []
    for original in selected(store):
        copy = original.model_copy(deep=True)
        triage = rules(copy)
        cluster_size = (
            sum(t.cluster_id == copy.cluster_id for t in store.tickets()) if copy.cluster_id else 1
        )
        rank(copy, cluster_size, triage.urgency, triage.sentiment, weights=request.priority)
        preview.append(
            {
                "id": copy.id,
                "subject": copy.subject,
                "before": original.priority_score,
                "after": copy.priority_score,
            }
        )
    return {"tickets": sorted(preview, key=lambda t: -t["after"])}


@router.post("/saved-views", response_model=SavedView)
def add_view(request: ViewRequest):
    def save():
        service = ConfigService()
        version, config = service.current()
        view = SavedView(id=uuid4().hex, name=request.name, filters=request.filters)
        config["saved_views"].append(view.model_dump())
        service.save(config, version, request.reviewer)
        return view

    return action_result(save)
