from __future__ import annotations

import asyncio
import json
from datetime import datetime
from time import monotonic

import pandas as pd
import streamlit as st

from support.actions import approve_action, approve_ticket, reject_action
from support.channels.base import load_adapters
from support.config import llm_enabled
from support.facts import Facts
from support.metrics import metrics
from support.pipeline import ingest, process
from support.store import Store

st.set_page_config(page_title="Matiks Support", page_icon="🧠", layout="wide")
store = Store()
st.title("Matiks Support")
st.caption("DRY-RUN · Drafts and proposals only · No messages or system changes are sent")

with st.sidebar:
    st.header("Support workbench")
    mode = st.radio("View", ["Queue", "Impact dashboard", "Action outbox", "Facts registry"])
    manual = st.toggle("Manual mode — hide AI assistance")
    reviewer = st.text_input("Reviewer", value="local-reviewer")
    st.caption(
        "Model calls enabled" if llm_enabled() else "Model calls disabled · local rules only"
    )
    if st.button("Import configured channels"):
        adapters = load_adapters()
        if not adapters:
            st.info("Enable ClickUp/email adapters in config.yaml first.")
        for adapter in adapters:
            try:
                st.write(ingest(store, adapter))
            except Exception as error:
                st.error(f"{adapter.name}: {type(error).__name__}. Verify local configuration.")

all_tickets = store.tickets()
categories = st.sidebar.multiselect("Category", sorted({t.category.value for t in all_tickets}))
channels = st.sidebar.multiselect("Channel", sorted({t.channel for t in all_tickets}))
statuses = st.sidebar.multiselect(
    "Status", ["open", "investigating", "drafted", "resolved", "escalated", "closed"]
)
cohort = st.sidebar.selectbox("Cohort", ["All", "Paying", "100+ day streak", "Unknown"])
provenance = st.sidebar.selectbox("Dataset", ["Real", "Synthetic test cases", "All"])
date_range = st.sidebar.date_input("Arrival dates", value=(), key="date_filter")
selected = [
    t
    for t in all_tickets
    if (not categories or t.category.value in categories)
    and (not channels or t.channel in channels)
    and (not statuses or t.status in statuses)
    and (
        cohort == "All"
        or cohort == "Paying"
        and t.cohort.is_paying is True
        or cohort == "100+ day streak"
        and t.cohort.is_power_user is True
        or cohort == "Unknown"
        and (t.cohort.is_paying is None or t.cohort.streak_days is None)
    )
    and (
        provenance == "All"
        or provenance == "Real"
        and t.provenance == "real"
        or provenance == "Synthetic test cases"
        and t.provenance == "synthetic"
    )
    and (
        len(date_range) != 2
        or date_range[0] <= datetime.fromisoformat(t.created_at).date() <= date_range[1]
    )
]

if not all_tickets:
    st.info(
        "No tickets imported. Connect real ClickUp/email sources or import a local ticket export. Synthetic evaluation cases do not count as a real-data demo."
    )

if mode == "Queue":
    left, right = st.columns([1, 2], gap="large")
    with left:
        st.subheader(f"Priority queue · {len(selected)}")
        st.caption("Safety first, then verified paying/streak cohorts and waiting time.")
        if selected:
            picked = st.radio(
                "Ticket",
                [t.id for t in selected],
                format_func=lambda tid: next(
                    f"{i + 1}. {t.subject[:65]} · {t.priority_score:g}"
                    for i, t in enumerate(selected)
                    if t.id == tid
                ),
                label_visibility="collapsed",
            )
        else:
            picked = None
    with right:
        if picked:
            ticket = store.get(picked)
            timer_key = f"timer:{picked}:{manual}"
            st.session_state.setdefault(timer_key, monotonic())
            st.subheader(ticket.subject or "Untitled report")
            st.caption(
                f"{ticket.channel} · {ticket.language} · {ticket.status} · {ticket.provenance}"
            )
            st.write(ticket.body)
            st.caption(
                "Cohort unknown"
                if ticket.cohort.source_ref is None
                else f"Paying: {ticket.cohort.is_paying} · streak: {ticket.cohort.streak_days} days"
            )
            st.write("Priority reasons", ticket.priority_breakdown)
            if ticket.injection_flag:
                st.warning("Potential prompt injection flagged. The ticket is treated as data.")
            if not manual:
                if st.button(
                    "Investigate and draft", disabled=ticket.status in {"resolved", "closed"}
                ):
                    with st.spinner("Collecting evidence"):
                        asyncio.run(process(store, picked))
                    st.rerun()
                if ticket.internal_summary:
                    st.write(ticket.internal_summary)
                if ticket.verdict:
                    st.caption(f"Verdict: {ticket.verdict} · confidence: {ticket.confidence}")
                if ticket.escalation_reason:
                    st.warning(ticket.escalation_reason)
                with st.expander("Current investigation evidence"):
                    for evidence in store.evidence_for(picked, ticket.active_run):
                        st.caption(
                            f"{evidence.id} · {evidence.tool} · {'available' if evidence.available else 'unavailable'}"
                        )
                        st.json(evidence.data)
                with st.expander("Review redacted ticket for model use"):
                    st.caption(
                        "Regex does not reliably find every name/address. Remove remaining PII before marking reviewed. Tool evidence requires separate review before live integration."
                    )
                    redacted_body = st.text_area(
                        "Redacted body", ticket.body, key=f"redaction:{picked}:{ticket.revision}"
                    )
                    if st.button("Save reviewed redaction"):
                        ticket.body, ticket.pii_reviewed = redacted_body, True
                        store.save(ticket)
                        store.event(ticket.id, "pii_review", {"reviewed": True})
                        st.rerun()
            draft = st.text_area(
                "Reply draft — nothing is sent",
                value="" if manual else ticket.reply_draft,
                height=180,
                key=f"reply:{picked}:{ticket.revision}:{manual}",
            )
            if st.button(
                "Approve draft into local outbox",
                disabled=ticket.status in {"resolved", "closed"} or not draft.strip(),
            ):
                try:
                    ticket.reply_draft = draft
                    store.save(ticket)
                    approve_ticket(
                        store,
                        ticket.id,
                        reviewer,
                        ticket.revision,
                        monotonic() - st.session_state[timer_key],
                        "manual" if manual else "assisted",
                    )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
            if not manual:
                with st.expander("Proposed internal actions — approval is separate"):
                    for action in store.rows("proposed_actions", picked):
                        if action["type"] != "send_reply":
                            st.write(action["type"], action["status"])
                            st.json(json.loads(action["payload"]))
                            st.caption(action["reason"])
                            if st.button(
                                "Approve into local outbox",
                                key=f"approve:{action['id']}",
                                disabled=action["status"] != "pending"
                                or action["run_id"] != ticket.active_run,
                            ):
                                try:
                                    approve_action(store, action["id"], reviewer, ticket.revision)
                                    st.rerun()
                                except ValueError as error:
                                    st.error(str(error))
                            if st.button(
                                "Reject proposal",
                                key=action["id"],
                                disabled=action["status"] != "pending",
                            ):
                                reject_action(store, action["id"], reviewer)
                                st.rerun()
                            st.caption(
                                "Approval rechecks current evidence and policy. Only a local outbox record is created."
                            )

