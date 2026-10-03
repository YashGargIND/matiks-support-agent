from __future__ import annotations

import pytest

from support.channels.email import EmailAdapter
from support.pipeline import ingest


class Mailbox:
    capabilities = (b"IMAP4rev1", b"X-GM-EXT-1")

    def __init__(self, *args, **kwargs):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def authenticate(self, mechanism, callback):
        assert mechanism == "XOAUTH2"
        assert callback(b"") == b"user=mailbox@example.test\x01auth=Bearer local-test-token\x01\x01"
        assert callback(b'{"status":"401"}') == b""
        self.calls.append(("authenticate", mechanism))

    def select(self, folder, readonly=False):
        assert readonly is True
        self.calls.append(("select", folder, readonly))
        return "OK", []

    def capability(self):
        return "OK", [b"IMAP4rev1 X-GM-EXT-1"]

    def response(self, name):
        assert name == "UIDVALIDITY"
        return "UIDVALIDITY", [b"42"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "search":
            assert "TO support@matiks.com" in args[-1]
            assert "CC support@matiks.in" in args[-1]
            return "OK", [b"10"]
        assert command == "fetch" and "BODY.PEEK" in args[-1] and "X-GM-MSGID" in args[-1]
        header = b"From: Reporter <sender@example.test>\r\nTo: support@matiks.com\r\nDate: Sat, 03 Oct 2026 10:00:00 +0000\r\nSubject: Game issue\r\nContent-Type: text/plain; charset=UTF-8\r\n"
        return "OK", [
            (b"1 (UID 10 X-GM-MSGID 255 BODY[HEADER] {200}", header),
            (b"BODY[TEXT]<0> {12}", b"Game failed"),
        ]


@pytest.fixture
def mailbox(monkeypatch):
    from support import google_oauth
    from support.channels import email

    instance = Mailbox()
    monkeypatch.setenv("IMAP_REFRESH_TOKEN", "never-transmitted-test-refresh")
    monkeypatch.setenv("IMAP_USER", "mailbox@example.test")
    monkeypatch.setenv("IMAP_FOLDER", "INBOX")
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.setattr(
        email.imaplib,
        "IMAP4_SSL",
        lambda host, *args, **kwargs: (
            instance if host == "imap.gmail.com" else pytest.fail("Unexpected token destination")
        ),
    )
    monkeypatch.setattr(
        google_oauth,
        "refresh_google_token",
        lambda: ("local-test-token", {"https://mail.google.com/"}),
    )
    return instance


def test_oauth_imap_is_readonly_and_deduplicates_gmail_snapshot_ids(store, mailbox):
    adapter = EmailAdapter()
    first = ingest(store, adapter)
    assert first["inserted"] == 1
    ticket = store.tickets()[0]
    assert ticket.channel_ref == "gmail:ff"
    assert store.checkpoint("email") == "42:10"
    assert "sender@example.test" not in ticket.body + ticket.user_identifier
    # The same Gmail message across the connector snapshot and IMAP has one canonical ID.
    second = ingest(store, EmailAdapter())
    assert second["inserted"] == 0
    assert len(store.tickets()) == 1
    assert not {c[0] for c in mailbox.calls}.intersection({"store", "append", "expunge", "delete"})


def test_oauth_token_cannot_be_sent_to_other_imap_host(store, mailbox, monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "other.example.test")
    with pytest.raises(ValueError, match="only be sent"):
        ingest(store, EmailAdapter())
    assert store.tickets() == []


def test_unrelated_mail_is_excluded_but_uid_checkpoint_advances(store, mailbox, monkeypatch):
    original = mailbox.uid

    def unrelated(command, *args):
        result = original(command, *args)
        if command == "fetch":
            status, parts = result
            parts[0] = (
                parts[0][0],
                parts[0][1].replace(b"support@matiks.com", b"private@example.test"),
            )
            return status, parts
        return result

    monkeypatch.setattr(mailbox, "uid", unrelated)
    result = ingest(store, EmailAdapter())
    assert result == {"inserted": 0, "fetched": 0, "channel": "email"}
    assert store.checkpoint("email") == "42:10"


def test_refresh_failures_never_echo_credentials(monkeypatch):
    from support import google_oauth

    for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "IMAP_REFRESH_TOKEN"):
        monkeypatch.setenv(key, "private-test-credential")

    class Response:
        status_code = 400

        def json(self):
            pytest.fail("Do not inspect/log the failed response body")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, data):
            assert url == "https://oauth2.googleapis.com/token"
            return Response()

    monkeypatch.setattr(google_oauth.httpx, "Client", Client)
    with pytest.raises(ValueError, match="HTTP 400") as error:
        google_oauth.refresh_google_token()
    assert "private-test-credential" not in str(error.value)


@pytest.mark.parametrize(
    "roles,allowed",
    [
        (["readAnyDatabase", "clusterMonitor"], True),
        (["read", "clusterMonitor"], True),
        (["clusterMonitor"], False),
        (["readWrite", "clusterMonitor"], False),
        (["readAnyDatabase", "customRole"], False),
    ],
)
def test_mongo_read_role_with_monitor_is_allowed_but_writes_are_rejected(
    monkeypatch, roles, allowed
):
    import pymongo

    from support.data import MongoReader

    monkeypatch.setenv("MONGO_URI_READONLY", "mongodb://fixture")
    monkeypatch.setenv("MONGO_DATABASE", "fixture")
    clients = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.admin = self
            self.closed = False
            clients.append(self)

        def __getitem__(self, key):
            return self

        def command(self, name, **kwargs):
            return {
                "authInfo": {
                    "authenticatedUsers": [{"user": "fixture"}],
                    "authenticatedUserRoles": [{"role": role, "db": "admin"} for role in roles],
                }
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(pymongo, "MongoClient", Client)
    if allowed:
        reader = MongoReader()
        reader.close()
    else:
        with pytest.raises(ValueError, match="built-in Mongo read role"):
            MongoReader()
    assert clients[0].closed is True
