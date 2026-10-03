from __future__ import annotations

import json
import math
from datetime import datetime
from statistics import median

from pydantic import ValidationError

from support.config import read_config
from support.contracts import (
    ChatReview,
    CodeInvestigation,
    DeliverySamples,
    GameplayComparison,
    Identity,
    LogWindow,
    Orders,
    Owners,
    Purchases,
    StreakHistory,
)
from support.facts import Facts
from support.models import (
    ActionType,
    Category,
    Claim,
    Evidence,
    Investigation,
    ProposedAction,
    Ticket,
)

ACK = {
    "en": "Thanks for reporting this. Your report needs a support review.",
    "hi": "आपकी रिपोर्ट के लिए धन्यवाद। आगे जाँच के लिए इसे सपोर्ट समीक्षा की ज़रूरत है।",
    "hinglish": "Report ke liye shukriya. Isse support review ki zaroorat hai.",
}
STREAK_REPLIES = {
    "bug_confirmed": {
        "en": "The records show a streak discrepancy. A free restore is proposed here and is pending human approval; no restore has been performed.",
        "hi": "रिकॉर्ड में स्ट्रीक की विसंगति मिली है। यहाँ मुफ्त बहाली का प्रस्ताव मानव स्वीकृति के लिए लंबित है; अभी बहाली नहीं की गई है।",
        "hinglish": "Records mein streak discrepancy mili hai. Yahan free restore ka proposal human approval ke liye pending hai; abhi restore nahi hua hai.",
    },
    "not_a_bug": {
        "en": "The checked records show no qualifying play or available shield on the disputed day. A paid restore option is proposed at {amount} {currency}, pending human review; no charge or restore has occurred.",
        "hi": "जाँचे गए रिकॉर्ड में उस दिन योग्य खेल या उपलब्ध शील्ड नहीं मिली। {amount} {currency} पर भुगतान वाली बहाली का विकल्प मानव समीक्षा के लिए प्रस्तावित है; कोई शुल्क या बहाली नहीं हुई है।",
        "hinglish": "Checked records mein disputed day par qualifying play ya available shield nahi mila. {amount} {currency} ka paid restore option human review ke liye proposed hai; koi charge ya restore nahi hua hai.",
    },
}


def result(
    ticket: Ticket,
    verdict: str,
    refs: list[str],
    summary: str,
    *,
    draft: str | None = None,
    actions: list[ProposedAction] | None = None,
    confidence: float = 0,
    escalate: bool = True,
    reason: str | None = None,
    hypothesis: str | None = None,
) -> Investigation:
    return Investigation(
        verdict=verdict,
        confidence=confidence,
        evidence_refs=refs,
        root_cause_hypothesis=hypothesis,
        proposed_actions=actions or [],
        user_reply_draft=draft or ACK[ticket.language],
        claims=[Claim(text=draft, evidence_refs=refs)]
        if draft and draft != ACK[ticket.language]
        else [],
        internal_summary=summary,
        escalate=escalate,
        escalate_reason=reason if escalate else None,
    )


def proposal(kind: ActionType, payload: dict, refs: list[str], reason: str) -> ProposedAction:
    return ProposedAction(
        type=kind,
        payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        evidence_refs=refs,
        reason=reason,
    )


def records(evidence: list[Evidence], ticket: Ticket) -> dict[str, Evidence]:
    return {
        e.tool: e
        for e in evidence
        if e.available and e.ticket_id == ticket.id and e.run_id == ticket.active_run
    }


def parsed(data: dict[str, Evidence], topic: str, cls):
    if topic not in data:
        return None
    try:
        return cls.model_validate(data[topic].data)
    except ValidationError:
        return None


