from __future__ import annotations

import os

import httpx


def refresh_google_token() -> tuple[str, set[str]]:
    """Refresh in memory only; never log, print, or persist access tokens."""
    fields = {
        "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token": os.getenv("IMAP_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }
    if not all(fields.values()):
        raise ValueError("Google OAuth client ID, secret and refresh token are required")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.post("https://oauth2.googleapis.com/token", data=fields)
    if response.status_code != 200:
        # Never include Google's body: it may contain client or token information.
        raise ValueError(f"Google OAuth refresh failed (HTTP {response.status_code})")
    data = response.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token or any(c in token for c in ("\r", "\n", "\x01")):
        raise ValueError("Google OAuth returned an invalid access token")
    return token, set(data.get("scope", "").split())
