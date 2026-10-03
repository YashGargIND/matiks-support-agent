from __future__ import annotations

import importlib
from abc import ABC, abstractmethod

from support.config import read_config, require_dry_run
from support.models import RawMessage, Ticket
from support.privacy import normalize


class ChannelAdapter(ABC):
    name: str

    @abstractmethod
    def fetch_new(self, since: str | None) -> list[RawMessage]:
        """Bounded read only fetch; since is an opaque adapter checkpoint."""

    def normalize(self, raw: RawMessage) -> tuple[Ticket, dict]:
        return normalize(raw)

    def cursor(self, raw: RawMessage) -> str:
        return raw.created_at

    def checkpoint_after_fetch(self, messages: list[RawMessage]) -> str | None:
        return self.cursor(messages[-1]) if messages else None

    def write_back(self, ticket: Ticket, action: dict) -> None:
        require_dry_run()
        raise RuntimeError("External write-back is permanently disabled. Use the local outbox.")


def load_adapters() -> list[ChannelAdapter]:
    adapters = []
    for spec in read_config()["channels"]:
        module, name = spec.split(":", 1)
        cls = getattr(importlib.import_module(module), name)
        if not issubclass(cls, ChannelAdapter):
            raise ValueError("Configured plugin must implement ChannelAdapter")
        adapter = cls()
        if adapter.name in {a.name for a in adapters}:
            raise ValueError("Channel names must be unique")
        adapters.append(adapter)
    return adapters
