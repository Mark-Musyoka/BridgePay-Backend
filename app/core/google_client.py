"""
Shared Google OAuth 2.0 primitives — the standard authorization-code
flow documented at
https://developers.google.com/identity/protocols/oauth2/web-server

Uses plain httpx calls against Google's OAuth endpoints rather than a
dedicated SDK (google-auth-oauthlib etc.) — these are stable, simple
REST endpoints and a full SDK would be more dependency than this needs.
"""

import secrets
from urllib.parse import urlencode

import httpx

from app.core.config import settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = ["openid", "email", "profile"]


def generate_oauth_state() -> str:
    """CSRF protection for the OAuth flow — a random value the caller is
    expected to store (e.g. in a short-lived cookie) before redirecting
    to Google, then compare against what Google sends back in the
    callback. See https://developers.google.com/identity/protocols/oauth2/web-server#creatingclient
    """
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "online",  # we don't need a refresh token from Google itself
        "prompt": "select_account",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
    response.raise_for_status()
    return response.json()


async def get_google_user_info(access_token: str) -> dict:
    """Returns Google's userinfo payload — notably 'email',
    'email_verified', 'name', 'sub' (Google's stable user id)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
    response.raise_for_status()
    return response.json()
