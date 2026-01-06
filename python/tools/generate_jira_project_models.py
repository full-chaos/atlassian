from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()

from atlassian.auth import (  # noqa: E402
    BasicApiTokenAuth,
    CookieAuth,
    OAuthBearerAuth,
)
from atlassian.oauth_3lo import OAuthRefreshTokenAuth  # noqa: E402
from atlassian.graph.schema_fetcher import fetch_schema_introspection  # noqa: E402


@dataclass(frozen=True)
class _Config:
    cloud_id_type: str
    projects_first_type: str
    projects_after_type: str
    ops_first_type: str
    ops_after_type: str
    pageinfo_has_end_cursor: bool
    projects_edge_has_cursor: bool
    ops_edge_has_cursor: bool
    project_has_id: bool
    refetch_strategy: str  # "node" or "jira"
    project_type_name: str
    node_id_arg_type: Optional[str]
    jira_project_field_name: Optional[str]
    jira_project_key_arg_name: Optional[str]
    jira_project_key_arg_type: Optional[str]


def _env_experimental_apis() -> List[str]:
    raw = os.getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _maybe_strip_quotes(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return raw


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _maybe_strip_quotes(value.strip())


def _build_auth_from_env():
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


def _load_introspection(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
        data = raw["data"]
    else:
        data = raw
    if not isinstance(data, dict) or "__schema" not in data:
        raise RuntimeError("Introspection JSON missing data.__schema")
    schema = data["__schema"]
    if not isinstance(schema, dict):
        raise RuntimeError("Introspection JSON data.__schema is not an object")
    return schema


def _types_map(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    types = schema.get("types")
    if not isinstance(types, list):
        raise RuntimeError("Introspection JSON missing __schema.types[]")
    out: Dict[str, Dict[str, Any]] = {}
    for t in types:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if isinstance(name, str) and name:
            out[name] = t
    return out


def _unwrap_named_type(type_ref: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    cur = type_ref
    for _ in range(16):
        if not isinstance(cur, dict):
            break
        kind = cur.get("kind")
        name = cur.get("name")
        if isinstance(name, str) and name:
            return name, kind if isinstance(kind, str) else None, cur
        nxt = cur.get("ofType")
        if nxt is None:
            break
        cur = nxt
    return None, None, {}


def _type_ref_to_gql(type_ref: Dict[str, Any]) -> str:
    kind = type_ref.get("kind")
    if kind == "NON_NULL":
        of_type = type_ref.get("ofType")
        if not isinstance(of_type, dict):
            raise RuntimeError("Invalid NON_NULL typeRef")
        return f"{_type_ref_to_gql(of_type)}!"
    if kind == "LIST":
        of_type = type_ref.get("ofType")
        if not isinstance(of_type, dict):
            raise RuntimeError("Invalid LIST typeRef")
        return f"[{_type_ref_to_gql(of_type)}]"
    name = type_ref.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("Invalid named typeRef")
    return name


def _field(type_def: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    fields = type_def.get("fields")
    if not isinstance(fields, list):
        return None
    for f in fields:
        if isinstance(f, dict) and f.get("name") == name:
            return f
    return None


def _input_field(type_def: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    fields = type_def.get("inputFields")
    if not isinstance(fields, list):
        return None
    for f in fields:
        if isinstance(f, dict) and f.get("name") == name:
            return f
    return None


def _arg(field_def: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    args = field_def.get("args")
    if not isinstance(args, list):
        return None
    for a in args:
        if isinstance(a, dict) and a.get("name") == name:
            return a
    return None


def _discover_config(schema: Dict[str, Any]) -> _Config:
    types = _types_map(schema)
    missing: List[str] = []

    query_type = schema.get("queryType")
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    if not isinstance(query_name, str) or not query_name:
        raise RuntimeError("Introspection JSON missing __schema.queryType.name")
    query_def = types.get(query_name)
    if not query_def:
        raise RuntimeError(f"Missing query type definition: {query_name}")

    jira_field = _field(query_def, "jira")
    if not jira_field:
        missing.append(f"type {query_name}.fields.jira")
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))
    jira_type_name, _, _ = _unwrap_named_type(jira_field.get("type") or {})
    if not jira_type_name or jira_type_name not in types:
        raise RuntimeError("Failed to resolve type for field Query.jira")
    jira_def = types[jira_type_name]

    all_projects_field = _field(jira_def, "allJiraProjects")
    if not all_projects_field:
        missing.append(f"type {jira_type_name}.fields.allJiraProjects")
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    for arg_name in ("cloudId", "filter", "first", "after"):
        if not _arg(all_projects_field, arg_name):
            missing.append(f"field jira.allJiraProjects.args.{arg_name}")

    cloud_id_type = ""
    projects_first_type = ""
    projects_after_type = ""

    cloud_arg = _arg(all_projects_field, "cloudId")
    if cloud_arg and isinstance(cloud_arg.get("type"), dict):
        cloud_id_type = _type_ref_to_gql(cloud_arg["type"])

    first_arg = _arg(all_projects_field, "first")
    if first_arg and isinstance(first_arg.get("type"), dict):
        projects_first_type = _type_ref_to_gql(first_arg["type"])

    after_arg = _arg(all_projects_field, "after")
    if after_arg and isinstance(after_arg.get("type"), dict):
        projects_after_type = _type_ref_to_gql(after_arg["type"])

    filter_arg = _arg(all_projects_field, "filter")
    if filter_arg and isinstance(filter_arg.get("type"), dict):
        filter_type_name, _, _ = _unwrap_named_type(filter_arg["type"])
        filter_def = types.get(filter_type_name or "")
        if not filter_def:
            missing.append("field jira.allJiraProjects.args.filter.type")
        else:
            types_field = _input_field(filter_def, "types")
            if not types_field:
                missing.append(f"type {filter_type_name}.inputFields.types")
            else:
                tref = types_field.get("type")
                if not isinstance(tref, dict):
                    missing.append(f"type {filter_type_name}.inputFields.types.type")

    conn_type_name, _, _ = _unwrap_named_type(all_projects_field.get("type") or {})
    conn_def = types.get(conn_type_name or "")
    if not conn_def:
        missing.append("field jira.allJiraProjects.type")
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    page_info_field = _field(conn_def, "pageInfo")
    edges_field = _field(conn_def, "edges")
    if not page_info_field:
        missing.append(f"type {conn_type_name}.fields.pageInfo")
    if not edges_field:
        missing.append(f"type {conn_type_name}.fields.edges")
    if missing:
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    pageinfo_type_name, _, _ = _unwrap_named_type(page_info_field.get("type") or {})
    pageinfo_def = types.get(pageinfo_type_name or "")
    if not pageinfo_def:
        raise RuntimeError(f"Missing PageInfo type definition: {pageinfo_type_name}")

    has_next = _field(pageinfo_def, "hasNextPage")
    if not has_next:
        raise RuntimeError(f"Missing PageInfo.hasNextPage on {pageinfo_type_name}")
    pageinfo_has_end_cursor = _field(pageinfo_def, "endCursor") is not None

    edges_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
    edges_def = types.get(edges_type_name or "")
    if not edges_def:
        raise RuntimeError(f"Missing edge type definition: {edges_type_name}")
    projects_edge_has_cursor = _field(edges_def, "cursor") is not None

    node_field = _field(edges_def, "node")
    if not node_field:
        raise RuntimeError(f"Missing edge.node on {edges_type_name}")
    project_type_name, _, _ = _unwrap_named_type(node_field.get("type") or {})
    project_def = types.get(project_type_name or "")
    if not project_def:
        raise RuntimeError(f"Missing project type definition: {project_type_name}")

    project_has_id = _field(project_def, "id") is not None
    if not _field(project_def, "key"):
        missing.append(f"type {project_type_name}.fields.key")
    if not _field(project_def, "name"):
        missing.append(f"type {project_type_name}.fields.name")
    ops_field = _field(project_def, "opsgenieTeamsAvailableToLinkWith")
    if not ops_field:
        missing.append(f"type {project_type_name}.fields.opsgenieTeamsAvailableToLinkWith")
    else:
        for arg_name in ("first", "after"):
            if not _arg(ops_field, arg_name):
                missing.append(f"field {project_type_name}.opsgenieTeamsAvailableToLinkWith.args.{arg_name}")

    if missing:
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    ops_first_type = ""
    ops_after_type = ""
    ops_first_arg = _arg(ops_field, "first")
    if ops_first_arg and isinstance(ops_first_arg.get("type"), dict):
        ops_first_type = _type_ref_to_gql(ops_first_arg["type"])
    ops_after_arg = _arg(ops_field, "after")
    if ops_after_arg and isinstance(ops_after_arg.get("type"), dict):
        ops_after_type = _type_ref_to_gql(ops_after_arg["type"])

    ops_conn_type_name, _, _ = _unwrap_named_type(ops_field.get("type") or {})
    ops_conn_def = types.get(ops_conn_type_name or "")
    if not ops_conn_def:
        raise RuntimeError(f"Missing opsgenie connection type: {ops_conn_type_name}")

    ops_page_info_field = _field(ops_conn_def, "pageInfo")
    ops_edges_field = _field(ops_conn_def, "edges")
    if not ops_page_info_field:
        missing.append(f"type {ops_conn_type_name}.fields.pageInfo")
    if not ops_edges_field:
        missing.append(f"type {ops_conn_type_name}.fields.edges")
    if missing:
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    ops_edges_type_name, _, _ = _unwrap_named_type(ops_edges_field.get("type") or {})
    ops_edges_def = types.get(ops_edges_type_name or "")
    if not ops_edges_def:
        raise RuntimeError(f"Missing opsgenie edge type: {ops_edges_type_name}")
    ops_edge_has_cursor = _field(ops_edges_def, "cursor") is not None

    ops_node_field = _field(ops_edges_def, "node")
    if not ops_node_field:
        raise RuntimeError(f"Missing opsgenie edge.node on {ops_edges_type_name}")
    ops_team_type_name, _, _ = _unwrap_named_type(ops_node_field.get("type") or {})
    ops_team_def = types.get(ops_team_type_name or "")
    if not ops_team_def:
        raise RuntimeError(f"Missing opsgenie team type: {ops_team_type_name}")
    if not _field(ops_team_def, "id"):
        missing.append(f"type {ops_team_type_name}.fields.id")
    if not _field(ops_team_def, "name"):
        missing.append(f"type {ops_team_type_name}.fields.name")
    if missing:
        raise RuntimeError("Missing required fields:\n- " + "\n- ".join(missing))

    refetch_strategy = "jira"
    node_id_arg_type: Optional[str] = None
    jira_project_field_name: Optional[str] = None
    jira_project_key_arg_name: Optional[str] = None
    jira_project_key_arg_type: Optional[str] = None

    node_field_def = _field(query_def, "node")
    if node_field_def:
        id_arg = _arg(node_field_def, "id")
        if id_arg and isinstance(id_arg.get("type"), dict) and project_has_id:
            node_id_arg_type = _type_ref_to_gql(id_arg["type"])
            refetch_strategy = "node"

    if refetch_strategy != "node":
        candidates: List[Tuple[str, Dict[str, Any]]] = []
        for f in jira_def.get("fields", []):
            if not isinstance(f, dict):
                continue
            f_type_name, _, _ = _unwrap_named_type(f.get("type") or {})
            if f_type_name == project_type_name:
                candidates.append((f.get("name") or "", f))

        candidates = sorted(candidates, key=lambda item: item[0])
        for field_name, f in candidates:
            if not field_name:
                continue
            if not _arg(f, "cloudId"):
                continue
            for key_arg_name in ("key", "projectKey"):
                key_arg = _arg(f, key_arg_name)
                if key_arg and isinstance(key_arg.get("type"), dict):
                    jira_project_field_name = field_name
                    jira_project_key_arg_name = key_arg_name
                    jira_project_key_arg_type = _type_ref_to_gql(key_arg["type"])
                    break
            if jira_project_field_name:
                break

        if not jira_project_field_name:
            raise RuntimeError(
                "Unable to determine a per-project refetch strategy for nested opsgenie pagination. "
                "Expected Query.node(id: ...) support or a jira.<project>(cloudId, key) field returning the Jira project type."
            )

    return _Config(
        cloud_id_type=cloud_id_type,
        projects_first_type=projects_first_type,
        projects_after_type=projects_after_type,
        ops_first_type=ops_first_type,
        ops_after_type=ops_after_type,
        pageinfo_has_end_cursor=pageinfo_has_end_cursor,
        projects_edge_has_cursor=projects_edge_has_cursor,
        ops_edge_has_cursor=ops_edge_has_cursor,
        project_has_id=project_has_id,
        refetch_strategy=refetch_strategy,
        project_type_name=project_type_name,
        node_id_arg_type=node_id_arg_type,
        jira_project_field_name=jira_project_field_name,
        jira_project_key_arg_name=jira_project_key_arg_name,
        jira_project_key_arg_type=jira_project_key_arg_type,
    )


def _render_python(cfg: _Config) -> str:
    pageinfo_select = "hasNextPage"
    if cfg.pageinfo_has_end_cursor:
        pageinfo_select += " endCursor"

    project_edge_select = "node {"
    if cfg.projects_edge_has_cursor:
        project_edge_select = "cursor\n      node {"

    ops_edge_select = "node {"
    if cfg.ops_edge_has_cursor:
        ops_edge_select = "cursor\n            node {"

    project_id_select = "id\n          " if cfg.project_has_id else ""

    projects_page_query_template = f"""\
query JiraProjectsPage(
  $cloudId: {cfg.cloud_id_type},
  $first: {cfg.projects_first_type},
  $after: {cfg.projects_after_type},
  $opsFirst: {cfg.ops_first_type}
) {{
  jira {{
    projects: allJiraProjects(
      cloudId: $cloudId,
      filter: {{ types: [__PROJECT_TYPES__] }},
      first: $first,
      after: $after
    ) {{
      pageInfo {{ {pageinfo_select} }}
      edges {{
        {project_edge_select}
          {project_id_select}key
          name
          opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $opsFirst) {{
            pageInfo {{ {pageinfo_select} }}
            edges {{
              {ops_edge_select}
                id
                name
              }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    if cfg.refetch_strategy == "node":
        if not cfg.node_id_arg_type:
            raise RuntimeError("invalid config: node strategy missing node_id_arg_type")
        ops_query = f"""\
query JiraProjectOpsgenieTeamsPage(
  $projectId: {cfg.node_id_arg_type},
  $first: {cfg.ops_first_type},
  $after: {cfg.ops_after_type}
) {{
  project: node(id: $projectId) {{
    ... on {cfg.project_type_name} {{
      opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $first, after: $after) {{
        pageInfo {{ {pageinfo_select} }}
        edges {{
          {ops_edge_select}
            id
            name
          }}
        }}
      }}
    }}
  }}
}}
"""
    else:
        if not cfg.jira_project_field_name or not cfg.jira_project_key_arg_name or not cfg.jira_project_key_arg_type:
            raise RuntimeError("invalid config: jira strategy missing project lookup details")
        ops_query = f"""\
query JiraProjectOpsgenieTeamsPage(
  $cloudId: {cfg.cloud_id_type},
  $projectKey: {cfg.jira_project_key_arg_type},
  $first: {cfg.ops_first_type},
  $after: {cfg.ops_after_type}
) {{
  jira {{
    project: {cfg.jira_project_field_name}(cloudId: $cloudId, {cfg.jira_project_key_arg_name}: $projectKey) {{
      opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $first, after: $after) {{
        pageInfo {{ {pageinfo_select} }}
        edges {{
          {ops_edge_select}
            id
            name
          }}
        }}
      }}
    }}
  }}
}}
"""

    return f"""\
