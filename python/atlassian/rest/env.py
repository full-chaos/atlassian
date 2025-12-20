from __future__ import annotations

import json
import os
from typing import Optional

from ..auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from ..oauth_3lo import OAuthRefreshTokenAuth


def auth_from_env():
    token = os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
    refresh_token = os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
    client_id = os.getenv("ATLASSIAN_CLIENT_ID")
    client_secret = os.getenv("ATLASSIAN_CLIENT_SECRET")
    email = os.getenv("ATLASSIAN_EMAIL")
    api_token = os.getenv("ATLASSIAN_API_TOKEN")
    cookies_json = os.getenv("ATLASSIAN_COOKIES_JSON")

    if refresh_token and client_id and client_secret:
        return OAuthRefreshTokenAuth(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
    if token:
        if client_secret and token.strip() == client_secret.strip():
            raise ValueError(
                "ATLASSIAN_OAUTH_ACCESS_TOKEN appears to be set to ATLASSIAN_CLIENT_SECRET; "
                "set an OAuth access token (not the client secret)."
            )
        return OAuthBearerAuth(lambda: token)
    if email and api_token:
        return BasicApiTokenAuth(email, api_token)
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
        except json.JSONDecodeError:
            return None
        if isinstance(cookies, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()
        ):
            return CookieAuth(cookies)
    return None


def _derive_site_base_url_from_gql_base(gql_base_url: str) -> Optional[str]:
    candidate = (gql_base_url or "").strip().rstrip("/")
    if not candidate:
        return None
    for suffix in ("/gateway/api/graphql", "/gateway/api", "/graphql"):
        if candidate.endswith(suffix):
            stripped = candidate[: -len(suffix)]
            return stripped.rstrip("/")
    return None


def jira_rest_base_url_from_env(cloud_id: str) -> Optional[str]:
    explicit = os.getenv("ATLASSIAN_JIRA_BASE_URL")
    if explicit and explicit.strip():
        return explicit.strip().rstrip("/")

    if os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN") or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN"):
        cloud_id_clean = (cloud_id or "").strip()
        if not cloud_id_clean:
            return None
        return f"https://api.atlassian.com/ex/jira/{cloud_id_clean}"

    gql_base = os.getenv("ATLASSIAN_GQL_BASE_URL")
    if gql_base:
        return _derive_site_base_url_from_gql_base(gql_base)
    return None