def streak(ticket: Ticket, data: dict[str, Evidence], facts: Facts) -> Investigation:
    history = parsed(data, "get_streak_history", StreakHistory)
    logs = parsed(data, "search_gcp_logs", LogWindow)
    refs = [data["get_streak_history"].id] if history else []
    unclear = result(
        ticket,
        "data_unclear",
        refs,
        "Streak evidence is incomplete.\nNo restore or paid offer is justified yet.",
        reason="Need disputed-day play, historical shield balance/setting, and log coverage",
    )
    if (
        not history
        or not ticket.matiks_user_id
        or history.user_id != ticket.matiks_user_id
        or not history.incident_date
        or not history.timezone
        or not history.date_range_complete
        or history.streak_broke is not True
    ):
        return unclear
    shield_failure = (
        history.shield_available_at_incident is not None
        and history.shield_available_at_incident > 0
        and history.auto_apply_shield_at_incident is True
    )
    if history.activity_recorded is True or shield_failure:
        if history.prior_streak is None or history.prior_streak == 0:
            return result(
                ticket,
                "bug_confirmed",
                refs,
                "Qualifying play or an eligible shield conflicts with a confirmed break.\nThe prior streak value needs verification before a restore proposal.",
                reason="Prior streak value is missing",
            )
        action = proposal(
            ActionType.RESTORE_STREAK,
            {
                "user_id": history.user_id,
                "incident_date": history.incident_date.isoformat(),
                "target_streak": history.prior_streak,
                "free": True,
                "approval_required": True,
            },
            refs,
            "Confirmed disputed-day discrepancy; pending human approval",
        )
        return result(
            ticket,
            "bug_confirmed",
            refs,
            "Confirmed streak discrepancy with disputed-day evidence.\nFree restoration proposed; human approval required.",
            draft=STREAK_REPLIES["bug_confirmed"][ticket.language],
            actions=[action],
            confidence=0.99,
            escalate=False,
        )
    if logs and logs.user_id == history.user_id and logs.incident_date == history.incident_date:
        refs.append(data["search_gcp_logs"].id)
    else:
        return unclear
    if (
        history.activity_recorded is not False
        or history.shield_available_at_incident != 0
        or history.shield_consumed is not False
        or not logs.coverage_complete
        or logs.errors
    ):
        return unclear
    prices = [f for f in facts.verified("streak") if f.get("topic") == "restore_price"]
    if not prices:
        return result(
            ticket,
            "not_a_bug",
            refs,
            "Complete records show no play, no shield, and no relevant errors.\nPaid-restore pricing/eligibility policy is unavailable.",
            reason="Verified restore price and eligibility are required",
        )
    policy = prices[0]
    values = policy.get("values", {})
    if (
        not isinstance(values.get("amount"), (int, float))
        or isinstance(values.get("amount"), bool)
        or values["amount"] < 0
        or not values.get("currency")
        or values.get("eligible") is not True
    ):
        return unclear
    refs.append(f"fact:{policy['id']}")
    action = proposal(
        ActionType.PAID_RESTORE,
        {
            "user_id": history.user_id,
            "incident_date": history.incident_date.isoformat(),
            "amount": values["amount"],
            "currency": values["currency"],
            "approval_required": True,
        },
        refs,
        "Complete records show no qualifying play or shield; verified price used",
    )
    draft = STREAK_REPLIES["not_a_bug"][ticket.language].format(
        amount=values["amount"], currency=values["currency"]
    )
    return result(
        ticket,
        "not_a_bug",
        refs,
        "Complete disputed-day evidence does not indicate a bug.\nPaid restore proposed from verified policy; human approval required.",
        draft=draft,
        actions=[action],
        confidence=0.98,
        escalate=False,
    )