# Code generated by python/tools/generate_jira_project_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from atlassian.errors import SerializationError

PAGEINFO_HAS_END_CURSOR = {str(cfg.pageinfo_has_end_cursor)}
PROJECTS_EDGE_HAS_CURSOR = {str(cfg.projects_edge_has_cursor)}
OPSGENIE_EDGE_HAS_CURSOR = {str(cfg.ops_edge_has_cursor)}
PROJECT_HAS_ID = {str(cfg.project_has_id)}
REFETCH_STRATEGY = {cfg.refetch_strategy!r}

JIRA_PROJECTS_PAGE_QUERY_TEMPLATE = {projects_page_query_template!r}
JIRA_PROJECT_OPSGENIE_TEAMS_PAGE_QUERY = {ops_query!r}


def build_jira_projects_page_query(project_types: Sequence[str]) -> str:
    if not project_types:
        raise ValueError("project_types must be non-empty")
    cleaned: List[str] = []
    for raw in project_types:
        if not isinstance(raw, str):
            raise ValueError("project_types must be strings")
        value = raw.strip().upper()
        if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
            raise ValueError(f"invalid Jira project type enum token: {{raw!r}}")
        cleaned.append(value)
    joined = ", ".join(cleaned)
    return JIRA_PROJECTS_PAGE_QUERY_TEMPLATE.replace("__PROJECT_TYPES__", joined)


