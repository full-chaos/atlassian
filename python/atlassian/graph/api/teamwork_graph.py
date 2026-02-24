from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Sequence

from ...canonical_models import TeamworkProject, TeamworkUserRelation
from ...errors import GraphQLOperationError, SerializationError
from ..client import GraphQLClient
from ..gen import teamwork_graph_api as api
from ..mappers.teams import map_teamwork_project, map_teamwork_user_relation

# Teamwork Graph APIs are EAP/experimental. They require @optIn(to: "TeamworkGraphContextAPIs")
# and are not available for OAuth-authenticated requests.
# Manager relationship queries require the X-Force-Dynamo: true header.

_TWG_EXPERIMENTAL_APIS = [api.TEAMWORK_GRAPH_OPT_IN]
_FORCE_DYNAMO_HEADERS: Dict[str, str] = {"X-Force-Dynamo": "true"}


def _twg_apis(extra: Optional[Sequence[str]] = None) -> List[str]:
    apis = list(_TWG_EXPERIMENTAL_APIS)
    if extra:
        for e in extra:
            if e and e not in apis:
                apis.append(e)
    return apis


def _paginate_twg(
    client: GraphQLClient,
    query: str,
    operation_name: str,
    variables: dict,
    experimental_apis: List[str],
    extra_headers: Optional[Dict[str, str]] = None,
) -> Iterator[api.GraphStoreCypherQueryV2Node]:
    """Generic paginator for Teamwork Graph connection queries."""
    after: Optional[str] = None
    seen_after: set[str] = set()

    while True:
        variables["after"] = after
        result = client.execute(
            query,
            variables=variables,
            operation_name=operation_name,
            experimental_apis=experimental_apis,
            extra_headers=extra_headers,
        )
        if result.data is None:
            raise SerializationError("Missing GraphQL data in response")

        # Use the appropriate parse function based on the operation name
        _parse_fn_map = {
            "TeamworkGraph_teamActiveProjects": api.parse_teamworkGraph_teamActiveProjects,
            "TeamworkGraph_teamUsers": api.parse_teamworkGraph_teamUsers,
            "TeamworkGraph_userTeams": api.parse_teamworkGraph_userTeams,
            "TeamworkGraph_userManager": api.parse_teamworkGraph_userManager,
            "TeamworkGraph_userDirectReports": api.parse_teamworkGraph_userDirectReports,
        }
        parse_fn = _parse_fn_map[operation_name]
        try:
            conn = parse_fn(result.data)
        except SerializationError as exc:
            if result.errors:
                raise GraphQLOperationError(errors=result.errors, partial_data=result.data) from exc
            raise

        for edge in conn.edges:
            yield edge.node

        if not conn.page_info.has_next_page:
            break

        next_after = conn.page_info.end_cursor
        if not next_after:
            raise SerializationError(f"Pagination cursor missing for {operation_name}")
        if next_after in seen_after:
            raise SerializationError(
                f"Pagination cursor repeated for {operation_name}; aborting to prevent infinite loop"
            )
        seen_after.add(next_after)
        after = next_after


def iter_team_active_projects(
    client: GraphQLClient,
    team_id: str,
    *,
    first: int = 50,
) -> Iterator[TeamworkProject]:
    team_id_clean = (team_id or "").strip()
    if not team_id_clean:
        raise ValueError("team_id is required")
    if first <= 0:
        raise ValueError("first must be > 0")

    variables: dict = {"teamId": team_id_clean, "first": first}
    for node in _paginate_twg(
        client,
        api.TEAMWORKGRAPH_TEAMACTIVEPROJECTS,
        "TeamworkGraph_teamActiveProjects",
        variables,
        _twg_apis(),
    ):
        yield map_teamwork_project(node)


def iter_team_users(
    client: GraphQLClient,
    team_id: str,
    *,
    first: int = 50,
) -> Iterator[TeamworkUserRelation]:
    team_id_clean = (team_id or "").strip()
    if not team_id_clean:
        raise ValueError("team_id is required")
    if first <= 0:
        raise ValueError("first must be > 0")

    variables: dict = {"teamId": team_id_clean, "first": first}
    for node in _paginate_twg(
        client,
        api.TEAMWORKGRAPH_TEAMUSERS,
        "TeamworkGraph_teamUsers",
        variables,
        _twg_apis(),
    ):
        yield map_teamwork_user_relation(node=node, relation_type="TEAM_MEMBER")


def iter_user_teams(
    client: GraphQLClient,
    user_id: str,
    *,
    first: int = 50,
) -> Iterator[TeamworkUserRelation]:
    user_id_clean = (user_id or "").strip()
    if not user_id_clean:
        raise ValueError("user_id is required")
    if first <= 0:
        raise ValueError("first must be > 0")

    variables: dict = {"userId": user_id_clean, "first": first}
    for node in _paginate_twg(
        client,
        api.TEAMWORKGRAPH_USERTEAMS,
        "TeamworkGraph_userTeams",
        variables,
        _twg_apis(),
    ):
        yield map_teamwork_user_relation(
            node=node, relation_type="TEAM_MEMBER", subject_user_id=user_id_clean
        )


def get_user_manager(
    client: GraphQLClient,
    user_id: str,
) -> Optional[TeamworkUserRelation]:
    user_id_clean = (user_id or "").strip()
    if not user_id_clean:
        raise ValueError("user_id is required")

    variables: dict = {"userId": user_id_clean}
    results = list(
        _paginate_twg(
            client,
            api.TEAMWORKGRAPH_USERMANAGER,
            "TeamworkGraph_userManager",
            variables,
            _twg_apis(),
            extra_headers=_FORCE_DYNAMO_HEADERS,
        )
    )
    if not results:
        return None
    return map_teamwork_user_relation(
        node=results[0], relation_type="REPORTS_TO", subject_user_id=user_id_clean
    )


def iter_user_direct_reports(
    client: GraphQLClient,
    user_id: str,
    *,
    first: int = 50,
) -> Iterator[TeamworkUserRelation]:
    user_id_clean = (user_id or "").strip()
    if not user_id_clean:
        raise ValueError("user_id is required")
    if first <= 0:
        raise ValueError("first must be > 0")

    variables: dict = {"userId": user_id_clean}
    for node in _paginate_twg(
        client,
        api.TEAMWORKGRAPH_USERDIRECTREPORTS,
        "TeamworkGraph_userDirectReports",
        variables,
        _twg_apis(),
        extra_headers=_FORCE_DYNAMO_HEADERS,
    ):
        yield map_teamwork_user_relation(
            node=node, relation_type="MANAGES", subject_user_id=user_id_clean
        )
