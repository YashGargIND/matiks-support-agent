from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from statistics import median

from support.models import Ticket
from support.store import Store


def seconds(start: str, end: str | None) -> float | None:
    return (
        None
        if end is None
        else max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    )


def metrics(store: Store, tickets: list[Ticket] | None = None) -> dict:
    selected = store.tickets() if tickets is None else tickets
    ids = {t.id for t in selected}
    calls = [c for c in store.rows("llm_calls") if c["ticket_id"] in ids]
    resolved = [t for t in selected if t.status in {"resolved", "closed"} and t.resolved_at]
    costs_known = all(c["cost_usd"] is not None for c in calls)
    spend = sum(c["cost_usd"] or 0 for c in calls)
    draft_times = [seconds(t.ingested_at, t.drafted_at) for t in selected if t.drafted_at]
    resolution_times = [seconds(t.ingested_at, t.resolved_at) for t in resolved]
    events = [e for e in store.rows("events") if e["ticket_id"] in ids]
    checks = [json.loads(e["data"]) for e in events if e["kind"] == "fact_check"]
    handling = {
        mode: [
            t.handling_seconds
            for t in selected
            if t.handling_mode == mode and t.handling_seconds is not None
        ]
        for mode in ("manual", "assisted")
    }
    # Arrival-to-resolved is shown separately; historical ticket age is not claimed as AI speed.
    arrival_times = [seconds(t.created_at, t.resolved_at) for t in resolved]
    return {
        "tickets": len(selected),
        "statuses": dict(Counter(t.status for t in selected)),
        "real_tickets": sum(t.provenance == "real" for t in selected),
        "synthetic_tickets": sum(t.provenance == "synthetic" for t in selected),
        "spend_usd": spend if costs_known else None,
        "known_spend_usd": spend,
        "unknown_cost_calls": sum(c["cost_usd"] is None for c in calls),
        "cost_per_ticket": spend / len(selected) if selected and costs_known else None,
        "cost_per_resolved": spend / len(resolved) if resolved and costs_known else None,
        "zero_llm_percent": 100
        * sum(t.id not in {c["ticket_id"] for c in calls} for t in selected)
        / len(selected)
        if selected
        else None,
        "median_time_to_draft_seconds": median(draft_times) if draft_times else None,
        "median_ingest_to_resolved_seconds": median(resolution_times) if resolution_times else None,
        "median_arrival_to_resolved_seconds": median(arrival_times) if arrival_times else None,
        "handling_seconds": {
            mode: median(values) if values else None for mode, values in handling.items()
        },
        "handling_sample_sizes": {mode: len(values) for mode, values in handling.items()},
        "guard_catches": sum(not c["passed"] for c in checks),
        "injection_flags": sum(t.injection_flag for t in selected),
        "unknown_cohort": sum(
            t.cohort.is_paying is None or t.cohort.streak_days is None for t in selected
        ),
        "unavailable_tool_calls": sum(
            not c["available"] for c in store.rows("tool_calls") if c["ticket_id"] in ids
        ),
        "queries_overall": dict(Counter(t.category.value for t in selected)),
        "queries_paying": dict(
            Counter(t.category.value for t in selected if t.cohort.is_paying is True)
        ),
        "queries_power": dict(
            Counter(t.category.value for t in selected if t.cohort.is_power_user is True)
        ),
    }