def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise SerializationError(f"Expected object at {{path}}")
    return obj


def _expect_list(obj: Any, path: str) -> List[Any]:
    if not isinstance(obj, list):
        raise SerializationError(f"Expected list at {{path}}")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise SerializationError(f"Expected string at {{path}}")
    return obj


def _expect_bool(obj: Any, path: str) -> bool:
    if not isinstance(obj, bool):
        raise SerializationError(f"Expected boolean at {{path}}")
    return obj


@dataclass(frozen=True)
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "PageInfo":
        raw = _expect_dict(obj, path)
        has_next = _expect_bool(raw.get("hasNextPage"), f"{{path}}.hasNextPage")
        end_cursor: Optional[str] = None
        if PAGEINFO_HAS_END_CURSOR:
            value = raw.get("endCursor")
            if value is not None:
                end_cursor = _expect_str(value, f"{{path}}.endCursor")
        return PageInfo(has_next_page=has_next, end_cursor=end_cursor)


@dataclass(frozen=True)
class OpsgenieTeamNode:
    id: str
    name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> "OpsgenieTeamNode":
        raw = _expect_dict(obj, path)
        return OpsgenieTeamNode(
            id=_expect_str(raw.get("id"), f"{{path}}.id"),
            name=_expect_str(raw.get("name"), f"{{path}}.name"),
        )


