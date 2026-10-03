from __future__ import annotations

import hashlib
import re

from support.models import RawMessage, Ticket

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")),
    ("SECRET", re.compile(r"\b(?:sk-|ghp_|xox[baprs]-)[A-Za-z0-9_-]{10,}")),
    ("PAYMENT", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    (
        "PHONE",
        re.compile(r"(?<!\w)(?:\+\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}(?!\w)"),
    ),
    ("PHONE", re.compile(r"(?<!\w)(?:\+91[\s-]?)?[6-9]\d{9}(?!\w)")),
    (
        "ADDRESS",
        re.compile(
            r"\b\d{1,5}\s+[\w .-]{2,60}\s(?:Street|Road|Avenue|Lane|Drive|St\b|Rd\b|Marg)\b[^\n]*",
            re.I,
        ),
    ),
    ("NAME", re.compile(r"(?<=my name is )[A-Za-z]+(?: [A-Za-z]+){0,2}", re.I)),
]


class Redactor:
    """Deterministic local redaction; human review gates all real-data LLM calls.

    Regex alone cannot reliably find arbitrary names/addresses in every language.
    Never treat this output as proof that all PII has been removed.
    """

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = mapping or {}

    def _token(self, value: str, kind: str) -> str:
        for token, original in self.mapping.items():
            if original == value:
                return token
        token = f"[{kind}_{len(self.mapping) + 1}]"
        self.mapping[token] = value
        return token

    def text(self, value: str, known_names: list[str] | None = None) -> str:
        for name in sorted(known_names or [], key=len, reverse=True):
            if len(name.strip()) > 1:
                value = re.sub(
                    r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)",
                    lambda m: self._token(m.group(), "NAME"),
                    value,
                    flags=re.I,
                )
        for kind, pattern in PATTERNS:
            value = pattern.sub(lambda m: self._token(m.group(), kind), value)
        return value

    def data(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.data(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.data(v) for v in value]
        return value


def normalize(raw: RawMessage) -> tuple[Ticket, dict]:
    digest = hashlib.sha256(f"{raw.channel}:{raw.channel_ref}".encode()).hexdigest()[:24]
    redactor = Redactor()
    ticket = Ticket(
        id=digest,
        channel=raw.channel,
        channel_ref=raw.channel_ref,
        created_at=raw.created_at,
        subject=redactor.text(raw.subject, raw.known_names),
        body=redactor.text(raw.body, raw.known_names),
        user_identifier=redactor.text(raw.user_identifier, raw.known_names),
        provenance=raw.provenance,
    )
    # Raw channel references may be sensitive; they stay local and are never sent to a model.
    return ticket, redactor.mapping
