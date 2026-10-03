from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from support.config import ROOT
from support.facts import Facts
from support.store import Store


def source_map() -> dict:
    return yaml.safe_load((ROOT / "source_map.yaml").read_text())


class MongoReader:
    """Only named, bounded query templates; no write/index/migration operations."""

    def __init__(self):
        from pymongo import MongoClient

        uri, database = os.getenv("MONGO_URI_READONLY"), os.getenv("MONGO_DATABASE")
        if not uri or not database:
            raise LookupError("Read-only Mongo source is not configured")
        self.client = MongoClient(
            uri,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            socketTimeoutMS=5000,
            tz_aware=True,
        )
        self.database = self.client[database]
        try:
            status = self.client.admin.command("connectionStatus", showPrivileges=True)
            auth = status.get("authInfo", {})
            roles = auth.get("authenticatedUserRoles", [])
            if not auth.get("authenticatedUsers") or not roles:
                raise ValueError("Authenticated read-only credentials are required")
            # MongoDB documents clusterMonitor as read-only monitoring access.
            # It may accompany a data-read role, but cannot substitute for one.
            if any(
                r["role"] not in {"read", "readAnyDatabase", "clusterMonitor"} for r in roles
            ) or not any(r["role"] in {"read", "readAnyDatabase"} for r in roles):
                raise ValueError("Use a built-in Mongo read role for this demo")
        except Exception:
            self.client.close()
            raise
        self.roles = [{"role": r["role"], "db": r["db"]} for r in roles]
        self.mapping = source_map()["collections"]

    def close(self):
        self.client.close()

    def collection(self, alias: str):
        definition = self.mapping[alias]
        if alias == "payments":
            database = os.getenv("PAYMENTS_MONGO_DATABASE")
            if not database:
                raise LookupError("Payment database must be explicitly configured")
            return self.client[database][definition["name"]]
        return self.database[definition["name"]]

    def find_user(self, alias: str, user_id: str, limit: int = 50) -> tuple[list[dict], bool]:
        from bson import ObjectId

        definition = self.mapping[alias]
        projection = {field: 1 for field in definition["projection"]}
        cursor = (
            self.collection(alias)
            .find({definition["user_field"]: ObjectId(user_id)}, projection)
            .max_time_ms(3000)
            .limit(min(limit, 100) + 1)
        )
        rows = list(cursor)
        return rows[:limit], len(rows) <= limit

    def resolve(self, identifier: str) -> dict:
        from bson import ObjectId

        auth_definition = self.mapping["auth"]
        projection = {field: 1 for field in auth_definition["projection"]}
        email = "@" in identifier and not identifier.startswith("@")
        if email:
            query = {"email": {"$regex": "^" + re.escape(identifier) + "$", "$options": "i"}}
            rows = list(self.collection("auth").find(query, projection).max_time_ms(3000).limit(2))
        elif re.fullmatch(r"[a-fA-F0-9]{24}", identifier):
            rows = list(
                self.collection("auth")
                .find({"_id": ObjectId(identifier)}, projection)
                .max_time_ms(3000)
                .limit(2)
            )
        else:
            profiles = list(
                self.collection("profiles")
                .find({"username": identifier.removeprefix("@")}, {"userId": 1, "_id": 0})
                .max_time_ms(3000)
                .limit(2)
            )
            rows = (
                list(
                    self.collection("auth")
                    .find({"_id": profiles[0]["userId"]}, projection)
                    .max_time_ms(3000)
                    .limit(2)
                )
                if len(profiles) == 1
                else []
            )
        if len(rows) != 1:
            return {"matiks_user_id": None, "identity_verified": False, "contact_verified": False}
        row = rows[0]
        return {
            "matiks_user_id": str(row["_id"]),
            "identity_verified": True,
            "contact_verified": email,
            "account_status": row.get("status"),
            "login_methods": [row["signupMethod"]] if row.get("signupMethod") else [],
        }

    def inspect(self) -> dict:
        databases = {self.database.name: set(self.database.list_collection_names())}
        payment_db = os.getenv("PAYMENTS_MONGO_DATABASE")
        if payment_db and payment_db not in databases:
            databases[payment_db] = set(self.client[payment_db].list_collection_names())
        metadata = []
        for alias, definition in self.mapping.items():
            database = payment_db if alias == "payments" else self.database.name
            present = definition["name"] in databases[database] if database else None
            indexes, field_types = [], {}
            if present:
                indexes = [
                    {"name": i["name"], "fields": dict(i["key"])}
                    for i in self.collection(alias).list_indexes()
                ][:100]
                projection = {f: 1 for f in definition.get("projection", [])}
                for row in self.collection(alias).find({}, projection).max_time_ms(3000).limit(3):
                    for key, value in row.items():
                        field_types.setdefault(key, set()).add(type(value).__name__)
            metadata.append(
                {
                    "alias": alias,
                    "collection": definition["name"],
                    "present": present,
                    "indexes": indexes,
                    "source_projection": definition.get("projection"),
                    "observed_field_types": {k: sorted(v) for k, v in field_types.items()},
                    "caveat": definition.get("caveat"),
                }
            )
        return {
            "roles": self.roles,
            "collections": metadata,
            "source_only_until_operator_confirms_schema": True,
        }


