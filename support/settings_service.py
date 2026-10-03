from __future__ import annotations

import json
import math
import os
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from support.config import ROOT, require_dry_run
from support.models import Category, now
from support.privacy import PATTERNS
from support.store import ConflictError, Store

MODELS = ["openai/gpt-4.1-mini", "openai/gpt-4.1"]
CHANNELS = {
    "clickup": "support.channels.clickup:ClickUpAdapter",
    "email": "support.channels.email:EmailAdapter",
    "file": "support.channels.file:FileAdapter",
}
SECRET_KEYS = [
    "OPENROUTER_API_KEY",
    "CLICKUP_API_TOKEN",
    "IMAP_USER",
    "IMAP_APP_PASSWORD",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "IMAP_REFRESH_TOKEN",
    "MONGO_URI_READONLY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "MODERATION_API_KEY",
    "MATIKS_ADMIN_READ_TOKEN",
    "SLACK_BOT_TOKEN",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSetting(StrictModel):
    enabled: bool = True
    model: str = "openai/gpt-4.1-mini"
    confidence_threshold: float = Field(default=0.8, ge=0.5, le=1)
    max_steps: int = Field(default=6, ge=1, le=12)
    instructions: str = Field(default="", max_length=12000)


class Person(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=80)
    categories: list[Category] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list, max_length=30)
    github_handle: str | None = None


