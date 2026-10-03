from __future__ import annotations

import json
import subprocess

import pytest

from support.actions import approve_action
from support.data import configured_provider
from support.models import RawMessage
from support.pipeline import process
from support.privacy import normalize
from support.repository import CompositeProvider, RepositoryProvider


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Synthetic Author")
    git("config", "user.email", "author@example.test")
    (root / "game").mkdir()
    (root / "game/score.py").write_text("def reset_score(score):\n    return score - 1\n")
    (root / "game/credentials.py").write_text("score = 'private-credential'\n")
    (root / ".env").write_text("PRIVATE_KEY=never-read-this\n")
    (root / "CODEOWNERS").write_text("* @example/reviewers\n/game/ @example/game-reviewers\n")
    git("add", ".")
    git("commit", "-m", "Synthetic score implementation")
    return root


@pytest.fixture
def mapping():
    return {
        "modules": {
            "gameplay": {"terms": ["score", "game"], "paths": ["game"]},
            "app": {"terms": [], "paths": ["game"]},
        }
    }


def score_ticket(store):
    ticket, vault = normalize(
        RawMessage(
            channel="test",
            channel_ref="score",
            created_at="2026-10-03T04:00:00+00:00",
            subject="Game score reset",
            body="The game score resets after a duel",
            provenance="synthetic",
        )
    )
    store.ingest(ticket, vault)
    return ticket


def test_bounded_source_provenance_and_review_ownership(repository, mapping, store):
    provider = RepositoryProvider(repository, score_ticket(store), mapping)
    code, source = provider.fetch("code_search", None)
    assert code["files"] == ["game/score.py"]
    assert code["snippets"][0]["start_line"] == 1
    assert len(code["snippets"][0]["sha256"]) == 64
    assert code["repo_head"] in source
    assert code["commits"][0]["causation_verified"] is False
    assert code["hypothesis"] is None and code["confidence"] == 0
    owners, _ = provider.fetch("get_module_owner", None)
    assert owners["owners"] == ["@example/game-reviewers"]
    assert owners["role"] == "path_code_reviewer"
    assert owners["sources"][0]["line"] == 2
    assert owners["contributors"][0]["ownership_verified"] is False
    assert "author@example.test" not in json.dumps(owners)
    assert "Synthetic Author" not in json.dumps(owners)


def test_source_reader_rejects_secret_untracked_traversal_and_symlink(repository, mapping, store):
    (repository / "game/untracked.py").write_text("score = 1")
    (repository / "game/score.py").unlink()
    (repository / "game/score.py").symlink_to(repository / ".env")
    provider = RepositoryProvider(repository, score_ticket(store), mapping)
    for path in (
        ".env",
        "game/credentials.py",
        "game/untracked.py",
        "../outside.py",
        "game/score.py",
    ):
        with pytest.raises(ValueError):
            provider.read(path)
    assert provider.code()["files"] == []


def test_unsupported_codeowners_never_guesses_owner(repository, mapping, store):
    (repository / "CODEOWNERS").write_text("* @example/reviewers\n/game/*.py @example/special\n")
    owners = RepositoryProvider(repository, score_ticket(store), mapping).owners()
    assert owners["owners"] == [] and owners["confidence"] == 0
    assert owners["sources"][0]["ownership_unavailable"] is True


def test_source_hash_captures_dirty_working_tree(repository, mapping, store):
    ticket = score_ticket(store)
    old = RepositoryProvider(repository, ticket, mapping).code()
    (repository / "game/score.py").write_text("def reset_score(score):\n    return score + 1\n")
    new = RepositoryProvider(repository, ticket, mapping).code()
    assert old["repo_head"] == new["repo_head"]
    assert new["working_tree_dirty"] is True
    assert old["snippets"][0]["sha256"] != new["snippets"][0]["sha256"]


async def test_bug_context_proposal_is_guarded_local_and_never_a_confirmed_cause(
    repository, mapping, store
):
    ticket = score_ticket(store)
    repo = RepositoryProvider(repository, ticket, mapping)
    result = await process(store, ticket.id, CompositeProvider(repository=repo))
    assert result.verdict == "bug_context_collected"
    assert result.status == "escalated" and result.root_cause_hypothesis is None
    assert len(store.rows("llm_calls")) == 0
    proposals = [
        p for p in store.rows("proposed_actions", ticket.id) if p["type"] == "slack_message"
    ]
    assert len(proposals) == 1
    proposal = proposals[0]
    payload = json.loads(proposal["payload"])
    assert payload["report"]["runtime_cause_confirmed"] is False
    assert payload["report"]["product_owner_verified"] is False
    assert payload["slack_user_ids"] == [] and payload["dispatch_allowed"] is False
    assert store.rows("outbox") == []
    # A modified action cannot pass approval against independently recomputed evidence.
    changed = dict(payload, dispatch_allowed=True)
    with store.connection() as db:
        db.execute(
            "UPDATE proposed_actions SET payload=? WHERE id=?",
            (json.dumps(changed), proposal["id"]),
        )
    with pytest.raises(ValueError, match="differs"):
        approve_action(store, proposal["id"], "reviewer", result.revision)
    with store.connection() as db:
        db.execute(
            "UPDATE proposed_actions SET payload=? WHERE id=?",
            (proposal["payload"], proposal["id"]),
        )
    approve_action(store, proposal["id"], "reviewer", result.revision)
    assert len(store.rows("outbox")) == 1
    assert store.rows("outbox")[0]["mode"] == "dry_run"


def test_repository_setup_survives_unavailable_mongo(repository, mapping, store, monkeypatch):
    import support.repository as repo_module
    from support import data

    ticket = score_ticket(store)
    monkeypatch.setenv("MONGO_SCHEMA_VERIFIED", "true")
    monkeypatch.setenv("REPO_PATH", str(repository))

    def unavailable(*args):
        raise LookupError("No database configured")

    monkeypatch.setattr(data, "MongoProvider", unavailable)
    original = repo_module.RepositoryProvider
    monkeypatch.setattr(
        repo_module, "RepositoryProvider", lambda root, ticket: original(root, ticket, mapping)
    )
    provider = configured_provider(store, ticket.id)
    try:
        assert provider.fetch("code_search", None)[0]["files"] == ["game/score.py"]
        with pytest.raises(LookupError):
            provider.fetch("resolve_user", None)
    finally:
        provider.close()


def test_unsafe_mapping_cannot_expand_repository_scope(repository, mapping, store):
    mapping["modules"]["gameplay"]["paths"] = ["../outside"]
    with pytest.raises(ValueError, match="Unsafe"):
        RepositoryProvider(repository, score_ticket(store), mapping)
