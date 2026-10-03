from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from support.api import app


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(store.path))
    monkeypatch.setenv("CLICKUP_API_TOKEN", "test-only-token")
    monkeypatch.setenv("CLICKUP_LIST_ID", "12345")
    with TestClient(app) as client:
        yield client


def clickup_registry(client):
    return next(
        item
        for item in client.get("/ui/settings").json()["registries"]["channels"]
        if item["id"] == "clickup"
    )


def test_clickup_sync_imports_once_with_audit_and_no_dispatch(client, store, monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "id": "form-1",
                        "date_created": "1791000000000",
                        "description": "Please add practice reminders",
                    }
                ]
            },
        )

    http_client = httpx.Client
    monkeypatch.setattr(
        "support.channels.clickup.httpx.Client",
        lambda **kwargs: http_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    assert clickup_registry(client)["available"] is True
    for inserted in (1, 0):
        response = client.post("/ui/channels/clickup/sync", json={"reviewer": "Tester"})
        assert response.status_code == 200
        assert response.json() == {
            "channel": "clickup",
            "inserted": inserted,
            "fetched": 1,
            "mode": "dry_run",
            "external_dispatch": False,
            "has_more": False,
        }
    assert len(store.tickets()) == 1
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.path == "/api/v2/list/12345/task" for request in requests)
    assert requests[1].url.params["date_created_gt"] == "1790999999999"
    reviews = [row for row in store.rows("events") if row["kind"] == "channel_sync_review"]
    assert len(reviews) == 2
    assert "Tester" in reviews[0]["data"]
    assert store.rows("outbox") == []
    assert store.rows("llm_calls") == []


@pytest.mark.parametrize("list_id", ["", "invalid-list"])
def test_clickup_missing_configuration_disables_sync(client, monkeypatch, list_id):
    monkeypatch.setenv("CLICKUP_LIST_ID", list_id)
    assert clickup_registry(client)["available"] is False
    response = client.post("/ui/channels/clickup/sync", json={"reviewer": "Tester"})
    assert response.status_code == 503
    assert "CLICKUP_LIST_ID" in response.json()["detail"]


def test_clickup_disabled_channel_cannot_sync(client, monkeypatch):
    monkeypatch.setattr(
        "support.ui_api.ConfigService.current",
        lambda _: (1, {"channels": {"clickup": {"enabled": False}}}),
    )
    response = client.post("/ui/channels/clickup/sync", json={"reviewer": "Tester"})
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


@pytest.mark.parametrize(
    "upstream_status,expected", [(401, 502), (403, 502), (429, 429), (500, 502)]
)
def test_clickup_error_is_redacted_and_checkpoint_preserved(
    client, store, monkeypatch, upstream_status, expected
):
    def fail(_self, _since):
        request = httpx.Request("GET", "https://api.clickup.com/api/v2/list/12345/task")
        response = httpx.Response(upstream_status, request=request, text="private-upstream-data")
        response.raise_for_status()

    monkeypatch.setattr("support.channels.clickup.ClickUpAdapter.fetch_new", fail)
    response = client.post("/ui/channels/clickup/sync", json={"reviewer": "Tester"})
    assert response.status_code == expected
    assert "private-upstream-data" not in response.text
    assert "test-only-token" not in response.text
    assert store.checkpoint("clickup") is None
    assert store.tickets() == []
    failures = [row for row in store.rows("events") if row["kind"] == "channel_sync_failed"]
    assert len(failures) == 1
    assert "private-upstream-data" not in failures[0]["data"]


def test_clickup_sync_requires_reviewer(client):
    assert client.post("/ui/channels/clickup/sync", json={}).status_code == 422


def test_clickup_full_batch_requests_another_sync(client, monkeypatch):
    monkeypatch.setattr(
        "support.ui_api.ingest",
        lambda store, adapter: {"channel": adapter.name, "inserted": 99, "fetched": 100},
    )
    response = client.post("/ui/channels/clickup/sync", json={"reviewer": "Tester"})
    assert response.status_code == 200
    assert response.json()["has_more"] is True