class MongoProvider:
    def __init__(self, store: Store, ticket_id: str, reader: MongoReader | None = None):
        if os.getenv("MONGO_SCHEMA_VERIFIED", "false").lower() != "true":
            raise LookupError("Inspect and verify the live schema before enabling Mongo tools")
        self.reader = reader or MongoReader()
        self.store, self.ticket_id = store, ticket_id

    def close(self):
        self.reader.close()

    def _orders(self, user_id: str) -> tuple[list[dict], bool]:
        rows, complete = self.reader.find_user("rewards", user_id)
        verified_delivery = any(
            f.get("topic") == "completed_means_delivered"
            and f.get("values", {}).get("confirmed") is True
            for f in Facts().verified("merch")
        )
        orders = []
        for row in rows:
            cake = row.get("rewardType") == "CAKE"
            ordered = row.get("igpConfirmedAt") if cake else row.get("claimedAt")
            if ordered is None:
                # Unconfirmed cake captures are evidence of ambiguity, not orders.
                complete = False
                continue
            confirmed = (
                bool(row.get("igpConfirmedAt")) if cake else row.get("reworksOrderId") is not None
            )
            delivered = (
                verified_delivery
                and row.get("reworksOrderStatus") == "completed"
                and row.get("completedAt") is not None
            )
            orders.append(
                {
                    "order_id": str(row["_id"]),
                    "user_id": user_id,
                    "item_type": row.get("rewardType", "unknown"),
                    "ordered_at": ordered,
                    "status": "delivered"
                    if delivered
                    else row.get("reworksOrderStatus", "unknown"),
                    "order_confirmed": confirmed,
                    "delivered_at": row.get("completedAt") if delivered else None,
                    "delivery_confirmed": delivered,
                }
            )
        return orders, complete

    def fetch(self, topic: str, user_id: str | None) -> tuple[dict, str]:
        if topic == "resolve_user":
            identifier = self.store.local_identity(self.ticket_id)
            if not identifier:
                raise LookupError("Ticket lacks a usable account identifier")
            return self.reader.resolve(identifier), "mongo:userAuth/userProfiles"
        if not user_id:
            raise LookupError("Resolve an unambiguous Matiks user first")
        if topic == "get_user_cohort":
            states, _ = self.reader.find_user("streak_state", user_id, 2)
            paying = None
            try:
                payments, _ = self.reader.find_user("payments", user_id, 100)
                paid = [
                    p
                    for p in payments
                    if p.get("payment_status") in {"PAID", "SETTLED"}
                    and p.get("environment") == "PRODUCTION"
                    and p.get("amount_minor", 0) > 0
                ]
                # A paid record is positive proof. An empty bounded query is not
                # proof that older billing systems/history contain no purchase.
                paying = True if paid else None
            except LookupError:
                pass
            return {
                "user_id": user_id,
                "is_paying": paying,
                "streak_days": states[0].get("currentStreak") if len(states) == 1 else None,
            }, "mongo:userStreaksNew/payments"
        if topic == "get_chat_history":
            from bson import ObjectId

            from support.moderation import conversation

            ticket = self.store.get(self.ticket_id)
            if ticket.channel != "in_app" or not re.fullmatch(
                r"[a-fA-F0-9]{24}", ticket.channel_ref
            ):
                raise LookupError(
                    "Select a source-backed in-app report for the conversation review"
                )
            rows = list(
                self.reader.collection("inapp_reports")
                .find(
                    {"_id": ObjectId(ticket.channel_ref), "reporterId": ObjectId(user_id)},
                    {"reporterId": 1, "reportedUserId": 1, "status": 1},
                )
                .max_time_ms(3000)
                .limit(2)
            )
            if len(rows) != 1 or rows[0].get("status") not in {"PENDING", "UNDER_REVIEW"}:
                raise LookupError("Current report identity/status is not verified")
            reported = str(rows[0]["reportedUserId"])
            if reported == user_id:
                raise ValueError("A report cannot identify the reporter as the other user")
            return conversation(user_id, reported), "matiks-admin-query:getAdminConversationHistory"
        if topic == "get_purchases":
            rows, complete = self.reader.find_user("payments", user_id, 50)
            purchases = [
                {
                    key: str(value)
                    if key == "_id"
                    else value.isoformat()
                    if isinstance(value, datetime)
                    else value
                    for key, value in row.items()
                    if key != "user_id"
                }
                for row in rows
            ]
            return {
                "user_id": user_id,
                "purchases": purchases,
                "complete": complete,
            }, "mongo:payments"
        if topic == "get_streak_history":
            states, _ = self.reader.find_user("streak_state", user_id, 2)
            # Use a server-side array slice. A missing historical balance/setting
            # cannot be reconstructed merely from current inventory.
            from bson import ObjectId

            histories = list(
                self.reader.collection("streak_history")
                .find({"_id": ObjectId(user_id)}, {"streakHistoryObj": {"$slice": -90}})
                .max_time_ms(3000)
                .limit(1)
            )
            state = states[0] if len(states) == 1 else {}
            history = histories[0].get("streakHistoryObj") if histories else None
            dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", self.store.get(self.ticket_id).body)
            return {
                "user_id": user_id,
                "incident_date": dates[0] if len(set(dates)) == 1 else None,
                "timezone": state.get("timezone"),
                "date_range_complete": False,
                "diagnostics": {
                    "current_streak": state.get("currentStreak"),
                    "current_shields": state.get("streakFreezers"),
                    "current_auto_apply": state.get("autoApplyShield"),
                    "current_status": state.get("currentStreakStatus"),
                    "recent_history": [
                        {"date": e["date"].isoformat(), "shield_used": e.get("isShieldUsed")}
                        for e in history or []
                    ],
                    "gap": "Historical shield inventory/settings and break timing are not proven by this snapshot",
                },
            }, "mongo:userStreaksNew/userStreaks"
        if topic == "get_merch_orders":
            orders, complete = self._orders(user_id)
            return {
                "user_id": user_id,
                "orders": orders,
                "complete": complete,
            }, "mongo:streakRewards"
        if topic == "get_merch_delivery_stats":
            orders, complete = self._orders(user_id)
            active = [
                o
                for o in orders
                if o["order_confirmed"]
                and o["status"].lower() not in {"cancelled", "canceled", "delivered"}
            ]
            if not complete or len(active) != 1:
                raise LookupError("Matching item requires an unambiguous confirmed order")
            item = active[0]["item_type"]
            if item == "CAKE" or not any(
                f.get("topic") == "completed_means_delivered"
                and f.get("values", {}).get("confirmed") is True
                for f in Facts().verified("merch")
            ):
                raise LookupError("Delivery semantics require independently verified policy")
            projection = {f: 1 for f in self.reader.mapping["rewards"]["projection"]}
            rows = list(
                self.reader.collection("rewards")
                .find(
                    {
                        "rewardType": item,
                        "reworksOrderStatus": "completed",
                        "completedAt": {"$gte": datetime.now(UTC) - timedelta(days=90)},
                    },
                    projection,
                )
                .sort("completedAt", -1)
                .max_time_ms(3000)
                .limit(50)
            )
            samples = [
                {
                    "order_id": str(row["_id"]),
                    "user_id": "population_sample",
                    "item_type": item,
                    "ordered_at": row["claimedAt"],
                    "status": "delivered",
                    "order_confirmed": True,
                    "delivered_at": row["completedAt"],
                    "delivery_confirmed": True,
                }
                for row in rows
                if row.get("claimedAt")
                and row.get("completedAt")
                and row.get("reworksOrderId") is not None
            ]
            return {
                "item_type": item,
                "orders": samples,
                "sample_description": "Up to 50 latest verified completed orders of the same item in the previous 90 days",
            }, "mongo:streakRewards/matching-deliveries"
        # Statistics need explicitly confirmed delivery semantics and a bounded
        # matching-item population query; source inspection alone is insufficient.
        raise LookupError(f"{topic} needs a separately verified source")


def configured_provider(store: Store, ticket_id: str):
    from support.repository import CompositeProvider, RepositoryProvider

    data, repository = None, None
    if os.getenv("MONGO_SCHEMA_VERIFIED", "false").lower() == "true":
        try:
            data = MongoProvider(store, ticket_id)
        except Exception as error:
            store.event(
                ticket_id,
                "source_setup_failed",
                {"source": "mongo", "error_type": type(error).__name__},
            )
    if os.getenv("REPO_PATH"):
        try:
            repository = RepositoryProvider(Path(os.environ["REPO_PATH"]), store.get(ticket_id))
        except Exception as error:
            store.event(
                ticket_id,
                "source_setup_failed",
                {"source": "repository", "error_type": type(error).__name__},
            )
    return CompositeProvider(data, repository) if data or repository else None