elif mode == "Impact dashboard":
    report = metrics(store, selected)
    columns = st.columns(5)
    columns[0].metric("Open", report["statuses"].get("open", 0))
    columns[1].metric("Draft ready", report["statuses"].get("drafted", 0))
    columns[2].metric("Resolved · dry-run", report["statuses"].get("resolved", 0))
    columns[3].metric("Escalated", report["statuses"].get("escalated", 0))
    columns[4].metric("Closed", report["statuses"].get("closed", 0))
    st.caption(
        "Resolved = a safe fact-checked auto draft or a locally approved draft. Replied-to-user count is zero: sending is disabled."
    )
    st.subheader("Top queries")
    for column, key, title in zip(
        st.columns(3),
        ("queries_overall", "queries_power", "queries_paying"),
        ("Overall", "100+ day streak", "Paying"),
        strict=True,
    ):
        column.write(title)
        if report[key]:
            column.bar_chart(pd.Series(report[key], name="Tickets"))
        else:
            column.caption("No verified data for this cohort")
    st.subheader("Cost and speed")
    st.write(
        {
            key: report[key]
            for key in (
                "spend_usd",
                "cost_per_ticket",
                "cost_per_resolved",
                "zero_llm_percent",
                "median_time_to_draft_seconds",
                "median_ingest_to_resolved_seconds",
                "median_arrival_to_resolved_seconds",
                "handling_seconds",
                "handling_sample_sizes",
            )
        }
    )
    st.caption(
        "Empty values mean no measurement. Historical arrival time and processing time are separate. Manual/assisted samples are observational unless matched by ticket complexity."
    )
    calls = [c for c in store.rows("llm_calls") if c["ticket_id"] in {t.id for t in selected}]
    if calls:
        st.dataframe(calls, hide_index=True, width="stretch")
    st.subheader("Honesty")
    st.write(
        {
            key: report[key]
            for key in (
                "guard_catches",
                "injection_flags",
                "unknown_cohort",
                "unavailable_tool_calls",
                "unknown_cost_calls",
                "real_tickets",
                "synthetic_tickets",
            )
        }
    )
    if selected:
        st.dataframe(
            [
                {
                    "category": t.category.value,
                    "confidence": t.confidence,
                    "resolution_type": t.resolution_type,
                    "escalation_reason": t.escalation_reason,
                    "cluster": t.cluster_id,
                }
                for t in selected
            ],
            hide_index=True,
            width="stretch",
        )

elif mode == "Facts registry":
    st.subheader("Verified answers and policies")
    st.caption(
        "Verify each source yourself before marking an entry verified. Unverified entries cannot support answers. Include approved wording for each supported language."
    )
    facts = Facts()
    fingerprint = facts.fingerprint()
    contents = st.text_area(
        "Facts YAML", facts.path.read_text(), height=450, key=f"facts:{fingerprint}"
    )
    reviewed = st.checkbox("I checked the sources, policy values and answer wording")
    if st.button("Save local facts registry", disabled=not reviewed):
        try:
            facts.save(contents, fingerprint, reviewer, store)
            st.success("Facts saved locally. Reinvestigate open tickets to use updated policies.")
        except ValueError as error:
            st.error(str(error))

else:
    st.subheader("Local outbox")
    st.caption("These records cannot dispatch replies or change Matiks systems.")
    st.dataframe(store.rows("outbox"), hide_index=True, width="stretch")