class SavedView(StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    filters: dict = Field(default_factory=dict)


class AppSettings(StrictModel):
    agents: dict[str, AgentSetting]
    connectors: dict[str, dict]
    channels: dict[str, dict]
    thresholds: dict[str, float]
    priority: dict[str, float]
    people: list[Person] = Field(default_factory=list, max_length=100)
    saved_views: list[SavedView] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def safe_settings(self):
        for name, agent in self.agents.items():
            if agent.model not in MODELS:
                raise ValueError("Choose a configured model")
            if name in {"fact_checker", "safety_rules"} and not agent.enabled:
                raise ValueError("Fact checking and safety rules are locked on")
        if set(self.channels) != set(CHANNELS):
            raise ValueError("Unknown channel registry entry")
        if set(self.connectors) != {"mongo", "gcp", "moderation", "codebase", "slack"}:
            raise ValueError("Unknown connector registry entry")
        if (
            not 0.5 <= self.thresholds.get("triage", 0) <= 1
            or not 0.9 <= self.thresholds.get("auto", 0) <= 1
        ):
            raise ValueError("Review threshold must be .5–1; automatic threshold must be .9–1")
        if not 0 <= self.thresholds.get("cluster_similarity", -1) <= 1:
            raise ValueError("Problem similarity must be 0–1")
        if set(self.thresholds) != {
            "triage",
            "auto",
            "cluster_similarity",
            "min_delivery_samples",
            "min_gameplay_baseline",
        }:
            raise ValueError("Unknown review threshold")
        for key, minimum in (("min_delivery_samples", 5), ("min_gameplay_baseline", 20)):
            value = self.thresholds[key]
            if not math.isfinite(value) or value != int(value) or not minimum <= value <= 100:
                raise ValueError(
                    "Evidence sample counts must be whole numbers within supported bounds"
                )
        if set(self.priority) != {
            "paying",
            "power_user",
            "streak_scale",
            "age_hour",
            "max_age",
            "purchase",
            "urgency",
            "negative_sentiment",
            "cluster_member",
            "safety",
        }:
            raise ValueError("Unknown priority weight")
        if self.priority.get("safety", 0) < 1000 or any(
            not math.isfinite(v) or v < 0 for v in self.priority.values()
        ):
            raise ValueError(
                "Safety weight must remain at least 1000; weights must be finite and nonnegative"
            )
        weights = self.priority
        largest_non_safety = (
            weights["paying"]
            + weights["power_user"]
            + 1000 * weights["streak_scale"]
            + weights["max_age"] * weights["age_hour"]
            + weights["purchase"]
            + weights["urgency"]
            + weights["negative_sentiment"]
            + 20 * weights["cluster_member"]
        )
        if largest_non_safety >= weights["safety"]:
            raise ValueError("Safety must rank above every possible non-safety ticket")
        if len({p.id for p in self.people}) != len(self.people):
            raise ValueError("Person IDs must be unique")
        if len({v.id for v in self.saved_views}) != len(self.saved_views):
            raise ValueError("View IDs must be unique")

        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if any(
                        word in key.lower()
                        for word in (
                            "secret",
                            "password",
                            "api_key",
                            "refresh_token",
                            "access_token",
                            "uri",
                        )
                    ):
                        raise ValueError("Credentials belong in the environment")
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
            elif isinstance(value, str):
                secret = next(pattern for name, pattern in PATTERNS if name == "SECRET")
                if secret.search(value) or "mongodb://" in value or "mongodb+srv://" in value:
                    raise ValueError("Credentials belong in the environment")

        inspect(self.model_dump())
        return self


def defaults(base: dict) -> dict:
    agents = {"triage": AgentSetting(max_steps=2).model_dump()}
    agents.update({f"specialist:{c.value}": AgentSetting().model_dump() for c in Category})
    agents.update(
        {
            name: AgentSetting().model_dump()
            for name in ("fact_checker", "ownership", "safety_rules")
        }
    )
    for name, setting in agents.items():
        setting["model"] = base["models"][
            "triage"
            if name == "triage"
            else "fact_checker"
            if name == "fact_checker"
            else "specialist"
        ]
    views = [
        {"id": c.value, "name": label, "filters": {"category": c.value}}
        for c, label in [
            (Category.SAFETY, "Safety"),
            (Category.PURCHASE, "Payments"),
            (Category.STREAK, "Streaks"),
            (Category.MERCH, "Merch"),
            (Category.GAMEPLAY, "Bugs"),
        ]
    ]
    views.append({"id": "vip", "name": "VIP only", "filters": {"cohort": "vip"}})
    return {
        "agents": agents,
        "connectors": {
            "mongo": {
                "enabled": True,
                "database": None,
                "payments_database": None,
                "collections": [],
            },
            "gcp": {"enabled": False, "project": None},
            "moderation": {"enabled": False, "base_url": None},
            "codebase": {"enabled": True, "path": None},
            "slack": {"enabled": False, "sandbox_channel": None},
        },
        "channels": {
            "clickup": {
                "enabled": CHANNELS["clickup"] in base["channels"],
                "list_id": None,
                "initial_lookback_days": base.get("clickup_initial_lookback_days", 7),
            },
            "email": {
                "enabled": CHANNELS["email"] in base["channels"],
                "folder": None,
                "lookback_days": 7,
            },
            "file": {"enabled": False, "path": None},
        },
        "thresholds": base["thresholds"],
        "priority": base["priority"],
        "people": [],
        "saved_views": views,
    }


class SecretProvider:
    def status(self) -> dict[str, str]:
        return {key: "set" if os.getenv(key) else "missing" for key in SECRET_KEYS}


class ConfigService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()
        self.base = yaml.safe_load((ROOT / "config.yaml").read_text())
        with self.store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS settings_versions (version INTEGER PRIMARY KEY, config TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            if db.execute("SELECT count(*) FROM settings_versions").fetchone()[0] == 0:
                initial = AppSettings.model_validate(defaults(self.base)).model_dump(mode="json")
                db.execute(
                    "INSERT INTO settings_versions VALUES (1,?,?,?)",
                    (json.dumps(initial), "initial configuration", now()),
                )

    def current(self) -> tuple[int, dict]:
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM settings_versions ORDER BY version DESC LIMIT 1"
            ).fetchone()
        return row["version"], json.loads(row["config"])

    def save(self, config: dict, version: int, reviewer: str) -> tuple[int, dict]:
        require_dry_run()
        if not reviewer.strip():
            raise ValueError("Reviewer is required")
        try:
            validated = AppSettings.model_validate(config).model_dump(mode="json")
        except (ValidationError, ValueError):
            raise ValueError(
                "Invalid non-secret settings. Keep safety checks on and use the declared fields and ranges."
            ) from None
        expected_agents = set(defaults(self.base)["agents"])
        if set(validated["agents"]) != expected_agents:
            raise ValueError("Agent registry entries cannot be added or removed")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actual = db.execute("SELECT max(version) FROM settings_versions").fetchone()[0]
            if actual != version:
                raise ConflictError("Settings changed; reload before saving")
            stamp = now()
            db.execute(
                "INSERT INTO settings_versions VALUES (?,?,?,?)",
                (version + 1, json.dumps(validated), reviewer, stamp),
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (
                    uuid4().hex,
                    None,
                    "settings_updated",
                    json.dumps({"reviewer": reviewer, "version": version + 1}),
                    stamp,
                ),
            )
        return version + 1, validated

    def history(self) -> list[dict]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT version,reviewer,created_at FROM settings_versions ORDER BY version DESC LIMIT 30"
            ).fetchall()
        return [dict(row) for row in rows]

    def agent_versions(self, agent_id: str) -> list[dict]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM settings_versions ORDER BY version DESC LIMIT 30"
            ).fetchall()
        return [
            {
                "version": row["version"],
                "reviewer": row["reviewer"],
                "created_at": row["created_at"],
                "settings": json.loads(row["config"])["agents"][agent_id],
            }
            for row in rows
        ]

    def restore_agent(self, agent_id: str, target: int, version: int, reviewer: str):
        _, config = self.current()
        with self.store.connection() as db:
            row = db.execute(
                "SELECT config FROM settings_versions WHERE version=?", (target,)
            ).fetchone()
        if row is None:
            raise ValueError("Previous version not found")
        config["agents"][agent_id] = json.loads(row["config"])["agents"][agent_id]
        return self.save(config, version, reviewer)

    def effective(self) -> dict:
        _, settings = self.current()
        base = json.loads(json.dumps(self.base))
        base["channels"] = [
            CHANNELS[key] for key, cfg in settings["channels"].items() if cfg["enabled"]
        ]
        base["thresholds"], base["priority"] = settings["thresholds"], settings["priority"]
        base["models"]["triage"] = settings["agents"]["triage"]["model"]
        base["models"]["fact_checker"] = settings["agents"]["fact_checker"]["model"]
        base["clickup_initial_lookback_days"] = settings["channels"]["clickup"][
            "initial_lookback_days"
        ]
        base["_settings"] = settings
        return base