@dataclass(frozen=True)
class OpsgenieTeamEdge:
    cursor: Optional[str]
    node: OpsgenieTeamNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> "OpsgenieTeamEdge":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if OPSGENIE_EDGE_HAS_CURSOR:
            value = raw.get("cursor")
            if value is not None:
                cursor = _expect_str(value, f"{{path}}.cursor")
        node = OpsgenieTeamNode.from_dict(raw.get("node"), f"{{path}}.node")
        return OpsgenieTeamEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class OpsgenieTeamsConnection:
    page_info: PageInfo
    edges: List[OpsgenieTeamEdge]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "OpsgenieTeamsConnection":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        edges_list = _expect_list(raw.get("edges"), f"{{path}}.edges")
        edges = [
            OpsgenieTeamEdge.from_dict(item, f"{{path}}.edges[{{idx}}]")
            for idx, item in enumerate(edges_list)
        ]
        return OpsgenieTeamsConnection(page_info=page_info, edges=edges)


@dataclass(frozen=True)
class JiraProjectNode:
    id: Optional[str]
    key: str
    name: str
    opsgenie_teams: OpsgenieTeamsConnection

    @staticmethod
    def from_dict(obj: Any, path: str) -> "JiraProjectNode":
        raw = _expect_dict(obj, path)
        project_id: Optional[str] = None
        if PROJECT_HAS_ID:
            value = raw.get("id")
            if value is not None:
                project_id = _expect_str(value, f"{{path}}.id")
        return JiraProjectNode(
            id=project_id,
            key=_expect_str(raw.get("key"), f"{{path}}.key"),
            name=_expect_str(raw.get("name"), f"{{path}}.name"),
            opsgenie_teams=OpsgenieTeamsConnection.from_dict(
                raw.get("opsgenieTeams"), f"{{path}}.opsgenieTeams"
            ),
        )


