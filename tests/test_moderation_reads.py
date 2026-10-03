from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from bson import ObjectId

from support.channels.in_app import InAppReportAdapter
from support.moderation import QUERY, connection_settings, conversation
from support.pipeline import ingest


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, fields):
        assert fields == [("reportedAt", 1), ("_id", 1)]
        return self

    def max_time_ms(self, timeout):
        assert timeout == 3000
        return self

    def limit(self, limit):
        assert limit == 100
        return self.rows


class Reader:
    def __init__(self, rows):
        self.rows, self.queries, self.closed = rows, [], False
        self.mapping = {
            "inapp_reports": {
                "projection": [
                    "_id",
                    "reporterId",
                    "reportedUserId",
                    "reportedAt",
                    "reasonKeys",
                    "additionalComments",
                    "status",
                ]
            }
        }

    def collection(self, name):
        assert name == "inapp_reports"
        return self

    def find(self, query, projection):
        self.queries.append(query)
        assert "proofImageURL" not in projection
        return Cursor(self.rows)

    def close(self):
        self.closed = True


def test_in_app_read_is_bounded_deduplicated_and_checkpointed_without_mutation(store, monkeypatch):
    monkeypatch.setenv("MONGO_SCHEMA_VERIFIED", "true")
    stamp = datetime.now(UTC)
    rows = [
        {
            "_id": ObjectId(),
            "reporterId": ObjectId(),
            "reportedUserId": ObjectId(),
            "reportedAt": stamp,
            "reasonKeys": ["harassment_bullying"],
            "status": "PENDING",
            "additionalComments": "Contact demo@example.com",
        }
        for _ in range(2)
    ]
    reader = Reader(rows)
    adapter = InAppReportAdapter(lambda: reader)
    assert ingest(store, adapter)["inserted"] == 2
    assert ingest(store, adapter)["inserted"] == 0
    assert len(store.tickets()) == 2 and reader.closed
    assert all(
        t.category == "dm_safety" and "demo@example.com" not in t.body for t in store.tickets()
    )
    assert json.loads(store.checkpoint("in_app")) == [stamp.isoformat(), str(rows[-1]["_id"])]
    assert "$or" in reader.queries[-1]
    assert store.rows("outbox") == []


def test_admin_reader_uses_only_existing_fixed_query_and_minimal_content(monkeypatch):
    monkeypatch.setenv("MATIKS_GRAPHQL_URL", "https://example.test/api")
    monkeypatch.setenv("MATIKS_ADMIN_READ_TOKEN", "synthetic-admin-token")
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert request.method == "POST"
        assert payload["query"] == QUERY
        assert "mutation" not in QUERY and "attachment" not in QUERY and "senderInfo" not in QUERY
        return httpx.Response(
            200,
            json={
                "data": {
                    "getAdminConversationHistory": {
                        "hasMore": False,
                        "messages": [
                            {
                                "_id": "m",
                                "sender": "reported",
                                "groupId": "g",
                                "content": "Synthetic message",
                                "createdAt": "2026-10-03T04:00:00Z",
                            }
                        ],
                    }
                }
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        "support.moderation.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = conversation("reporter", "reported")
    assert result["severity_verified"] is False and result["violation_found"] is None
    assert result["excerpts"][0]["text"] == "Synthetic message"
    assert seen[0]["variables"] == {"reporterId": "reporter", "reportedUserId": "reported"}


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "private provider details"}]},
        {
            "data": {
                "getAdminConversationHistory": {
                    "messages": [{"sender": "unrelated", "content": "Private"}]
                }
            }
        },
    ],
)
def test_admin_reader_fails_closed_on_auth_or_wrong_sender(monkeypatch, response):
    monkeypatch.setenv("MATIKS_GRAPHQL_URL", "https://example.test/api")
    monkeypatch.setenv("MATIKS_ADMIN_READ_TOKEN", "synthetic-admin-token")
    original_client = httpx.Client
    monkeypatch.setattr(
        "support.moderation.httpx.Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)), **kwargs
        ),
    )
    with pytest.raises((LookupError, ValueError)) as error:
        conversation("reporter", "reported")
    assert "private provider details" not in str(error.value)


def test_existing_client_environment_resolves_api_without_using_server_signing_secret(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text("MATIKS_ADMIN_READ_TOKEN=synthetic-session\n")
    (tmp_path / ".env.client").write_text("EXPO_PUBLIC_SERVER_HOST=example.test\n")
    (tmp_path / ".env.server").write_text("MAIN__AUTH__JWT_SECRET=unused-signing-secret\n")
    monkeypatch.setattr("support.moderation.ROOT", tmp_path)
    monkeypatch.delenv("MATIKS_GRAPHQL_URL", raising=False)
    monkeypatch.delenv("MATIKS_ADMIN_READ_TOKEN", raising=False)
    assert connection_settings() == ("https://example.test/api", "synthetic-session")


def test_tool_redaction_uses_one_private_reversible_mapping(store, ticket):
    first = store.redact_evidence(ticket.id, {"text": "Contact demo@example.com"})
    second = store.redact_evidence(
        ticket.id, {"text": "Contact demo@example.com or other@example.com"}
    )
    assert first["text"] in second["text"]
    with store.connection() as db:
        mapping = json.loads(
            db.execute("SELECT mapping FROM pii_vault WHERE ticket_id=?", (ticket.id,)).fetchone()[
                0
            ]
        )
    assert set(mapping.values()) == {"demo@example.com", "other@example.com"}
