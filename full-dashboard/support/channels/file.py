from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from support.channels.base import ChannelAdapter
from support.config import read_config
from support.models import RawMessage


class FileAdapter(ChannelAdapter):
    name = "file"

    def __init__(self, path: Path | None = None):
        configured = os.getenv("SUPPORT_IMPORT_PATH")
        if path is None and not configured:
            raise ValueError("Set SUPPORT_IMPORT_PATH to a JSON or CSV ticket export")
        self.path = path or Path(configured)

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        if self.path.stat().st_size > 5_000_000:
            raise ValueError("Export exceeds 5 MB; split into smaller files")
        with self.path.open() as stream:
            rows = list(csv.DictReader(stream)) if self.path.suffix == ".csv" else json.load(stream)
        if not isinstance(rows, list):
            raise ValueError("JSON export must be a list of normalized RawMessage objects")
        messages = [RawMessage.model_validate(row) for row in rows]
        messages.sort(key=lambda m: (m.created_at, m.channel, m.channel_ref))
        boundary = tuple(json.loads(since)) if since else None
        return [
            m
            for m in messages
            if boundary is None or (m.created_at, m.channel, m.channel_ref) > boundary
        ][: read_config()["limits"]["max_tickets_per_ingest"]]

    def cursor(self, raw: RawMessage) -> str:
        return json.dumps([raw.created_at, raw.channel, raw.channel_ref])
