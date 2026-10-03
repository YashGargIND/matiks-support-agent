from __future__ import annotations

import httpx

from support.channels.clickup import ClickUpAdapter, task_message
from support.channels.snapshot import GmailSnapshot
from support.guards import ACKS, PROMISE
from support.pipeline import ingest


def task(identifier="one", timestamp="1791000000000", **changes):
    return {
        "id": identifier,
        "name": "Form Submission",
        "date_created": timestamp,
        "text_content": "Please add a feature",
        "creator": {"username": "Employee", "email": "employee@example.com"},
        "list": {"id": "901611930428"},
        "custom_fields": [
            {"id": "dc7038b0-24fd-4767-a5eb-f5d5f1d1ea17", "value": "reporter@example.com"},
            {"id": "068dd0b6-7886-4775-aa84-fc0a36009a26", "value": "reporter_handle"},
            {"id": "a5e3ce45-2379-4f5d-945b-b2dc9db92917", "value": 1},
        ],
    } | changes


def test_clickup_uses_verified_form_fields_not_creator():
    raw = task_message(task())
    assert raw.user_identifier == "reporter@example.com"
    assert "Feature suggestion" in raw.subject
    assert raw.body == "Please add a feature"
    raw = task_message(task(list={"id": "unmapped"}))
    assert raw.user_identifier == ""


def test_clickup_more_than_100_same_timestamp_reports_do_not_starve(monkeypatch, store):
    pages = []

    def respond(request):
        page = int(request.url.params["page"])
        pages.append(page)
        assert request.method == "GET" and request.url.params["reverse"] == "true"
        assert request.url.params["include_closed"] == "false"
        assert "date_created_gt" in request.url.params
        data = [task(str(i)) for i in range(page * 100, min((page + 1) * 100, 205))]
        return httpx.Response(200, json={"tasks": data})

    client_type = httpx.Client
    monkeypatch.setattr(
        "support.channels.clickup.httpx.Client",
        lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setenv("CLICKUP_API_TOKEN", "test-never-sent")
    monkeypatch.setenv("CLICKUP_LIST_ID", "901611930428")
    adapter = ClickUpAdapter()
    for _ in range(4):
        ingest(store, adapter)
    assert len(store.tickets()) == 205
    assert pages == [0, 0, 1, 2]


def test_gmail_snapshot_is_support_scoped_and_trims_quoted_campaigns(store):
    message = {
        "id": "gmail-one",
        "internal_date": "1791000000000",
        "payload": {
            "mime_type": "text/plain",
            "headers": [
                {"name": "From", "value": "Test Sender <sender@example.com>"},
                {"name": "To", "value": "support@matiks.com"},
                {"name": "Subject", "value": "Streak help"},
            ],
            "body": {
                "content": "Test Sender needs streak help\nOn Fri, 2 Oct Support wrote:\nPurchase our product"
            },
        },
    }
    adapter = GmailSnapshot([message])
    raw = adapter.fetch_new(None)[0]
    assert "Purchase" not in raw.body
    ingest(store, adapter)
    ticket = store.tickets()[0]
    assert "Test Sender" not in ticket.body
    assert ticket.user_identifier != "sender@example.com"
    message["payload"]["headers"][1]["value"] = "personal@example.com"
    assert GmailSnapshot([message]).fetch_new(None) == []


def test_hindi_need_is_not_a_promise():
    assert not PROMISE.search(ACKS["hi"])
    assert PROMISE.search("हम ज़रूर ठीक कर देंगे")
