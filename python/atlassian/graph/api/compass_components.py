from __future__ import annotations

import json
import os
from typing import Iterator, List, Optional, Sequence

from ...auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from ...canonical_models import CompassComponent, CompassScorecardScore
from ...errors import GraphQLOperationError, SerializationError
from ...oauth_3lo import OAuthRefreshTokenAuth
from ..client import GraphQLClient
from ..gen import compass_components_api as components_api
from ..gen import compass_scorecards_api as scorecards_api
from ..mappers.compass_components import map_compass_component, map_compass_scorecard_score


def _env_experimental_apis() -> List[str]:
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
    if end_cursor:
        return end_cursor
    if edge_has_cursor:
        for cursor in reversed(edges_cursors):
            if cursor:
                return cursor
    raise SerializationError(f"Pagination cursor missing for {path}")


def iter_compass_components(
    client: GraphQLClient,
    cloud_id: str,
    page_size: int = 50,
    *,
    query: Optional[dict] = None,
    experimental_apis: Optional[Sequence[str]] = None,
) -> Iterator[CompassComponent]:
    """Iterate all Compass components for a cloud site, handling pagination."""
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        variables: dict = {"cloudId": cloud_id_clean}
        search_query: dict = {"first": page_size}
        if after:
            search_query["after"] = after
        if query:
            search_query.update(query)
        variables["query"] = search_query

        result = client.execute(
            components_api.COMPASS_SEARCH_COMPONENTS_QUERY,
            variables=variables,
            operation_name="CompassSearchComponents",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        try:
            parsed = components_api.parse_compass_search_components(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise

        if isinstance(parsed, components_api.QueryError):
            raise GraphQLOperationError(
                errors=[{"message": parsed.message}],
                partial_data=result.data,
            )

        conn = parsed
        for edge in conn.edges:
            node = edge.node
            if node.component is not None:
                yield map_compass_component(cloud_id=cloud_id_clean, component=node.component)

        next_after = _next_after_from_pageinfo(
            has_next_page=conn.page_info.has_next_page,
            end_cursor=conn.page_info.end_cursor,
            edge_has_cursor=components_api.EDGE_HAS_CURSOR,
            edges_cursors=[e.cursor for e in conn.edges],
            path="compass.searchComponents",
        )
        if next_after is None:
            break
        if next_after in seen_after:
            raise SerializationError("Pagination cursor repeated; aborting to prevent infinite loop")
        seen_after.add(next_after)
        after = next_after


def iter_compass_component_scorecard_scores(
    client: GraphQLClient,
    component_id: str,
    *,
    experimental_apis: Optional[Sequence[str]] = None,
) -> Iterator[CompassScorecardScore]:
    """Iterate all scorecard scores for a single Compass component, handling pagination."""
    component_id_clean = (component_id or "").strip()
    if not component_id_clean:
        raise ValueError("component_id is required")

    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        variables: dict = {"componentId": component_id_clean}
        if after:
            variables["after"] = after

        result = client.execute(
            scorecards_api.COMPASS_COMPONENT_SCORECARDS_QUERY,
            variables=variables,
            operation_name="CompassComponentScorecards",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        try:
            parsed = scorecards_api.parse_compass_component_scorecards(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise

        if isinstance(parsed, scorecards_api.QueryError):
            raise GraphQLOperationError(
                errors=[{"message": parsed.message}],
                partial_data=result.data,
            )

        conn = parsed
        for edge in conn.edges:
            node = edge.node
            yield map_compass_scorecard_score(component_id_clean, node)

        next_after = _next_after_from_pageinfo(
            has_next_page=conn.page_info.has_next_page,
            end_cursor=conn.page_info.end_cursor,
            edge_has_cursor=scorecards_api.EDGE_HAS_CURSOR,
            edges_cursors=[e.cursor for e in conn.edges],
            path=f"compass.component[{component_id_clean}].appliedScorecards",
        )
        if next_after is None:
            break
        if next_after in seen_after:
            raise SerializationError("Pagination cursor repeated; aborting to prevent infinite loop")
        seen_after.add(next_after)
        after = next_after


def list_compass_components(
    cloud_id: str,
    page_size: int = 50,
    *,
    query: Optional[dict] = None,
) -> Iterator[CompassComponent]:
    """List all Compass components using credentials from environment variables."""
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
        yield from iter_compass_components(
            client,
            cloud_id,
            page_size,
            query=query,
            experimental_apis=experimental_apis or None,
        )


def list_compass_component_scorecard_scores(
    component_id: str,
) -> Iterator[CompassScorecardScore]:
    """List all scorecard scores for a Compass component using credentials from environment variables."""
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
        yield from iter_compass_component_scorecard_scores(
            client,
            component_id,
            experimental_apis=experimental_apis or None,
        )
