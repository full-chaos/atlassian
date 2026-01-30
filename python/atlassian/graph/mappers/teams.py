from __future__ import annotations

from typing import Any, Iterable, Optional

from ...canonical_models import (
    AtlassianTeam,
    AtlassianTeamMember,
    TeamworkProject,
    TeamworkUserRelation,
)
from ..gen.teamwork_graph_api import (
    GraphStoreCypherQueryV2AriNode,
    GraphStoreCypherQueryV2Column,
    GraphStoreCypherQueryV2Node,
    GraphStoreCypherQueryV2NodeList,
)


def _require_non_empty(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def map_team(team: Any) -> AtlassianTeam:
    if team is None:
        raise ValueError("team is required")

    team_id = _require_non_empty(getattr(team, "id", None), "team.id")
    display_name = _require_non_empty(
        getattr(team, "display_name", None), "team.displayName"
    )
    state = _require_non_empty(getattr(team, "state", None), "team.state")

    return AtlassianTeam(
        id=team_id,
        display_name=display_name,
        state=state,
        description=_optional_str(getattr(team, "description", None)),
        avatar_url=_optional_str(getattr(team, "avatar_url", None)),
        member_count=_optional_int(getattr(team, "member_count", None)),
    )


def map_team_member(*, team_id: str, member: Any) -> AtlassianTeamMember:
    if member is None:
        raise ValueError("member is required")

    canonical_team_id = _require_non_empty(team_id, "teamId")
    account_id = _require_non_empty(
        getattr(member, "account_id", None), "member.accountId"
    )

    return AtlassianTeamMember(
        team_id=canonical_team_id,
        account_id=account_id,
        display_name=_optional_str(getattr(member, "display_name", None)),
        role=_optional_str(getattr(member, "role", None)),
    )


TEAM_ARI_PREFIX = "ari:cloud:identity::team/"
USER_ARI_PREFIX = "ari:cloud:identity::user/"
TEAM_TYPENAMES = {"TeamV2"}
USER_TYPENAMES = {"AtlassianAccountUser"}
PROJECT_TYPENAMES = {"JiraProject", "TownsquareProject"}


def _require_non_empty_str(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def _iter_nodes_from_value(value: Any) -> Iterable[GraphStoreCypherQueryV2AriNode]:
    if isinstance(value, GraphStoreCypherQueryV2AriNode):
        yield value
    elif isinstance(value, GraphStoreCypherQueryV2NodeList):
        yield from value.nodes


def _iter_nodes_from_columns(
    columns: Iterable[GraphStoreCypherQueryV2Column],
) -> Iterable[GraphStoreCypherQueryV2AriNode]:
    for column in columns:
        if column.value is None:
            continue
        yield from _iter_nodes_from_value(column.value)


def _column_key_matches(
    column: GraphStoreCypherQueryV2Column, keys: Iterable[str]
) -> bool:
    key = column.key.strip().lower()
    return any(key == candidate for candidate in keys)


def _select_node_by_key(
    columns: Iterable[GraphStoreCypherQueryV2Column],
    keys: Iterable[str],
    predicate,
) -> Optional[GraphStoreCypherQueryV2AriNode]:
    candidates = []
    for column in columns:
        if not _column_key_matches(column, keys):
            continue
        if column.value is None:
            continue
        for node in _iter_nodes_from_value(column.value):
            if predicate(node):
                return node
            candidates.append(node)
    if candidates:
        return candidates[0]
    return None


def _select_node(
    columns: Iterable[GraphStoreCypherQueryV2Column],
    predicate,
) -> Optional[GraphStoreCypherQueryV2AriNode]:
    for node in _iter_nodes_from_columns(columns):
        if predicate(node):
            return node
    return None


def _is_team_node(node: GraphStoreCypherQueryV2AriNode) -> bool:
    if node.data and node.data.typename in TEAM_TYPENAMES:
        return True
    return node.id.startswith(TEAM_ARI_PREFIX)


def _is_user_node(node: GraphStoreCypherQueryV2AriNode) -> bool:
    if node.data and node.data.typename in USER_TYPENAMES:
        return True
    return node.id.startswith(USER_ARI_PREFIX)


def _is_project_node(node: GraphStoreCypherQueryV2AriNode) -> bool:
    return bool(node.data and node.data.typename in PROJECT_TYPENAMES)


# Teamwork Graph APIs are EAP/experimental and may evolve without notice.
def map_teamwork_project(node: GraphStoreCypherQueryV2Node) -> TeamworkProject:
    if node is None:
        raise ValueError("node is required")

    team_node = _select_node_by_key(
        node.columns, ("team", "teamid", "team_id"), _is_team_node
    )
    if team_node is None:
        team_node = _select_node(node.columns, _is_team_node)

    project_node = _select_node_by_key(
        node.columns, ("project", "projectid", "project_id"), _is_project_node
    )
    if project_node is None:
        project_node = _select_node(node.columns, _is_project_node)

    if team_node is None or project_node is None:
        raise ValueError("teamwork project mapping requires team and project nodes")

    project_name = None
    project_key = None
    if project_node.data:
        project_name = project_node.data.name or project_node.data.display_name
        project_key = project_node.data.key

    return TeamworkProject(
        team_id=_require_non_empty_str(team_node.id, "team.id"),
        project_id=_require_non_empty_str(project_node.id, "project.id"),
        project_key=_optional_str(project_key),
        project_name=_optional_str(project_name),
    )


# Teamwork Graph APIs are EAP/experimental and may evolve without notice.
def map_teamwork_user_relation(
    *,
    node: GraphStoreCypherQueryV2Node,
    relation_type: str,
    subject_user_id: Optional[str] = None,
) -> TeamworkUserRelation:
    if node is None:
        raise ValueError("node is required")
    if not relation_type or not relation_type.strip():
        raise ValueError("relation_type is required")

    relation_type = relation_type.strip()

    subject_node = None
    if subject_user_id:
        subject_user_id = subject_user_id.strip()
        for candidate in _iter_nodes_from_columns(node.columns):
            if candidate.id == subject_user_id:
                subject_node = candidate
                break

    if subject_node is None:
        subject_node = _select_node_by_key(
            node.columns, ("user", "userid", "user_id", "member"), _is_user_node
        )
    if subject_node is None:
        subject_node = _select_node(node.columns, _is_user_node)

    if subject_node is None:
        raise ValueError("teamwork user relation requires a subject user")

    team_node = _select_node_by_key(
        node.columns, ("team", "teamid", "team_id"), _is_team_node
    )
    if team_node is None:
        team_node = _select_node(node.columns, _is_team_node)

    related_user_node = _select_node_by_key(
        node.columns,
        ("manager", "report", "directreport", "direct_report"),
        _is_user_node,
    )
    if related_user_node is None:
        for candidate in _iter_nodes_from_columns(node.columns):
            if _is_user_node(candidate) and candidate.id != subject_node.id:
                related_user_node = candidate
                break

    if relation_type == "TEAM_MEMBER":
        if team_node is None:
            raise ValueError("TEAM_MEMBER relation requires team node")
        return TeamworkUserRelation(
            subject_user_id=_require_non_empty_str(subject_node.id, "user.id"),
            relation_type=relation_type,
            team_id=_require_non_empty_str(team_node.id, "team.id"),
            related_user_id=None,
        )

    if related_user_node is None:
        raise ValueError("manager relation requires a related user node")

    return TeamworkUserRelation(
        subject_user_id=_require_non_empty_str(subject_node.id, "user.id"),
        relation_type=relation_type,
        team_id=None,
        related_user_id=_require_non_empty_str(related_user_node.id, "related_user.id"),
    )
