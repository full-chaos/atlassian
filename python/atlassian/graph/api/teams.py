from __future__ import annotations

from typing import Iterator, List, Optional, Sequence

from ...canonical_models import AtlassianTeam
from ...errors import GraphQLOperationError, SerializationError
from ..client import GraphQLClient
from ..gen import teams_api as api
from ..mappers.teams import map_team


def get_team_by_id(
    client: GraphQLClient,
    team_id: str,
    *,
    site_id: Optional[str] = None,
    experimental_apis: Optional[Sequence[str]] = None,
) -> AtlassianTeam:
    team_id_clean = (team_id or "").strip()
    if not team_id_clean:
        raise ValueError("team_id is required")

    variables = {"teamId": team_id_clean}
    if site_id is not None:
        variables["siteId"] = site_id.strip()

    apis = list(experimental_apis) if experimental_apis is not None else list(api.EXPERIMENTAL_APIS)

    result = client.execute(
        api.TEAM_BY_ID_QUERY,
        variables=variables,
        operation_name="TeamById",
        experimental_apis=apis,
    )
    if result.data is None:
        raise SerializationError("Missing GraphQL data in response")

    try:
        team_node = api.parse_team_by_id(result.data)
    except SerializationError as exc:
        if result.errors:
            raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
        raise

    return map_team(team_node)


def iter_teams(
    client: GraphQLClient,
    organization_id: str,
    site_id: str,
    *,
    query: str = "",
    first: int = 50,
    experimental_apis: Optional[Sequence[str]] = None,
) -> Iterator[AtlassianTeam]:
    org_id_clean = (organization_id or "").strip()
    if not org_id_clean:
        raise ValueError("organization_id is required")
    site_id_clean = (site_id or "").strip()
    if not site_id_clean:
        raise ValueError("site_id is required")
    if first <= 0:
        raise ValueError("first must be > 0")

    apis = list(experimental_apis) if experimental_apis is not None else list(api.EXPERIMENTAL_APIS)

    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        variables = {
            "organizationId": org_id_clean,
            "siteId": site_id_clean,
            "query": query,
            "first": first,
            "after": after,
        }
        result = client.execute(
            api.TEAM_SEARCH_V2_QUERY,
            variables=variables,
            operation_name="TeamSearchV2",
            experimental_apis=apis,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        try:
            conn = api.parse_team_search_v2(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise

        if api.TEAM_SEARCH_USES_EDGES:
            edges = conn.edges or []
            for edge in edges:
                node = edge.node
                if api.TEAM_SEARCH_NODE_TYPE == api.TEAM_TYPE_NAME:
                    team_node = node
                else:
                    team_node = node.team  # type: ignore[union-attr]
                yield map_team(team_node)
        else:
            nodes = conn.nodes or []
            for node in nodes:
                if api.TEAM_SEARCH_NODE_TYPE == api.TEAM_TYPE_NAME:
                    team_node = node
                else:
                    team_node = node.team  # type: ignore[union-attr]
                yield map_team(team_node)

        page_info = conn.page_info
        if page_info is None or not page_info.has_next_page:
            break

        next_after: Optional[str] = None
        if api.TEAM_SEARCH_PAGEINFO_HAS_END_CURSOR and page_info.end_cursor:
            next_after = page_info.end_cursor
        elif api.TEAM_SEARCH_USES_EDGES and api.TEAM_SEARCH_EDGE_HAS_CURSOR:
            edges = conn.edges or []
            for edge in reversed(edges):
                if edge.cursor:
                    next_after = edge.cursor
                    break

        if next_after is None:
            raise SerializationError("Pagination cursor missing for teamSearchV2")
        if next_after in seen_after:
            raise SerializationError(
                "Pagination cursor repeated; aborting to prevent infinite loop"
            )
        seen_after.add(next_after)
        after = next_after


def list_teams(
    client: GraphQLClient,
    organization_id: str,
    site_id: str,
    *,
    query: str = "",
    first: int = 50,
    experimental_apis: Optional[Sequence[str]] = None,
) -> List[AtlassianTeam]:
    return list(
        iter_teams(
            client,
            organization_id,
            site_id,
            query=query,
            first=first,
            experimental_apis=experimental_apis,
        )
    )
