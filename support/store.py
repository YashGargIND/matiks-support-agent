from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from support.config import db_path, require_dry_run
from support.models import Evidence, Ticket, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
 id TEXT PRIMARY KEY, channel TEXT NOT NULL, channel_ref TEXT NOT NULL,
 data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(channel, channel_ref)
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, run_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposed_actions (
 id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, run_id TEXT NOT NULL,
 type TEXT NOT NULL, payload TEXT NOT NULL, evidence_refs TEXT NOT NULL,
 reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
 approved_at TEXT, reviewer TEXT, mode TEXT NOT NULL CHECK(mode = 'dry_run')
);
CREATE TABLE IF NOT EXISTS outbox (
 id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE,
 payload TEXT NOT NULL, created_at TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode = 'dry_run')
);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, ticket_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
 id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, ticket_id TEXT NOT NULL,
 agent TEXT NOT NULL, step TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
 cost_source TEXT NOT NULL, latency_ms REAL NOT NULL, cache_hit INTEGER,
 status TEXT NOT NULL, generation_id TEXT
);
CREATE TABLE IF NOT EXISTS tool_calls (
 id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, ticket_id TEXT NOT NULL,
 run_id TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL,
 latency_ms REAL NOT NULL, result_size INTEGER NOT NULL, available INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (channel TEXT PRIMARY KEY, cursor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pii_vault (ticket_id TEXT PRIMARY KEY, mapping TEXT NOT NULL);
"""


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path: Path | None = None):
        require_dry_run()
        self.path = path or db_path()
        new_directory = not self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Protect WAL/SHM files as well as the main database.
        if new_directory:
            os.chmod(self.path.parent, 0o700)
        with self.connection() as db:
            db.executescript(SCHEMA)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, ticket: Ticket, mapping: dict) -> bool:
        with self.connection() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO tickets (id,channel,channel_ref,data) VALUES (?,?,?,?)",
                (ticket.id, ticket.channel, ticket.channel_ref, ticket.model_dump_json()),
            )
            if cur.rowcount:
                db.execute("INSERT INTO pii_vault VALUES (?,?)", (ticket.id, json.dumps(mapping)))
            return cur.rowcount == 1

    def get(self, ticket_id: str) -> Ticket:
        with self.connection() as db:
            row = db.execute("SELECT data FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if row is None:
            raise KeyError(ticket_id)
        return Ticket.model_validate_json(row["data"])

    def tickets(self) -> list[Ticket]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM tickets").fetchall()
        return sorted(
            (Ticket.model_validate_json(r["data"]) for r in rows), key=lambda t: -t.priority_score
        )

    def save(self, ticket: Ticket):
        revision = ticket.revision
        ticket.revision += 1
        with self.connection() as db:
            cur = db.execute(
                "UPDATE tickets SET data=?, revision=? WHERE id=? AND revision=?",
                (ticket.model_dump_json(), ticket.revision, ticket.id, revision),
            )
            if cur.rowcount != 1:
                ticket.revision = revision
                raise ConflictError("Ticket changed in another session. Refresh before continuing.")

    def event(self, ticket_id: str | None, kind: str, data: dict):
        with self.connection() as db:
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (uuid4().hex, ticket_id, kind, json.dumps(data), now()),
            )

    def evidence(self, record: Evidence):
        with self.connection() as db:
            db.execute(
                "INSERT INTO evidence VALUES (?,?,?,?)",
                (record.id, record.ticket_id, record.run_id, record.model_dump_json()),
            )

    def evidence_for(self, ticket_id: str, run_id: str | None = None) -> list[Evidence]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT data FROM evidence WHERE ticket_id=? AND (? IS NULL OR run_id=?)",
                (ticket_id, run_id, run_id),
            ).fetchall()
        return [Evidence.model_validate_json(r["data"]) for r in rows]

    def rows(self, table: str, ticket_id: str | None = None) -> list[dict]:
        allowed = {"llm_calls", "tool_calls", "events", "proposed_actions", "outbox"}
        if table not in allowed:
            raise ValueError("Table is not public")
        with self.connection() as db:
            query = f"SELECT * FROM {table}"
            rows = (
                db.execute(query + " WHERE ticket_id=?", (ticket_id,)).fetchall()
                if ticket_id
                else db.execute(query).fetchall()
            )
        return [dict(r) for r in rows]

    def checkpoint(self, channel: str) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT cursor FROM checkpoints WHERE channel=?", (channel,)
            ).fetchone()
        return row[0] if row else None

    def set_checkpoint(self, channel: str, cursor: str):
        with self.connection() as db:
            db.execute(
                "INSERT INTO checkpoints VALUES (?,?) ON CONFLICT(channel) DO UPDATE SET cursor=excluded.cursor",
                (channel, cursor),
            )

    def local_identity(self, ticket_id: str) -> str:
        """Local-only lookup for read-only account resolution; never expose via API."""
        ticket = self.get(ticket_id)
        with self.connection() as db:
            row = db.execute(
                "SELECT mapping FROM pii_vault WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        mapping = json.loads(row[0]) if row else {}
        return mapping.get(ticket.user_identifier, ticket.user_identifier)

    def redact_evidence(self, ticket_id: str, data):
        """Keep tool-output redaction reversible in the same private local vault."""
        from support.privacy import Redactor

        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT mapping FROM pii_vault WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            redactor = Redactor(json.loads(row[0]) if row else {})
            cleaned = redactor.data(data)
            db.execute(
                "INSERT INTO pii_vault VALUES (?,?) ON CONFLICT(ticket_id) DO UPDATE SET mapping=excluded.mapping",
                (ticket_id, json.dumps(redactor.mapping)),
            )
        return cleaned