def delivery_stats(samples: DeliverySamples, as_of: datetime | None = None) -> dict | None:
    days, seen = [], set()
    for order in samples.orders:
        if (
            order.item_type != samples.item_type
            or not order.order_confirmed
            or not order.delivery_confirmed
            or order.delivered_at is None
            or order.order_id in seen
            or (as_of is not None and order.delivered_at > as_of)
        ):
            continue
        duration = (order.delivered_at - order.ordered_at).total_seconds() / 86400
        if duration >= 0:
            days.append(duration)
            seen.add(order.order_id)
    if len(days) < read_config()["thresholds"]["min_delivery_samples"]:
        return None
    days.sort()
    return {
        "median_days": round(median(days), 1),
        "p90_days": round(days[math.ceil(len(days) * 0.9) - 1], 1),
        "mean_days": round(sum(days) / len(days), 1),
        "samples": len(days),
    }


def merch(ticket: Ticket, data: dict[str, Evidence], facts: Facts) -> Investigation:
    orders = parsed(data, "get_merch_orders", Orders)
    samples = parsed(data, "get_merch_delivery_stats", DeliverySamples)
    refs = [data["get_merch_orders"].id] if orders else []
    unclear = result(
        ticket,
        "merch_unclear",
        refs,
        "A confirmed, unambiguous order and delivery sample are needed.\nNo firm delivery date is inferred.",
        reason="Missing/ambiguous order or insufficient matching delivery history",
    )
    if (
        not orders
        or not ticket.matiks_user_id
        or orders.user_id != ticket.matiks_user_id
        or not orders.complete
    ):
        return unclear
    candidates = [
        o
        for o in orders.orders
        if o.order_confirmed
        and o.user_id == orders.user_id
        and o.status.lower() not in {"cancelled", "canceled", "delivered"}
    ]
    if len(candidates) != 1 or not samples or samples.item_type != candidates[0].item_type:
        return unclear
    stats = delivery_stats(
        samples, datetime.fromisoformat(data["get_merch_delivery_stats"].fetched_at)
    )
    if not stats:
        return unclear
    order = candidates[0]
    age = (
        datetime.fromisoformat(data["get_merch_orders"].fetched_at) - order.ordered_at
    ).total_seconds() / 86400
    if age < 0:
        return unclear
    refs.append(data["get_merch_delivery_stats"].id)
    if age > stats["p90_days"]:
        action = proposal(
            ActionType.VENDOR,
            {
                "order_id": order.order_id,
                "item_type": order.item_type,
                "age_days": round(age, 1),
                "recent_p90_days": stats["p90_days"],
                "approval_required": True,
            },
            refs,
            "Order age exceeds the matching recent-delivery p90; vendor review proposed",
        )
        return result(
            ticket,
            "merch_delayed",
            refs,
            f"Confirmed {order.item_type} order is older than recent p90 ({stats['p90_days']} days).\nVendor inquiry proposed; delivery timing needs human follow-up.",
            actions=[action],
            confidence=0.95,
            reason="Confirmed order is outside the observed delivery window",
        )
    drafts = {
        "en": "Your confirmed {item} order is within the recent delivery range. Based on {n} matching delivered orders, delivery usually takes around {median} days from order; the observed 90th percentile is {p90} days. This is an estimate, not a fixed delivery date.",
        "hi": "आपका पुष्ट {item} ऑर्डर हाल की डिलीवरी सीमा के भीतर है। समान प्रकार के {n} पूरे हुए ऑर्डर के आधार पर डिलीवरी में आमतौर पर ऑर्डर से लगभग {median} दिन लगते हैं; देखा गया 90वाँ प्रतिशतक {p90} दिन है। यह अनुमान है, निश्चित डिलीवरी तारीख नहीं।",
        "hinglish": "Aapka confirmed {item} order recent delivery range mein hai. {n} matching delivered orders ke basis par delivery usually order se lagbhag {median} days leti hai; observed 90th percentile {p90} days hai. Yeh estimate hai, fixed delivery date nahi.",
    }
    draft = drafts[ticket.language].format(
        item=order.item_type, n=stats["samples"], median=stats["median_days"], p90=stats["p90_days"]
    )
    return result(
        ticket,
        "merch_within_window",
        refs,
        f"One confirmed order; {stats['samples']} matching delivered samples.\nObserved median {stats['median_days']} days, p90 {stats['p90_days']} days.",
        draft=draft,
        confidence=0.99,
        escalate=False,
    )


