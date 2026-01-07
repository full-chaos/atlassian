from __future__ import annotations

import json
import os
from typing import Iterator, Optional, Sequence

from ...auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from ...canonical_models import JiraWorklog
from ...errors import GraphQLOperationError, SerializationError
from ...oauth_3lo import OAuthRefreshTokenAuth
from ..client import GraphQLClient
from ..gen import jira_worklogs_api as api
from ..mappers.jira_worklogs import map_worklog


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


def _next_after_from_pageinfo(
    *,
    has_next_page: bool,
    end_cursor: Optional[str],
    edge_has_cursor: bool,
    edges_cursors: Sequence[Optional[str]],
    path: str,
) -> Optional[str]:
    if not has_next_page:
        return None
    if api.PAGEINFO_HAS_END_CURSOR and end_cursor:
        return end_cursor
    if edge_has_cursor:
        for cursor in reversed(edges_cursors):
            if cursor:
                return cursor
    raise SerializationError(f"Pagination cursor missing for {path}")


def iter_issue_worklogs_via_graphql(
    client: GraphQLClient,
    *,
    cloud_id: str,
    issue_key: str,
    page_size: int = 50,
    experimental_apis: Optional[Sequence[str]] = None,
) -> Iterator[JiraWorklog]:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    issue_key_clean = (issue_key or "").strip()
    if not issue_key_clean:
        raise ValueError("issue_key is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        result = client.execute(
            api.JIRA_ISSUE_WORKLOGS_PAGE_QUERY,
            variables={
                "cloudId": cloud_id_clean,
                "key": issue_key_clean,
                "first": page_size,
                "after": after,
            },
            operation_name="JiraIssueWorklogsPage",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        try:
            conn = api.parse_issue_worklogs_page(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise

        for edge in conn.edges:
            yield map_worklog(issue_key=issue_key_clean, worklog=edge.node)

        next_after = _next_after_from_pageinfo(
            has_next_page=conn.page_info.has_next_page,
            end_cursor=conn.page_info.end_cursor,
            edge_has_cursor=api.WORKLOGS_EDGE_HAS_CURSOR,
            edges_cursors=[e.cursor for e in conn.edges],
            path=f"jira.issue[{issue_key_clean}].worklogs",
        )
        if next_after is None:
            break
        if next_after in seen_after:
            raise SerializationError("Pagination cursor repeated; aborting to prevent infinite loop")
        seen_after.add(next_after)
        after = next_after


def list_issue_worklogs_via_graphql(
    cloud_id: str,
    issue_key: str,
    page_size: int = 50,
) -> Iterator[JiraWorklog]:
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
        yield from iter_issue_worklogs_via_graphql(
            client,
            cloud_id=cloud_id,
            issue_key=issue_key,
            page_size=page_size,
            experimental_apis=experimental_apis or None,
        )
