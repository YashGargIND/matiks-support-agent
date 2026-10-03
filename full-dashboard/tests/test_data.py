from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bson import ObjectId

from support.branches import delivery_stats
from support.contracts import DeliverySamples
from support.data import MongoProvider, MongoReader
from support.models import Cohort
from support.pipeline import process
from tests.test_specialists import EvidenceProvider, merch_provider


class Cursor:
    def __init__(self, rows):
        self.rows, self.limit_value, self.timeout = rows, None, None

    def max_time_ms(self, value):
        self.timeout = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def __iter__(self):
        return iter(self.rows[: self.limit_value])


class Collection:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def find(self, query, projection):
        self.queries.append((query, projection))
        self.cursor = Cursor(self.rows)
        return self.cursor


def test_readonly_role_failure_closes_connection(monkeypatch):
    class Client:
        closed = False
        admin = None

        def __init__(self, *args, **kwargs):
            self.admin = self

        def __getitem__(self, name):
            return self

        def command(self, *args, **kwargs):
            return {
                "authInfo": {
                    "authenticatedUsers": [{"user": "test"}],
                    "authenticatedUserRoles": [{"role": "readWrite", "db": "test"}],
                }
            }

        def close(self):
            Client.closed = True

    monkeypatch.setenv("MONGO_URI_READONLY", "mongodb://unused")
    monkeypatch.setenv("MONGO_DATABASE", "test")
    monkeypatch.setattr("pymongo.MongoClient", Client)
    with pytest.raises(ValueError, match="read role"):
        MongoReader()
    assert Client.closed


def test_user_query_uses_minimal_projection_and_bounded_cursor():
    reader = object.__new__(MongoReader)
    reader.mapping = {"auth": {"user_field": "_id", "projection": ["_id", "status"]}}
    collection = Collection([{"_id": "a"}] * 4)
    reader.collection = lambda alias: collection
    identifier = str(ObjectId())
    rows, complete = reader.find_user("auth", identifier, 3)
    assert len(rows) == 3 and complete is False
    assert collection.cursor.limit_value == 4 and collection.cursor.timeout == 3000
    assert collection.queries == [({"_id": ObjectId(identifier)}, {"_id": 1, "status": 1})]


def test_payment_database_is_explicit(monkeypatch):
    reader = object.__new__(MongoReader)
    reader.mapping = {"payments": {"name": "payments"}}
    monkeypatch.delenv("PAYMENTS_MONGO_DATABASE", raising=False)
    with pytest.raises(LookupError):
        reader.collection("payments")


def test_empty_payment_query_does_not_assert_nonpaying(monkeypatch, store, ticket):
    class Reader:
        def find_user(self, alias, user_id, limit=50):
            return [], True

    monkeypatch.setenv("MONGO_SCHEMA_VERIFIED", "true")
    provider = MongoProvider(store, ticket.id, Reader())
    cohort, _ = provider.fetch("get_user_cohort", "user1")
    assert cohort["is_paying"] is None


def test_unconfirmed_cake_and_completed_status_are_not_delivery_proof(monkeypatch, store, ticket):
    class Reader:
        def find_user(self, alias, user_id, limit=50):
            return [
                {"_id": "cake", "rewardType": "CAKE", "createdAt": datetime.now(UTC)},
                {
                    "_id": "shirt",
                    "rewardType": "TSHIRT",
                    "claimedAt": datetime.now(UTC),
                    "reworksOrderId": "1",
                    "reworksOrderStatus": "completed",
                    "completedAt": datetime.now(UTC),
                },
            ], True

    monkeypatch.setenv("MONGO_SCHEMA_VERIFIED", "true")
    provider = MongoProvider(store, ticket.id, Reader())
    orders, complete = provider._orders("user1")
    assert not complete and len(orders) == 1
    assert not orders[0]["delivery_confirmed"] and orders[0]["delivered_at"] is None
    with pytest.raises(LookupError):
        provider.fetch("get_merch_delivery_stats", "user1")


def test_delivery_stats_deduplicate_and_ignore_future_samples():
    data = merch_provider().facts["get_merch_delivery_stats"]
    data["orders"].append(data["orders"][0])
    samples = DeliverySamples.model_validate(data)
    assert delivery_stats(samples, datetime.now(UTC))["samples"] == 5
    samples.orders[1].delivered_at = datetime.now(UTC).replace(year=2030)
    assert delivery_stats(samples, datetime.now(UTC)) is None


async def test_reinvestigation_cannot_reuse_old_identity_or_cohort(store, ticket):
    ticket.matiks_user_id = "stale"
    ticket.cohort = Cohort(is_paying=True, streak_days=999)
    store.save(ticket)

    class Missing(EvidenceProvider):
        def fetch(self, topic, user_id):
            raise LookupError

    outcome = await process(store, ticket.id, Missing({}))
    assert outcome.matiks_user_id is None
    assert outcome.cohort.is_paying is None and outcome.cohort.streak_days is None


async def test_owned_provider_always_closes(monkeypatch, store, ticket):
    class Provider(EvidenceProvider):
        closed = False

        def close(self):
            self.closed = True

    provider = Provider({})
    monkeypatch.setattr("support.data.configured_provider", lambda *_: provider)
    await process(store, ticket.id)
    assert provider.closed
