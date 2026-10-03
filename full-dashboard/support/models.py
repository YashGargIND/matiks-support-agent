from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now() -> str:
    return datetime.now(UTC).isoformat()


class Category(StrEnum):
    ACCOUNT = "account"
    FEATURE = "feature"
    GAMEPLAY = "gameplay_bug"
    APP = "app_bug"
    STREAK = "streak"
    PURCHASE = "purchase"
    SAFETY = "dm_safety"
    CHEATING = "cheating"
    MERCH = "merch"
    OTHER = "other"


class ActionType(StrEnum):
    SEND_REPLY = "send_reply"
    RESTORE_STREAK = "restore_streak"
    PAID_RESTORE = "offer_paid_restore"
    TEMP_BAN = "temp_ban_messaging"
    CHEATING = "flag_cheating"
    PURCHASE = "escalate_purchase"
    VENDOR = "vendor_ticket"
    SLACK = "slack_message"
    PR = "draft_pr"
    FEATURE = "feature_to_pm"


class RawMessage(BaseModel):
    channel: str
    channel_ref: str
    created_at: str
    subject: str = Field(default="", max_length=1000)
    body: str = Field(max_length=100000)
    user_identifier: str = ""
    known_names: list[str] = Field(default_factory=list)
    attachments_meta: list[dict] = Field(default_factory=list)
    provenance: Literal["real", "synthetic"] = "real"

    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return parsed.astimezone(UTC).isoformat()


class Cohort(BaseModel):
    is_paying: bool | None = None
    streak_days: int | None = Field(default=None, ge=0)
    source_ref: str | None = None

    @property
    def is_power_user(self) -> bool | None:
        return None if self.streak_days is None else self.streak_days >= 100


class Evidence(BaseModel):
    id: str
    ticket_id: str
    run_id: str
    tool: str
    fetched_at: str = Field(default_factory=now)
    data: dict
    available: bool = True
    source: str


class Triage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    subcategory: str
    language: Literal["en", "hi", "hinglish"]
    sentiment: Literal["neutral", "positive", "negative"]
    urgency: Literal["normal", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    needs_investigation: bool


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    evidence_refs: list[str]


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ActionType
    payload: str  # JSON text, validated before insertion; strict SDK schema stays bounded.
    evidence_refs: list[str]
    reason: str


class Investigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str]
    root_cause_hypothesis: str | None
    proposed_actions: list[ProposedAction]
    user_reply_draft: str
    claims: list[Claim]
    internal_summary: str
    escalate: bool
    escalate_reason: str | None


class Ticket(BaseModel):
    id: str
    channel: str
    channel_ref: str
    created_at: str
    ingested_at: str = Field(default_factory=now)
    subject: str
    body: str
    user_identifier: str = ""
    matiks_user_id: str | None = None
    language: Literal["en", "hi", "hinglish"] = "en"
    status: Literal["open", "investigating", "drafted", "resolved", "escalated", "closed"] = "open"
    category: Category = Category.OTHER
    category_override: Category | None = None
    language_override: Literal["en", "hi", "hinglish"] | None = None
    subcategory: str = ""
    cohort: Cohort = Field(default_factory=Cohort)
    priority_score: float = 0
    priority_breakdown: dict[str, float] = Field(default_factory=dict)
    cluster_id: str | None = None
    confidence: float | None = None
    verdict: str | None = None
    root_cause_hypothesis: str | None = None
    resolution_type: Literal["auto", "assisted", "escalated"] | None = None
    assigned_to: str | None = None
    reply_draft: str = ""
    internal_summary: str = ""
    escalation_reason: str | None = None
    injection_flag: bool = False
    pii_reviewed: bool = False
    provenance: Literal["real", "synthetic"] = "real"
    evidence_refs: list[str] = Field(default_factory=list)
    drafted_at: str | None = None
    resolved_at: str | None = None
    approved_at: str | None = None
    closed_at: str | None = None
    active_run: str | None = None
    handling_seconds: float | None = None
    handling_mode: Literal["manual", "assisted"] | None = None
    revision: int = 0
