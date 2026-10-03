"""Exactly one admin GraphQL read operation for a scoped DM conversation."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

from support.config import ROOT

QUERY = """query SupportConversation($reporterId: ID!, $reportedUserId: ID!) {
  getAdminConversationHistory(reporterId: $reporterId, reportedUserId: $reportedUserId, limit: 10) {
    hasMore
    messages { _id sender groupId content createdAt }
  }
}"""


def connection_settings() -> tuple[str | None, str | None]:
    local = dotenv_values(ROOT / ".env", interpolate=False)
    url = os.getenv("MATIKS_GRAPHQL_URL") or local.get("MATIKS_GRAPHQL_URL")
    token = local.get("MATIKS_ADMIN_READ_TOKEN") or os.getenv("MATIKS_ADMIN_READ_TOKEN")
    if not url:
        host = dotenv_values(ROOT / ".env.client", interpolate=False).get("EXPO_PUBLIC_SERVER_HOST")
        if host and "://" not in host and "/" not in host:
            url = "https://" + host + "/api"
    return url, token


def conversation(reporter_id: str, reported_id: str) -> dict:
    url, token = connection_settings()
    if not url or not token:
        raise LookupError("Admin conversation read is not configured; Mongo content is encrypted")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use an HTTPS GraphQL URL without embedded credentials")
    if any(c in token for c in "\r\n"):
        raise ValueError("Invalid credential")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "query": QUERY,
                "variables": {"reporterId": reporter_id, "reportedUserId": reported_id},
            },
        )
        if response.status_code != 200:
            raise LookupError("Conversation read request failed")
        if len(response.content) > 100000:
            raise ValueError("Conversation response exceeds limit")
        payload = response.json()
    if payload.get("errors"):
        raise LookupError("Conversation query was not authorized or failed")
    record = payload.get("data", {}).get("getAdminConversationHistory")
    if not isinstance(record, dict) or not isinstance(record.get("messages"), list):
        raise LookupError("Conversation response did not match the source contract")
    excerpts = []
    for message in record["messages"][:10]:
        if message.get("sender") not in {reporter_id, reported_id}:
            raise ValueError("Conversation contains an unexpected sender")
        if not isinstance(message.get("content"), str):
            raise ValueError("Conversation content is missing")
        excerpts.append(
            {
                "message_id": message["_id"],
                "sender_id": message["sender"],
                "created_at": message["createdAt"],
                "text": message["content"][:1200],
            }
        )
    return {
        "reporter_id": reporter_id,
        "reported_id": reported_id,
        "severity_verified": False,
        "violation_found": None,
        "reporter_aggressor": None,
        "excerpts": excerpts,
    }
