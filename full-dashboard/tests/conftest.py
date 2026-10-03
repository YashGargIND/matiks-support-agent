from __future__ import annotations

import pytest

from support.models import RawMessage
from support.privacy import normalize
from support.store import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    for flag in ("SEND_MODE", "ACTION_MODE", "SLACK_POST_MODE"):
        monkeypatch.setenv(flag, "dry_run")
    monkeypatch.setenv("LLM_ENABLED", "false")
    return Store(tmp_path / "state" / "test.sqlite3")


@pytest.fixture
def ticket(store):
    raw = RawMessage(
        channel="test",
        channel_ref="one",
        created_at="2026-10-03T04:00:00+00:00",
        subject="Streak broke",
        body="My shield failed",
        provenance="synthetic",
    )
    result, mapping = normalize(raw)
    store.ingest(result, mapping)
    return result
