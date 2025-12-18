from __future__ import annotations

import json
import os
from typing import Iterator, List, Optional, Sequence

from ...auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from ...canonical_models import CanonicalProjectWithOpsgenieTeams
from ...errors import GraphQLOperationError, SerializationError
from ...oauth_3lo import OAuthRefreshTokenAuth
from ..client import GraphQLClient
from ..gen import jira_projects_api as api
from ..mappers.jira_projects import map_project_with_opsgenie_teams


def _normalize_project_types(project_types: Sequence[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in project_types:
        if not isinstance(raw, str):
            raise ValueError("project_types must be strings")
        value = raw.strip().upper()
        if not value:
            continue
        cleaned.append(value)
    if not cleaned:
        raise ValueError("project_types must be non-empty")
    return cleaned


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
    if api.PAGEINFO_HAS_END_CURSOR and end_cursor:
        return end_cursor
    if edge_has_cursor:
        for cursor in reversed(edges_cursors):
            if cursor:
                return cursor
    raise SerializationError(f"Pagination cursor missing for {path}")


def iter_projects_with_opsgenie_linkable_teams(
    client: GraphQLClient,
    cloud_id: str,
    project_types: List[str],
    page_size: int = 50,
    *,
    experimental_apis: Optional[Sequence[str]] = None,
) -> Iterator[CanonicalProjectWithOpsgenieTeams]:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    normalized_types = _normalize_project_types(project_types)
    query = api.build_jira_projects_page_query(normalized_types)

    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        variables = {
            "cloudId": cloud_id_clean,
            "first": page_size,
            "after": after,
            "opsFirst": page_size,
        }
        result = client.execute(
            query,
            variables=variables,
            operation_name="JiraProjectsPage",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        try:
            page = api.parse_jira_projects_page(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise
        conn = page.projects

        for edge in conn.edges:
            project = edge.node
            teams_conn = project.opsgenie_teams
            teams = [e.node for e in teams_conn.edges]
            if teams_conn.page_info.has_next_page:
                teams.extend(
                    _paginate_opsgenie_teams(
                        client=client,
                        cloud_id=cloud_id_clean,
                        project=project,
                        initial_connection=teams_conn,
                        page_size=page_size,
                        experimental_apis=experimental_apis,
                    )
                )

            yield map_project_with_opsgenie_teams(
                cloud_id=cloud_id_clean,
                project=project,
                opsgenie_teams=teams,
            )

        next_after = _next_after_from_pageinfo(
            has_next_page=conn.page_info.has_next_page,
            end_cursor=conn.page_info.end_cursor,
            edge_has_cursor=api.PROJECTS_EDGE_HAS_CURSOR,
            edges_cursors=[e.cursor for e in conn.edges],
            path="jira.projects",
        )
        if next_after is None:
            break
        if next_after in seen_after:
            raise SerializationError("Pagination cursor repeated; aborting to prevent infinite loop")
        seen_after.add(next_after)
        after = next_after


def list_projects_with_opsgenie_linkable_teams(
    cloud_id: str,
    project_types: List[str],
    page_size: int = 50,
) -> Iterator[CanonicalProjectWithOpsgenieTeams]:
    base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
    auth = _auth_from_env()
    if not base_url and (
        os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
        or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
    ):
        base_url = "https://api.atlassian.com"
    if not base_url or auth is None:
        raise ValueError(
            "Missing ATLASSIAN_GQL_BASE_URL and/or credentials. "
            "Set ATLASSIAN_OAUTH_ACCESS_TOKEN, or ATLASSIAN_OAUTH_REFRESH_TOKEN + (ATLASSIAN_CLIENT_ID + ATLASSIAN_CLIENT_SECRET), "
            "or (ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN), or ATLASSIAN_COOKIES_JSON."
        )

    experimental_apis = _env_experimental_apis()
    with GraphQLClient(base_url, auth=auth, timeout_seconds=30.0) as client:
        yield from iter_projects_with_opsgenie_linkable_teams(
            client,
            cloud_id,
            project_types,
            page_size,
            experimental_apis=experimental_apis or None,
        )

def _paginate_opsgenie_teams(
    *,
    client: GraphQLClient,
    cloud_id: str,
    project: api.JiraProjectNode,
    initial_connection: api.OpsgenieTeamsConnection,
    page_size: int,
    experimental_apis: Optional[Sequence[str]],
) -> List[api.OpsgenieTeamNode]:
    after = _next_after_from_pageinfo(
        has_next_page=initial_connection.page_info.has_next_page,
        end_cursor=initial_connection.page_info.end_cursor,
        edge_has_cursor=api.OPSGENIE_EDGE_HAS_CURSOR,
        edges_cursors=[e.cursor for e in initial_connection.edges],
        path=f"jira.project[{project.key}].opsgenieTeams",
    )
    if after is None:
        return []

    query = api.JIRA_PROJECT_OPSGENIE_TEAMS_PAGE_QUERY
    seen_after: set[str] = {after}
    out: List[api.OpsgenieTeamNode] = []

    while True:
        if api.REFETCH_STRATEGY == "node":
            project_id = (project.id or "").strip()
            if not project_id:
                raise SerializationError("Project id is required for node-based opsgenie pagination")
            variables = {"projectId": project_id, "first": page_size, "after": after}
        else:
            project_key = (project.key or "").strip()
            if not project_key:
                raise SerializationError("Project key is required for opsgenie pagination")
            variables = {
                "cloudId": cloud_id,
                "projectKey": project_key,
                "first": page_size,
                "after": after,
            }

        result = client.execute(
            query,
            variables=variables,
            operation_name="JiraProjectOpsgenieTeamsPage",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in opsgenie pagination response")

        try:
            conn = api.parse_project_opsgenie_teams(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise
        out.extend([e.node for e in conn.edges])

        next_after = _next_after_from_pageinfo(
            has_next_page=conn.page_info.has_next_page,
            end_cursor=conn.page_info.end_cursor,
            edge_has_cursor=api.OPSGENIE_EDGE_HAS_CURSOR,
            edges_cursors=[e.cursor for e in conn.edges],
            path=f"jira.project[{project.key}].opsgenieTeams",
        )
        if next_after is None:
            break
        if next_after in seen_after:
            raise SerializationError("Opsgenie pagination cursor repeated; aborting")
        seen_after.add(next_after)
        after = next_after

    return out