@dataclass(frozen=True)
class JiraProjectEdge:
    cursor: Optional[str]
    node: JiraProjectNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> "JiraProjectEdge":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if PROJECTS_EDGE_HAS_CURSOR:
            value = raw.get("cursor")
            if value is not None:
                cursor = _expect_str(value, f"{{path}}.cursor")
        node = JiraProjectNode.from_dict(raw.get("node"), f"{{path}}.node")
        return JiraProjectEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class JiraProjectsConnection:
    page_info: PageInfo
    edges: List[JiraProjectEdge]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "JiraProjectsConnection":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        edges_list = _expect_list(raw.get("edges"), f"{{path}}.edges")
        edges = [
            JiraProjectEdge.from_dict(item, f"{{path}}.edges[{{idx}}]")
            for idx, item in enumerate(edges_list)
        ]
        return JiraProjectsConnection(page_info=page_info, edges=edges)


@dataclass(frozen=True)
class JiraProjectsPageData:
    projects: JiraProjectsConnection

    @staticmethod
    def from_dict(obj: Any, path: str = "data.jira") -> "JiraProjectsPageData":
        raw = _expect_dict(obj, path)
        return JiraProjectsPageData(
            projects=JiraProjectsConnection.from_dict(raw.get("projects"), f"{{path}}.projects"),
        )


