from __future__ import annotations

import json
import os
from typing import Optional, Sequence

from ...auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from ...canonical_models import JiraSprint
from ...errors import GraphQLOperationError, SerializationError
from ...oauth_3lo import OAuthRefreshTokenAuth
from ..client import GraphQLClient
from ..gen import jira_sprints_api as api
from ..mappers.jira_sprints import map_sprint


def _env_experimental_apis() -> list[str]:
    raw = os.getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _auth_from_env():
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


def get_sprint_by_id(
    client: GraphQLClient,
    sprint_id: str,
    *,
    experimental_apis: Optional[Sequence[str]] = None,
) -> JiraSprint:
    sprint_id_clean = (sprint_id or "").strip()
    if not sprint_id_clean:
        raise ValueError("sprint_id is required")

    result = client.execute(
        api.JIRA_SPRINT_BY_ID_QUERY,
        variables={"id": sprint_id_clean},
        operation_name="JiraSprintById",
        experimental_apis=list(experimental_apis) if experimental_apis else None,
    )
    if result.data is None:
        raise SerializationError("Missing GraphQL data in response")

    try:
        sprint = api.parse_jira_sprint_by_id(result.data)
    except SerializationError as exc:
        if result.errors:
            raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
        raise

    return map_sprint(sprint=sprint)


def fetch_sprint_by_id(
    sprint_id: str,
) -> JiraSprint:
    base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
    auth = _auth_from_env()
    if not base_url and (
        os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN") or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
    ):
        base_url = "https://api.atlassian.com"
    if not base_url or auth is None:
        raise ValueError(
            "Missing ATLASSIAN_GQL_BASE_URL and/or credentials. "
            "Set ATLASSIAN_OAUTH_ACCESS_TOKEN, or ATLASSIAN_OAUTH_REFRESH_TOKEN + "
            "(ATLASSIAN_CLIENT_ID + ATLASSIAN_CLIENT_SECRET), or "
            "(ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN), or ATLASSIAN_COOKIES_JSON."
        )

    experimental_apis = _env_experimental_apis()
    with GraphQLClient(base_url, auth=auth, timeout_seconds=30.0) as client:
        return get_sprint_by_id(
            client,
            sprint_id=sprint_id,
            experimental_apis=experimental_apis or None,
        )