def investigate(ticket: Ticket, evidence: list[Evidence], facts: Facts) -> Investigation | None:
    data = records(evidence, ticket)
    if ticket.category in {Category.GAMEPLAY, Category.APP}:
        code = parsed(data, "code_search", CodeInvestigation)
        if code and code.files and code.snippets and code.repo_head:
            refs = [data["code_search"].id]
            owner = parsed(data, "get_module_owner", Owners)
            logs = parsed(data, "search_gcp_logs", LogWindow)
            scoped_logs = (
                logs is not None and ticket.matiks_user_id and logs.user_id == ticket.matiks_user_id
            )
            if scoped_logs:
                refs.append(data["search_gcp_logs"].id)
            reviewers = []
            if (
                owner
                and owner.module == code.module
                and owner.sources
                and owner.role in {"global_code_reviewer", "path_code_reviewer"}
            ):
                refs.append(data["get_module_owner"].id)
                reviewers = owner.owners
            report = {
                "kind": "bug_investigation_context",
                "category": ticket.category.value,
                "module": code.module,
                "repo_head": code.repo_head,
                "working_tree_dirty": code.working_tree_dirty,
                "source_files": code.files,
                "source_spans": [
                    {k: s.get(k) for k in ("path", "start_line", "end_line", "sha256")}
                    for s in code.snippets
                ],
                "recent_commits": code.commits,
                "commits_prove_causation": False,
                "log_errors": logs.errors if scoped_logs else [],
                "log_coverage_complete": bool(scoped_logs and logs.coverage_complete),
                "runtime_cause_confirmed": False,
                "root_cause_hypothesis": None,
                "next_step": "Correlate the disputed event with runtime logs and reproduce before selecting a fix",
                "code_review_candidates": reviewers,
                "owner_role": owner.role if reviewers else "unknown",
                "product_owner_verified": False,
                "evidence_refs": refs,
                "coverage": code.coverage,
            }
            actions = (
                [
                    proposal(
                        ActionType.SLACK,
                        {
                            "report": report,
                            "github_reviewers": reviewers,
                            "slack_user_ids": [],
                            "destination": None,
                            "dispatch_allowed": False,
                            "approval_required": True,
                        },
                        refs,
                        "Repository review candidates identified; runtime cause is unconfirmed and human routing is required",
                    )
                ]
                if reviewers
                else []
            )
            return result(
                ticket,
                "bug_context_collected",
                refs,
                f"Source context: {code.module}; {len(code.files)} files and {len(code.commits)} recent commits, with causation unconfirmed.\nRuntime correlation and reproduction are required; code-review candidates: {', '.join(reviewers) or 'unresolved'}.",
                actions=actions,
                confidence=0,
                reason="Runtime cause and fix are unconfirmed; human investigation is required",
            )
    if ticket.category == Category.FEATURE:
        from support.guards import FEATURE_ACKS

        return result(
            ticket,
            "suggestion_recorded",
            [],
            "Suggestion recorded in the local queue.\nNo shipping decision or release date is implied.",
            draft=FEATURE_ACKS[ticket.language],
            confidence=1,
            escalate=False,
        )
    if ticket.category == Category.SAFETY:
        chat = parsed(data, "get_chat_history", ChatReview)
        if (
            not chat
            or chat.reporter_id != ticket.matiks_user_id
            or not chat.reported_id
            or chat.reported_id == chat.reporter_id
        ):
            return result(
                ticket,
                "safety_unclear",
                [],
                "Minimal verified chat evidence is unavailable or mis-scoped.\nImmediate human review is needed.",
                reason="Safety evidence is unavailable or ambiguous",
            )
        refs = [data["get_chat_history"].id]
        aggressor = " Reporter-aggressor flag is present." if chat.reporter_aggressor else ""
        if (
            not chat.severity_verified
            or chat.severity is None
            or not chat.excerpts
            or chat.violation_found is not True
        ):
            return result(
                ticket,
                "safety_human_review",
                refs,
                "Chat evidence needs severity/policy review."
                + aggressor
                + "\nNo ban duration is inferred.",
                reason="Verified violation and severity are required",
            )
        bands = read_config().get("severity_bands", {})
        policies = facts.refs()
        policy = policies.get(chat.policy_ref)
        policy_values = policy.get("values", {}) if policy else {}
        band = bands.get(str(chat.severity), bands.get(chat.severity))
        if band is None and policy:
            band = [policy_values.get("min_days"), policy_values.get("max_days")]
        if (
            chat.severity >= 4
            or not isinstance(band, list)
            or len(band) != 2
            or not policy
            or policy.get("category") != "dm_safety"
            or policy.get("topic") != f"severity_{chat.severity}"
        ):
            return result(
                ticket,
                "safety_human_review",
                refs,
                f"Reported severity: {chat.severity}."
                + aggressor
                + "\nNo validated temporary-ban policy/band is available.",
                reason="Human severity/policy review required",
            )
        low, high = band
        values = policy.get("values", {})
        if (
            type(low) is not int
            or type(high) is not int
            or low < 1
            or high < low
            or values.get("min_days") != low
            or values.get("max_days") != high
        ):
            return result(
                ticket,
                "safety_human_review",
                refs,
                "Severity band does not match verified policy.\nNo duration is proposed.",
                reason="Severity band and policy do not match",
            )
        refs.append(chat.policy_ref)
        action = proposal(
            ActionType.TEMP_BAN,
            {
                "reported_user_id": chat.reported_id,
                "severity": chat.severity,
                "days": low,
                "approval_required": True,
                "reporter_aggressor": chat.reporter_aggressor,
            },
            refs,
            "Verified violation; lower end of the approved severity band proposed for human review",
        )
        return result(
            ticket,
            "safety_ban_review",
            refs,
            f"Verified severity {chat.severity}; proposed {low}-day temporary messaging restriction within policy band {low}–{high}."
            + aggressor
            + "\nHuman approval is required; no user action has occurred.",
            actions=[action],
            confidence=0.95,
            reason="Every moderation action requires human review",
        )
    if ticket.category == Category.CHEATING:
        comparison = parsed(data, "get_gameplay_stats", GameplayComparison)
        if (
            not comparison
            or comparison.reporter_id != ticket.matiks_user_id
            or not comparison.reported_user_id
            or comparison.reported_user_id == comparison.reporter_id
            or not comparison.comparison_complete
            or comparison.baseline_sample_size
            < read_config()["thresholds"].get("min_gameplay_baseline", 20)
            or not comparison.baseline_source
        ):
            return result(
                ticket,
                "cheating_unclear",
                [],
                "A verified reported account and sufficient population comparison are unavailable.\nThe report alone is not proof of cheating.",
                reason="Verified population comparison is required",
            )
        refs = [data["get_gameplay_stats"].id]
        actions = (
            [
                proposal(
                    ActionType.CHEATING,
                    {
                        "reported_user_id": comparison.reported_user_id,
                        "baseline_sample_size": comparison.baseline_sample_size,
                        "anomalies": comparison.anomalies,
                        "approval_required": True,
                    },
                    refs,
                    "Population comparison contains anomalies; human investigation proposed, not a cheating verdict",
                )
            ]
            if comparison.anomalies
            else []
        )
        return result(
            ticket,
            "cheating_anomaly_review" if actions else "cheating_no_anomaly",
            refs,
            f"Population comparison: {comparison.baseline_sample_size} samples; {len(comparison.anomalies)} anomalies.\nAn anomaly is not proof of cheating; human review remains required.",
            actions=actions,
            confidence=0.8,
            reason="Human review of population evidence required",
        )
    if ticket.category == Category.ACCOUNT:
        identity = parsed(data, "resolve_user", Identity)
        if (
            not identity
            or not identity.identity_verified
            or not ticket.matiks_user_id
            or identity.matiks_user_id != ticket.matiks_user_id
        ):
            return result(
                ticket,
                "account_identity_unclear",
                [],
                "Account identity is unresolved.\nNo account steps or changes are proposed.",
                reason="Unambiguous account identity is required",
            )
        topic = "deletion_steps" if ticket.subcategory == "deletion" else "login_steps"
        if topic == "deletion_steps" and not identity.contact_verified:
            return result(
                ticket,
                "account_identity_unclear",
                [data["resolve_user"].id],
                "Account is resolved but the requesting contact is unverified.\nDeletion requests require human identity review.",
                reason="Deletion requester contact is unverified",
            )
        policies = [
            f
            for f in facts.verified("account")
            if f.get("topic") == topic and f.get("answers", {}).get(ticket.language)
        ]
        if len(policies) != 1:
            return result(
                ticket,
                "account_policy_unclear",
                [data["resolve_user"].id],
                "Account resolved; verified answer is unavailable or ambiguous.\nNo account mutation is proposed.",
                reason="Verified account instructions are required",
            )
        policy = policies[0]
        methods = policy.get("values", {}).get("login_methods")
        if topic == "login_steps" and (
            not methods or not set(identity.login_methods).intersection(methods)
        ):
            return result(
                ticket,
                "account_policy_unclear",
                [data["resolve_user"].id],
                "Verified instructions do not establish the account's login method.\nHuman review is needed.",
                reason="Login method and policy do not match",
            )
        refs = [data["resolve_user"].id, f"fact:{policy['id']}"]
        return result(
            ticket,
            "account_verified_howto",
            refs,
            "Verified account instructions match the resolved identity.\nHow-to draft only; no account change.",
            draft=policy["answers"][ticket.language],
            confidence=0.99,
            escalate=False,
        )
    if ticket.category == Category.STREAK:
        return streak(ticket, data, facts)
    if ticket.category == Category.MERCH:
        return merch(ticket, data, facts)
    if ticket.category == Category.PURCHASE:
        purchases = parsed(data, "get_purchases", Purchases)
        if purchases and purchases.user_id == ticket.matiks_user_id:
            refs = [data["get_purchases"].id]
            counts = len(purchases.purchases)
            return result(
                ticket,
                "purchase_human_review",
                refs,
                f"Read {counts} purchase/verification records; inspect evidence for status and errors.\nPayment resolution and any refund need human review.",
                actions=[
                    proposal(
                        ActionType.PURCHASE,
                        {"user_id": purchases.user_id, "purchase_count": counts},
                        refs,
                        "Purchase issue requires human review",
                    )
                ],
                confidence=0.8,
                reason="Purchase branch always escalates",
            )
    return None


def independently_supported(
    result_: Investigation, ticket: Ticket, evidence: list[Evidence], facts: Facts
) -> bool:
    expected = investigate(ticket, evidence, facts)
    return (
        expected is not None
        and expected.user_reply_draft == result_.user_reply_draft
        and expected.verdict == result_.verdict
        and expected.evidence_refs == result_.evidence_refs
        and expected.proposed_actions == result_.proposed_actions
    )


def auto_allowed(ticket: Ticket, result_: Investigation) -> bool:
    return (
        (
            (ticket.category == Category.MERCH and result_.verdict == "merch_within_window")
            or (ticket.category == Category.ACCOUNT and result_.verdict == "account_verified_howto")
            or (ticket.category == Category.FEATURE and result_.verdict == "suggestion_recorded")
        )
        and not result_.escalate
        and not result_.proposed_actions
    )