def parse_jira_projects_page(data: Any) -> JiraProjectsPageData:
    root = _expect_dict(data, "data")
    jira = root.get("jira")
    if jira is None:
        raise SerializationError("Missing data.jira")
    return JiraProjectsPageData.from_dict(jira, "data.jira")


def parse_project_opsgenie_teams(data: Any) -> OpsgenieTeamsConnection:
    root = _expect_dict(data, "data")
    if REFETCH_STRATEGY == "node":
        project = root.get("project")
        if project is None:
            raise SerializationError("Missing data.project")
        project_obj = _expect_dict(project, "data.project")
        inner = project_obj.get("opsgenieTeams")
        if inner is None:
            raise SerializationError("Missing data.project.opsgenieTeams")
        return OpsgenieTeamsConnection.from_dict(inner, "data.project.opsgenieTeams")

    jira = root.get("jira")
    if jira is None:
        raise SerializationError("Missing data.jira")
    jira_obj = _expect_dict(jira, "data.jira")
    project = jira_obj.get("project")
    if project is None:
        raise SerializationError("Missing data.jira.project")
    project_obj = _expect_dict(project, "data.jira.project")
    inner = project_obj.get("opsgenieTeams")
    if inner is None:
        raise SerializationError("Missing data.jira.project.opsgenieTeams")
    return OpsgenieTeamsConnection.from_dict(inner, "data.jira.project.opsgenieTeams")
"""


def main(argv: Sequence[str]) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    token_file = os.getenv("ATLASSIAN_OAUTH_TOKEN_FILE")
    if not token_file:
        token_file = str(repo_root / "oauth_tokens.txt")
    _load_env_file(Path(token_file))

    schema_path = repo_root / "graphql" / "schema.introspection.json"

    if not schema_path.exists():
        base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
        if not base_url and (
            os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
            or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
        ):
            base_url = "https://api.atlassian.com"
        try:
            auth = _build_auth_from_env()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not base_url or auth is None:
            print(
                f"Missing {schema_path}. Set ATLASSIAN_GQL_BASE_URL (required for non-OAuth auth modes) and credentials, "
                "or run `make graphql-schema` first.",
                file=sys.stderr,
            )
            return 2
        fetch_schema_introspection(
            base_url,
            auth,
            output_dir=schema_path.parent,
            experimental_apis=_env_experimental_apis(),
        )

    schema = _load_introspection(schema_path)
    cfg = _discover_config(schema)
    output_py = repo_root / "python" / "atlassian" / "graph" / "gen" / "jira_projects_api.py"
    output_py.parent.mkdir(parents=True, exist_ok=True)
    output_py.write_text(_render_python(cfg), encoding="utf-8")

    print(f"Wrote {output_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
