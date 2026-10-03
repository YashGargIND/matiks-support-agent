from __future__ import annotations

import json

from fastapi.testclient import TestClient

from support.api import app
from support.channels.file import FileAdapter
from support.models import RawMessage
from support.pipeline import ingest


def test_file_boundary_does_not_lose_same_timestamp_tickets(store, tmp_path):
    rows = [
        RawMessage(
            channel="discord",
            channel_ref=f"{i:04d}",
            created_at="2026-10-03T04:00:00Z",
            body="Feature request",
            provenance="synthetic",
        ).model_dump()
        for i in range(105)
    ]
    path = tmp_path / "export.json"
    path.write_text(json.dumps(rows))
    adapter = FileAdapter(path)
    assert ingest(store, adapter)["inserted"] == 100
    assert ingest(store, adapter)["inserted"] == 5
    assert ingest(store, adapter)["inserted"] == 0
    assert len(store.tickets()) == 105


def test_api_local_flow(store, ticket, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(store.path))
    with TestClient(app) as client:
        assert client.get("/health").json()["external_dispatch"] is False
        processed = client.post(f"/tickets/{ticket.id}/process").json()
        assert processed["status"] == "escalated"
        response = client.post(
            f"/tickets/{ticket.id}/approve",
            json={"reviewer": "local", "revision": processed["revision"], "handling_seconds": 5},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert client.get("/metrics").json()["statuses"]["resolved"] == 1
        assert client.get("/tickets/no-such-ticket/evidence").status_code == 404
