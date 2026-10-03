from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from support.config import ROOT
from support.models import Category


class FactEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    category: Category
    topic: str = Field(min_length=1, max_length=100)
    status: str = Field(pattern=r"^(verified|unverified)$")
    source: str = Field(min_length=1, max_length=1000)
    checked_at: str
    answers: dict[str, str] = Field(default_factory=dict)
    values: dict = Field(default_factory=dict)

    @field_validator("checked_at")
    @classmethod
    def checked_timestamp(cls, value):
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp > datetime.now(UTC):
            raise ValueError(
                "Verification timestamp must include a timezone and cannot be in the future"
            )
        return value

    @field_validator("answers")
    @classmethod
    def languages(cls, value):
        if set(value) - {"en", "hi", "hinglish"}:
            raise ValueError("Answer language must be en, hi or hinglish")
        from support.guards import COMPLETED_ACTION, PROMISE

        if any(COMPLETED_ACTION.search(a) or PROMISE.search(a) for a in value.values()):
            raise ValueError("Policy wording contains a promise or completed-action claim")
        return value

    @field_validator("values")
    @classmethod
    def finite(cls, value):
        json.dumps(value, allow_nan=False)
        return value


class Facts:
    def __init__(self, path=None, *, items=None):
        self.path = path or ROOT / "facts.yaml"
        self.items = (
            items if items is not None else yaml.safe_load(self.path.read_text()).get("facts", [])
        )
        ids = [f["id"] for f in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Fact IDs must be unique")

    def verified(self, category: str | None = None) -> list[dict]:
        verified = []
        for fact in self.items:
            try:
                FactEntry.model_validate(fact)
            except ValueError:
                continue
            if fact["status"] == "verified" and (category is None or fact["category"] == category):
                verified.append(fact)
        return verified

    def refs(self) -> dict[str, dict]:
        return {f"fact:{f['id']}": f for f in self.verified()}

    def answer(self, category: str, language: str, topic: str) -> tuple[str, str] | None:
        # Match the approved topic explicitly; an unrelated category fact is unsafe.
        for fact in self.verified(category):
            if fact.get("topic") == topic and fact.get("answers", {}).get(language):
                return fact["answers"][language], f"fact:{fact['id']}"
        return None

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def save(self, contents: str, expected_fingerprint: str, reviewer: str, store):
        from support.config import require_dry_run
        from support.store import ConflictError

        require_dry_run()
        if not reviewer.strip():
            raise ValueError("Reviewer identifier is required")
        try:
            payload = yaml.safe_load(contents)
        except yaml.YAMLError as error:
            raise ValueError("Facts YAML could not be parsed") from error
        if (
            not isinstance(payload, dict)
            or set(payload) != {"facts"}
            or not isinstance(payload["facts"], list)
        ):
            raise ValueError("Expected a YAML object containing a facts list")
        entries = [FactEntry.model_validate(f).model_dump(mode="json") for f in payload["facts"]]
        if len({f["id"] for f in entries}) != len(entries):
            raise ValueError("Fact IDs must be unique")
        if self.fingerprint() != expected_fingerprint:
            raise ConflictError("Facts changed; reload before saving")
        from uuid import uuid4

        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                yaml.safe_dump({"facts": entries}, allow_unicode=True, sort_keys=False)
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.items = entries
        store.event(
            None,
            "facts_updated",
            {"reviewer": reviewer, "entries": len(entries), "sha256": self.fingerprint()},
        )


def ticket_facts(store, ticket_id: str) -> Facts:
    """Demo policy is isolated to registered synthetic examples, never real tickets."""
    from support.demo import demo_context

    context = demo_context(store, ticket_id)
    return Facts(items=context["facts"]) if context else Facts()
