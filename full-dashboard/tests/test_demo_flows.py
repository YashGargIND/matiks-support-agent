from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from support.api import app
from support.demo import demo_context
from support.facts import ticket_facts


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB", str(store.path))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "scenario,verdict,action",
    [
        ("dm-safety", "safety_ban_review", "temp_ban_messaging"),
        ("merch-reply", "merch_within_window", None),
        ("streak-restore", "bug_confirmed", "restore_streak"),
        ("feature-request", "suggestion_recorded", None),
    ],
)
def test_first_four_demo_paths_use_normal_pipeline_and_never_dispatch(
    client, store, scenario, verdict, action
):
    created = client.post(f"/ui/demo/{scenario}", json={"reviewer": "Demo tester"})
    assert created.status_code == 200
    ticket = created.json()
    assert ticket["provenance"] == "synthetic"
    response = client.post(
        f"/ui/tickets/{ticket['id']}/process",
        json={"reviewer": "Demo tester", "revision": ticket["revision"]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["verdict"] == verdict
    assert result["reply_draft"]
    detail = client.get(f"/ui/tickets/{ticket['id']}").json()
    assert detail["fact_checks"][-1]["passed"] is True
    assert all(
        e["source"].startswith("synthetic-demo:") for e in detail["evidence"] if e["available"]
    )
    if action:
        proposal = next(a for a in detail["actions"] if a["type"] == action)
        assert proposal["status"] == "pending"
        assert store.rows("outbox") == []
        approved = client.post(
            f"/ui/actions/{proposal['id']}/approve",
            json={"reviewer": "Human", "revision": result["revision"]},
        )
        assert approved.status_code == 200
        assert store.rows("outbox")[0]["mode"] == "dry_run"
        assert json.loads(store.rows("outbox")[0]["payload"])
        assert store.get(ticket["id"]).status == result["status"]
        assert (
            next(a for a in store.rows("proposed_actions") if a["type"] == "send_reply")["status"]
            == "pending"
        )
    else:
        assert store.rows("outbox") == []
    assert client.get("/ui/overview").json()["tickets"] == []
    assert len(client.get("/ui/overview?provenance=synthetic").json()["tickets"]) == 1
    assert store.rows("llm_calls") == []


@pytest.mark.parametrize(
    "scenario,verdict",
    [
        ("dm-critical", "needs_human_review"),
        ("merch-delayed", "merch_delayed"),
        ("streak-unclear", "data_unclear"),
        ("streak-paid", "not_a_bug"),
    ],
)
def test_demo_edge_paths(client, store, scenario, verdict):
    ticket = client.post(f"/ui/demo/{scenario}", json={"reviewer": "Demo tester"}).json()
    result = client.post(
        f"/ui/tickets/{ticket['id']}/process",
        json={"reviewer": "Demo tester", "revision": ticket["revision"]},
    ).json()
    assert result["verdict"] == verdict
    if scenario == "dm-critical":
        assert store.rows("tool_calls") == []
        assert store.rows("llm_calls") == []
        assert {a["type"] for a in store.rows("proposed_actions")} == {"send_reply"}
    assert store.rows("outbox") == []


def test_demo_policy_cannot_leak_to_real_or_agent_authored_reports(client, store):
    demo = client.post("/ui/demo/dm-safety", json={"reviewer": "Demo tester"}).json()
    real = client.post("/ui/reports", json={"body": "DM harassment", "reviewer": "Human"}).json()
    assert real["provenance"] == "real"
    assert demo_context(store, real["id"]) is None
    assert "fact:demo-severity2" not in ticket_facts(store, real["id"]).refs()
    modified = store.get(demo["id"])
    modified.body += "Changed inbound text"
    store.save(modified)
    assert demo_context(store, modified.id) is None


def test_report_redaction_safety_override_stale_review_and_bad_promises(client, store):
    result = client.post(
        "/ui/reports",
        json={
            "body": "DM harassment. Contact me at demo@example.com",
            "category": "feature",
            "reviewer": "Tester",
            "provenance": "synthetic",
            "user_identifier": "demo@example.com",
        },
    ).json()
    assert result["category"] == "dm_safety"
    assert "demo@example.com" not in result["body"]
    assert store.local_identity(result["id"]) == "demo@example.com"
    edited = client.patch(
        f"/ui/tickets/{result['id']}",
        json={
            "reviewer": "Human",
            "revision": result["revision"],
            "reply_draft": "We will fix it tomorrow",
        },
    ).json()
    assert (
        client.post(
            f"/ui/tickets/{result['id']}/approve",
            json={
                "reviewer": "Human",
                "revision": result["revision"],
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/ui/tickets/{result['id']}/approve",
            json={
                "reviewer": "Human",
                "revision": edited["revision"],
            },
        ).status_code
        == 422
    )
    assert store.rows("outbox") == []


def test_human_category_and_reply_language_survive_investigation(client, monkeypatch):
    monkeypatch.setattr("support.data.configured_provider", lambda *args: None)
    ticket = client.post(
        "/ui/reports",
        json={
            "body": "Please add a merch order tracker",
            "category": "feature",
            "language": "hinglish",
            "reviewer": "Human",
            "provenance": "synthetic",
        },
    ).json()
    result = client.post(
        f"/ui/tickets/{ticket['id']}/process",
        json={"reviewer": "Human", "revision": ticket["revision"]},
    ).json()
    assert result["category"] == "feature"
    assert result["language"] == "hinglish"
    assert result["verdict"] == "suggestion_recorded"
    assert "Suggestion share" in result["reply_draft"]


def test_stale_investigation_cannot_start_a_new_run(client, store):
    ticket = client.post("/ui/demo/streak-restore", json={"reviewer": "Tester"}).json()
    edited = client.patch(
        f"/ui/tickets/{ticket['id']}",
        json={"reviewer": "Human", "revision": ticket["revision"], "reply_draft": "Review needed"},
    )
    assert edited.status_code == 200
    response = client.post(
        f"/ui/tickets/{ticket['id']}/process",
        json={"reviewer": "Tester", "revision": ticket["revision"]},
    )
    assert response.status_code == 409
    assert store.get(ticket["id"]).active_run is None
