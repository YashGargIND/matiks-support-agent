from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import UTC, datetime, timedelta
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from support.channels.base import ChannelAdapter
from support.config import read_config
from support.models import RawMessage


class EmailAdapter(ChannelAdapter):
    name = "email"

    def checkpoint_after_fetch(self, messages: list[RawMessage]) -> str | None:
        return getattr(self, "_next_cursor", None)

    def cursor(self, raw: RawMessage) -> str:
        return raw.channel_ref

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        oauth = bool(os.getenv("IMAP_REFRESH_TOKEN"))
        host = os.getenv("IMAP_HOST") or ("imap.gmail.com" if oauth else None)
        user, password = os.getenv("IMAP_USER"), os.getenv("IMAP_APP_PASSWORD")
        if not host or not user or (not oauth and not password):
            raise ValueError("IMAP read-only mailbox is not configured")
        if any(c in user for c in ("\r", "\n", "\x01")):
            raise ValueError("Invalid mailbox identifier")
        if oauth and host != "imap.gmail.com":
            raise ValueError("Google OAuth tokens may only be sent to imap.gmail.com")
        folder = os.getenv("IMAP_FOLDER", "INBOX")
        if any(c in folder for c in ("\r", "\n")):
            raise ValueError("Invalid IMAP folder")
        self._next_cursor = None
        with imaplib.IMAP4_SSL(host, int(os.getenv("IMAP_PORT", "993")), timeout=20) as client:
            client.debug = 0
            if oauth:
                from support.google_oauth import refresh_google_token

                token, scopes = refresh_google_token()
                if scopes and "https://mail.google.com/" not in scopes:
                    raise ValueError("The supplied token lacks Google's IMAP mail scope")
                initial = f"user={user}\x01auth=Bearer {token}\x01\x01".encode()
                first = True

                def authenticate(challenge):
                    nonlocal first
                    if not first or challenge:
                        return b""
                    first = False
                    return initial

                client.authenticate("XOAUTH2", authenticate)
            else:
                client.login(user, password)
            capability_status, capabilities = client.capability()
            if capability_status != "OK":
                raise ValueError("Cannot verify IMAP capabilities")
            current_capabilities = {
                c.decode() for group in capabilities if group for c in group.split()
            }
            quoted_folder = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
            status, _ = client.select(quoted_folder, readonly=True)
            if status != "OK":
                raise ValueError("Cannot examine configured IMAP folder")
            validity = client.response("UIDVALIDITY")[1][0].decode()
            last_uid = 0
            if since:
                previous_validity, previous_uid = since.split(":", 1)
                if previous_validity == validity:
                    last_uid = int(previous_uid)
            lookback = int(os.getenv("IMAP_LOOKBACK_DAYS", "7"))
            if not 1 <= lookback <= 90:
                raise ValueError("Initial IMAP lookback must be 1–90 days")
            query = f"UID {last_uid + 1}:* (OR (OR TO support@matiks.com TO support@matiks.in) (OR CC support@matiks.com CC support@matiks.in))"
            if not last_uid:
                query += " SINCE " + (datetime.now(UTC) - timedelta(days=lookback)).strftime(
                    "%d-%b-%Y"
                )
            status, data = client.uid("search", None, query)
            if status != "OK":
                raise ValueError("IMAP UID search failed")
            uids = sorted((u for u in data[0].split() if int(u) > last_uid), key=int)
            gmail_ids = "X-GM-EXT-1" in current_capabilities
            messages = []
            for uid in uids[: read_config()["limits"]["max_tickets_per_ingest"]]:
                # BODY.PEEK preserves unread flags even on unusual servers.
                status, parts = client.uid(
                    "fetch",
                    uid,
                    "("
                    + ("X-GM-MSGID " if gmail_ids else "")
                    + "BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.131072>)",
                )
                if status != "OK":
                    raise ValueError("IMAP fetch failed; checkpoint remains unchanged")
                chunks = [p[1] for p in parts if isinstance(p, tuple)]
                if len(chunks) != 2:
                    raise ValueError("Unexpected IMAP response; checkpoint remains unchanged")
                message = email.message_from_bytes(
                    chunks[0] + b"\r\n" + chunks[1], policy=policy.default
                )
                self._next_cursor = f"{validity}:{uid.decode()}"
                recipients = {
                    a.lower()
                    for _, a in getaddresses(
                        [str(message.get("To", "")), str(message.get("Cc", ""))]
                    )
                }
                if not recipients.intersection({"support@matiks.com", "support@matiks.in"}):
                    continue
                try:
                    created = parsedate_to_datetime(message["Date"])
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                except (TypeError, ValueError):
                    raise ValueError("Email lacks a usable date; review the export") from None
                body_parts = [
                    p.get_content()
                    for p in message.walk()
                    if p.get_content_type() == "text/plain" and not p.get_filename()
                ]
                sender = message["From"]
                names = (
                    [a.display_name for a in sender.addresses if a.display_name]
                    if hasattr(sender, "addresses")
                    else []
                )
                identifier = (
                    sender.addresses[0].addr_spec
                    if hasattr(sender, "addresses") and sender.addresses
                    else ""
                )
                gmail_id = (
                    re.search(
                        rb"X-GM-MSGID\s+(\d+)",
                        b" ".join(p[0] for p in parts if isinstance(p, tuple)),
                    )
                    if gmail_ids
                    else None
                )
                channel_ref = (
                    "gmail:" + format(int(gmail_id.group(1)), "x")
                    if gmail_id
                    else f"{validity}:{uid.decode()}"
                )
                messages.append(
                    RawMessage(
                        channel=self.name,
                        channel_ref=channel_ref,
                        created_at=created.astimezone(UTC).isoformat(),
                        subject=str(message["Subject"] or ""),
                        body="\n".join(body_parts)[:100000],
                        user_identifier=identifier,
                        known_names=names,
                    )
                )
            return messages
