from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadContract(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Identity(ReadContract):
    matiks_user_id: str | None = None
    identity_verified: bool = False
    account_status: str | None = None
    login_methods: list[str] = Field(default_factory=list)
    contact_verified: bool = False


class CohortEvidence(ReadContract):
    user_id: str
    is_paying: bool | None = None
    streak_days: int | None = Field(default=None, ge=0)


class StreakHistory(ReadContract):
    user_id: str
    incident_date: date | None = None
    timezone: str | None = None
    date_range_complete: bool = False
    streak_broke: bool | None = None
    prior_streak: int | None = Field(default=None, ge=0)
    activity_recorded: bool | None = None
    shield_available_at_incident: int | None = Field(default=None, ge=0)
    shield_consumed: bool | None = None
    auto_apply_shield_at_incident: bool | None = None
    goodwill_used: bool | None = None
    diagnostics: dict = Field(default_factory=dict)


class LogWindow(ReadContract):
    user_id: str
    incident_date: date | None = None
    coverage_complete: bool = False
    errors: list[dict] = Field(default_factory=list)
    known_cause: str | None = None


class Order(ReadContract):
    order_id: str
    user_id: str
    item_type: str
    ordered_at: datetime
    status: str
    order_confirmed: bool
    delivered_at: datetime | None = None
    delivery_confirmed: bool = False

    @field_validator("ordered_at", "delivered_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Order timestamps must include a timezone")
        return value


class Orders(ReadContract):
    user_id: str
    orders: list[Order]
    complete: bool = False


class DeliverySamples(ReadContract):
    item_type: str
    orders: list[Order]
    sample_description: str


class Purchases(ReadContract):
    user_id: str
    purchases: list[dict]
    complete: bool = False


class ChatReview(ReadContract):
    reporter_id: str
    reported_id: str
    severity: int | None = Field(default=None, ge=0, le=4)
    policy_ref: str | None = None
    severity_verified: bool = False
    violation_found: bool | None = None
    reporter_aggressor: bool | None = None
    excerpts: list[dict] = Field(default_factory=list, max_length=10)


class GameplayComparison(ReadContract):
    reporter_id: str
    reported_user_id: str
    anomalies: list[dict]
    baseline_sample_size: int = Field(ge=0)
    baseline_source: str
    comparison_complete: bool = False


class CodeInvestigation(ReadContract):
    module: str | None = None
    files: list[str] = Field(default_factory=list)
    commits: list[dict] = Field(default_factory=list)
    hypothesis: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    known_issue_ref: str | None = None
    repo_head: str | None = None
    working_tree_dirty: bool = False
    snippets: list[dict] = Field(default_factory=list, max_length=5)
    search_terms: list[str] = Field(default_factory=list, max_length=12)
    coverage: str = "unknown"


class Owners(ReadContract):
    module: str
    owners: list[str]
    confidence: float = Field(ge=0, le=1)
    sources: list[dict]
    role: str = "unknown"
    contributors: list[dict] = Field(default_factory=list, max_length=10)


CONTRACTS = {
    "resolve_user": Identity,
    "get_user_cohort": CohortEvidence,
    "get_streak_history": StreakHistory,
    "search_gcp_logs": LogWindow,
    "get_merch_orders": Orders,
    "get_merch_delivery_stats": DeliverySamples,
    "get_purchases": Purchases,
    "get_chat_history": ChatReview,
    "get_gameplay_stats": GameplayComparison,
    "code_search": CodeInvestigation,
    "get_module_owner": Owners,
}
