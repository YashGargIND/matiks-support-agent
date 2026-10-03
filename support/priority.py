from __future__ import annotations

from datetime import UTC, datetime

from support.config import read_config
from support.models import Category, Ticket


def rank(
    ticket: Ticket,
    cluster_size: int = 1,
    urgency: str = "normal",
    sentiment: str = "neutral",
    clock: datetime | None = None,
    weights: dict | None = None,
):
    weights = weights if weights is not None else read_config()["priority"]
    age = max(
        0,
        ((clock or datetime.now(UTC)) - datetime.fromisoformat(ticket.created_at)).total_seconds()
        / 3600,
    )
    breakdown = {"waiting_hours": min(age, weights["max_age"]) * weights["age_hour"]}
    if ticket.cohort.is_paying is True:
        breakdown["paying_user"] = weights["paying"]
    if ticket.cohort.is_power_user is True:
        breakdown["100_plus_day_streak"] = (
            weights["power_user"] + min(ticket.cohort.streak_days, 1000) * weights["streak_scale"]
        )
    if ticket.category == Category.PURCHASE:
        breakdown["purchase_issue"] = weights["purchase"]
    if ticket.category == Category.SAFETY:
        breakdown["safety_first"] = weights["safety"]
    if urgency in {"high", "critical"}:
        breakdown["urgency"] = weights["urgency"]
    if sentiment == "negative":
        breakdown["negative_sentiment"] = weights["negative_sentiment"]
    if cluster_size > 1:
        breakdown["cluster_size"] = min(cluster_size - 1, 20) * weights["cluster_member"]
    ticket.priority_breakdown = breakdown
    ticket.priority_score = round(sum(breakdown.values()), 2)
