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
    team_field_name: str
    team_id_arg_name: str
    team_id_arg_type: str
    team_type_name: str
    team_id_required: bool
    team_display_name_required: bool
    team_avatar_required: bool
    team_state_required: bool
    team_search_parent_field_name: Optional[str]
    team_search_field_name: str
    team_search_org_type: str
    team_search_site_type: str
    team_search_filter_type: str
    team_search_filter_query_type: str
    team_search_first_type: str
    team_search_after_type: Optional[str]
    team_search_connection_type: str
    team_search_has_page_info: bool
    team_search_pageinfo_has_end_cursor: bool
    team_search_uses_edges: bool
    team_search_edge_has_cursor: bool
    team_search_node_type: str
    team_search_node_uses_team_field: bool
    team_search_node_team_field_name: Optional[str]


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


def _unwrap_named_type(
    type_ref: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
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


def _is_non_null(type_ref: Dict[str, Any]) -> bool:
    return type_ref.get("kind") == "NON_NULL"


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


def _find_team_by_id_field(
    query_def: Dict[str, Any], types: Dict[str, Dict[str, Any]]
) -> Tuple[str, Dict[str, Any], str]:
    candidates: List[Tuple[str, Dict[str, Any], str]] = []
    for f in query_def.get("fields", []):
        if not isinstance(f, dict):
            continue
        if not _arg(f, "id"):
            continue
        type_name, _, _ = _unwrap_named_type(f.get("type") or {})
        if not type_name:
            continue
        type_def = types.get(type_name)
        if not type_def:
            continue
        if not _field(type_def, "id"):
            continue
        if not _field(type_def, "displayName"):
            continue
        if not _field(type_def, "smallAvatarImageUrl"):
            continue
        if not _field(type_def, "state"):
            continue
        field_name = f.get("name")
        if isinstance(field_name, str) and field_name:
            candidates.append((field_name, f, type_name))

    candidates = sorted(candidates, key=lambda item: item[0])
    for name, f, type_name in candidates:
        if name == "team":
            return name, f, type_name
    if candidates:
        return candidates[0]
    raise RuntimeError("Unable to locate team-by-id field on the query type")


def _all_args_optional(field_def: Dict[str, Any]) -> bool:
    args = field_def.get("args")
    if not isinstance(args, list):
        return True
    for arg in args:
        if not isinstance(arg, dict):
            continue
        type_ref = arg.get("type")
        if isinstance(type_ref, dict) and _is_non_null(type_ref):
            return False
    return True


def _discover_team_search_field(
    schema: Dict[str, Any], query_def: Dict[str, Any], types: Dict[str, Dict[str, Any]]
) -> Tuple[Optional[str], Dict[str, Any]]:
    direct = _field(query_def, "teamSearchV2")
    if direct:
        return None, direct
    parent_field = _field(query_def, "team")
    if not parent_field:
        raise RuntimeError("Missing required field Query.teamSearchV2 or Query.team")
    if not _all_args_optional(parent_field):
        raise RuntimeError("Query.teamSearchV2 not found and Query.team requires args")
    parent_type_name, _, _ = _unwrap_named_type(parent_field.get("type") or {})
    if not parent_type_name:
        raise RuntimeError("Unable to resolve Query.team return type")
    parent_def = types.get(parent_type_name)
    if not parent_def:
        raise RuntimeError(
            f"Missing team search parent type definition: {parent_type_name}"
        )
    nested = _field(parent_def, "teamSearchV2")
    if not nested:
        raise RuntimeError("Missing field teamSearchV2 on team query type")
    return parent_field.get("name") or "team", nested


def _require_opt_in_directive(schema: Dict[str, Any]) -> None:
    directives = schema.get("directives")
    if not isinstance(directives, list):
        raise RuntimeError("Introspection JSON missing __schema.directives[]")
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        if directive.get("name") != "optIn":
            continue
        args = directive.get("args")
        if not isinstance(args, list):
            continue
        for arg in args:
            if isinstance(arg, dict) and arg.get("name") == "to":
                return
    raise RuntimeError("Missing @optIn directive or optIn.to argument")


def _discover_config(schema: Dict[str, Any]) -> _Config:
    types = _types_map(schema)
    _require_opt_in_directive(schema)

    query_type = schema.get("queryType")
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    if not isinstance(query_name, str) or not query_name:
        raise RuntimeError("Introspection JSON missing __schema.queryType.name")
    query_def = types.get(query_name)
    if not query_def:
        raise RuntimeError(f"Missing query type definition: {query_name}")

    team_field_name, team_field, team_type_name = _find_team_by_id_field(
        query_def, types
    )
    team_id_arg = _arg(team_field, "id")
    if not team_id_arg or not isinstance(team_id_arg.get("type"), dict):
        raise RuntimeError(
            f"Missing team id argument on {query_name}.{team_field_name}"
        )
    team_id_arg_type = _type_ref_to_gql(team_id_arg["type"])

    team_def = types.get(team_type_name)
    if not team_def:
        raise RuntimeError(f"Missing team type definition: {team_type_name}")

    team_id_field = _field(team_def, "id")
    display_name_field = _field(team_def, "displayName")
    avatar_field = _field(team_def, "smallAvatarImageUrl")
    state_field = _field(team_def, "state")
    if (
        not team_id_field
        or not display_name_field
        or not avatar_field
        or not state_field
    ):
        raise RuntimeError(
            "Team type missing one of required fields: id, displayName, smallAvatarImageUrl, state"
        )

    team_id_required = _is_non_null(team_id_field.get("type") or {})
    team_display_name_required = _is_non_null(display_name_field.get("type") or {})
    team_avatar_required = _is_non_null(avatar_field.get("type") or {})
    team_state_required = _is_non_null(state_field.get("type") or {})

    team_search_parent_field, team_search_field = _discover_team_search_field(
        schema, query_def, types
    )
    team_search_field_name = team_search_field.get("name") or "teamSearchV2"

    org_arg = _arg(team_search_field, "organizationId")
    site_arg = _arg(team_search_field, "siteId")
    filter_arg = _arg(team_search_field, "filter")
    first_arg = _arg(team_search_field, "first")
    if not org_arg or not site_arg or not filter_arg or not first_arg:
        raise RuntimeError("Missing required args on teamSearchV2")

    if not isinstance(org_arg.get("type"), dict):
        raise RuntimeError("Invalid teamSearchV2.organizationId type")
    if not isinstance(site_arg.get("type"), dict):
        raise RuntimeError("Invalid teamSearchV2.siteId type")
    if not isinstance(filter_arg.get("type"), dict):
        raise RuntimeError("Invalid teamSearchV2.filter type")
    if not isinstance(first_arg.get("type"), dict):
        raise RuntimeError("Invalid teamSearchV2.first type")

    team_search_org_type = _type_ref_to_gql(org_arg["type"])
    team_search_site_type = _type_ref_to_gql(site_arg["type"])
    team_search_filter_type = _type_ref_to_gql(filter_arg["type"])
    team_search_first_type = _type_ref_to_gql(first_arg["type"])

    after_arg = _arg(team_search_field, "after")
    team_search_after_type: Optional[str] = None
    if after_arg and isinstance(after_arg.get("type"), dict):
        team_search_after_type = _type_ref_to_gql(after_arg["type"])

    filter_type_name, _, _ = _unwrap_named_type(filter_arg["type"])
    if not filter_type_name:
        raise RuntimeError("Unable to resolve teamSearchV2.filter type")
    filter_def = types.get(filter_type_name)
    if not filter_def:
        raise RuntimeError(
            f"Missing teamSearchV2 filter type definition: {filter_type_name}"
        )
    filter_query_field = _input_field(filter_def, "query")
    if not filter_query_field:
        raise RuntimeError(f"Missing filter.query field on {filter_type_name}")
    if not isinstance(filter_query_field.get("type"), dict):
        raise RuntimeError(f"Invalid filter.query type on {filter_type_name}")
    team_search_filter_query_type = _type_ref_to_gql(filter_query_field["type"])

    conn_type_name, _, _ = _unwrap_named_type(team_search_field.get("type") or {})
    if not conn_type_name:
        raise RuntimeError("Unable to resolve teamSearchV2 return type")
    conn_def = types.get(conn_type_name)
    if not conn_def:
        raise RuntimeError(f"Missing teamSearchV2 connection type: {conn_type_name}")

    page_info_field = _field(conn_def, "pageInfo")
    nodes_field = _field(conn_def, "nodes")
    edges_field = _field(conn_def, "edges")
    team_search_has_page_info = page_info_field is not None
    team_search_uses_edges = nodes_field is None and edges_field is not None
    if not nodes_field and not edges_field:
        raise RuntimeError(f"Missing nodes/edges on connection type: {conn_type_name}")

    team_search_pageinfo_has_end_cursor = False
    if page_info_field:
        pageinfo_type_name, _, _ = _unwrap_named_type(page_info_field.get("type") or {})
        if not pageinfo_type_name:
            raise RuntimeError("Unable to resolve pageInfo type")
        pageinfo_def = types.get(pageinfo_type_name)
        if not pageinfo_def:
            raise RuntimeError(
                f"Missing pageInfo type definition: {pageinfo_type_name}"
            )
        if not _field(pageinfo_def, "hasNextPage"):
            raise RuntimeError(f"Missing pageInfo.hasNextPage on {pageinfo_type_name}")
        team_search_pageinfo_has_end_cursor = (
            _field(pageinfo_def, "endCursor") is not None
        )

    node_type_name = ""
    edge_has_cursor = False
    node_uses_team_field = False
    node_team_field_name: Optional[str] = None

    if nodes_field:
        node_type_name, _, _ = _unwrap_named_type(nodes_field.get("type") or {})
    else:
        if not edges_field:
            raise RuntimeError(f"Missing edges on connection type: {conn_type_name}")
        edges_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
        if not edges_type_name:
            raise RuntimeError("Unable to resolve edges type")
        edges_def = types.get(edges_type_name)
        if not edges_def:
            raise RuntimeError(f"Missing edges type definition: {edges_type_name}")
        edge_has_cursor = _field(edges_def, "cursor") is not None
        node_field = _field(edges_def, "node")
        if not node_field:
            raise RuntimeError(f"Missing node field on {edges_type_name}")
        node_type_name, _, _ = _unwrap_named_type(node_field.get("type") or {})

    if not node_type_name:
        raise RuntimeError("Unable to resolve teamSearchV2 node type")

    if node_type_name != team_type_name:
        node_def = types.get(node_type_name)
        if not node_def:
            raise RuntimeError(f"Missing node type definition: {node_type_name}")
        team_field = _field(node_def, "team")
        if not team_field:
            raise RuntimeError(f"Missing team field on node type: {node_type_name}")
        team_field_type, _, _ = _unwrap_named_type(team_field.get("type") or {})
        if team_field_type != team_type_name:
            raise RuntimeError("Node.team does not return Team type")
        node_uses_team_field = True
        node_team_field_name = team_field.get("name") or "team"

    return _Config(
        team_field_name=team_field_name,
        team_id_arg_name="id",
        team_id_arg_type=team_id_arg_type,
        team_type_name=team_type_name,
        team_id_required=team_id_required,
        team_display_name_required=team_display_name_required,
        team_avatar_required=team_avatar_required,
        team_state_required=team_state_required,
        team_search_parent_field_name=team_search_parent_field,
        team_search_field_name=team_search_field_name,
        team_search_org_type=team_search_org_type,
        team_search_site_type=team_search_site_type,
        team_search_filter_type=team_search_filter_type,
        team_search_filter_query_type=team_search_filter_query_type,
        team_search_first_type=team_search_first_type,
        team_search_after_type=team_search_after_type,
        team_search_connection_type=conn_type_name,
        team_search_has_page_info=team_search_has_page_info,
        team_search_pageinfo_has_end_cursor=team_search_pageinfo_has_end_cursor,
        team_search_uses_edges=team_search_uses_edges,
        team_search_edge_has_cursor=edge_has_cursor,
        team_search_node_type=node_type_name,
        team_search_node_uses_team_field=node_uses_team_field,
        team_search_node_team_field_name=node_team_field_name,
    )


def _render_python(cfg: _Config) -> str:
    team_field_lines = ["id", "displayName", "smallAvatarImageUrl", "state"]
    if cfg.team_search_node_uses_team_field:
        team_block_lines = [f"{cfg.team_search_node_team_field_name} {{"]
        team_block_lines.extend([f"  {line}" for line in team_field_lines])
        team_block_lines.append("}")
    else:
        team_block_lines = team_field_lines

    if cfg.team_search_uses_edges:
        edge_lines: List[str] = []
        if cfg.team_search_edge_has_cursor:
            edge_lines.append("cursor")
        edge_lines.append("node {")
        edge_lines.extend([f"  {line}" for line in team_block_lines])
        edge_lines.append("}")
        search_lines = ["edges {"]
        search_lines.extend([f"  {line}" for line in edge_lines])
        search_lines.append("}")
    else:
        search_lines = ["nodes {"]
        search_lines.extend([f"  {line}" for line in team_block_lines])
        search_lines.append("}")

    team_search_lines: List[str] = [
        "query TeamSearchV2(",
        f"  $organizationId: {cfg.team_search_org_type},",
        f"  $siteId: {cfg.team_search_site_type},",
        f"  $query: {cfg.team_search_filter_query_type},",
        f"  $first: {cfg.team_search_first_type},",
    ]
    if cfg.team_search_after_type:
        team_search_lines.append(f"  $after: {cfg.team_search_after_type},")
    team_search_lines.append(") {")
    if cfg.team_search_parent_field_name:
        team_search_lines.append(f"  {cfg.team_search_parent_field_name} {{")
        indent = "    "
        close_parent = True
    else:
        indent = "  "
        close_parent = False

    team_search_lines.append(f"{indent}{cfg.team_search_field_name}(")
    team_search_lines.append(f"{indent}  organizationId: $organizationId")
    team_search_lines.append(f"{indent}  siteId: $siteId")
    team_search_lines.append(f"{indent}  filter: {{ query: $query }}")
    team_search_lines.append(f"{indent}  first: $first")
    if cfg.team_search_after_type:
        team_search_lines.append(f"{indent}  after: $after")
    team_search_lines.append(f'{indent}) @optIn(to: "Team-search-v2") {{')
    if cfg.team_search_has_page_info:
        pageinfo_line = "pageInfo { hasNextPage"
        if cfg.team_search_pageinfo_has_end_cursor:
            pageinfo_line += " endCursor"
        pageinfo_line += " }"
        team_search_lines.append(f"{indent}  {pageinfo_line}")
    for line in search_lines:
        team_search_lines.append(f"{indent}  {line}")
    team_search_lines.append(f"{indent}}}")
    if close_parent:
        team_search_lines.append("  }")
    team_search_lines.append("}")
    team_search_body = "\n".join(team_search_lines) + "\n"

    team_by_id_lines = [
        "query TeamById(",
        f"  $teamId: {cfg.team_id_arg_type}",
        ") {",
        f"  {cfg.team_field_name}({cfg.team_id_arg_name}: $teamId) {{",
        "    id",
        "    displayName",
        "    smallAvatarImageUrl",
        "    state",
        "  }",
        "}",
    ]
    team_by_id_body = "\n".join(team_by_id_lines) + "\n"

    id_type = "str" if cfg.team_id_required else "Optional[str]"
    display_type = "str" if cfg.team_display_name_required else "Optional[str]"
    avatar_type = "str" if cfg.team_avatar_required else "Optional[str]"
    state_type = "str" if cfg.team_state_required else "Optional[str]"

    return f"""# Code generated by python/tools/generate_team_models.py. DO NOT EDIT.
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from atlassian.errors import SerializationError

TEAM_SEARCH_V2_OPT_IN = "Team-search-v2"
EXPERIMENTAL_APIS = ("teams-beta", "team-members-beta")
TEAM_ARI_PREFIX = "ari:cloud:identity::team/"
TEAM_ARI_RE = re.compile(r"^" + re.escape(TEAM_ARI_PREFIX) + r"[0-9a-fA-F-]{{36}}$")

TEAM_QUERY_FIELD = {cfg.team_field_name!r}
TEAM_QUERY_ID_ARG = {cfg.team_id_arg_name!r}
TEAM_QUERY_ID_TYPE = {cfg.team_id_arg_type!r}
TEAM_TYPE_NAME = {cfg.team_type_name!r}
TEAM_SEARCH_PARENT_FIELD = {cfg.team_search_parent_field_name!r}
TEAM_SEARCH_FIELD = {cfg.team_search_field_name!r}
TEAM_SEARCH_FILTER_TYPE = {cfg.team_search_filter_type!r}
TEAM_SEARCH_FILTER_QUERY_TYPE = {cfg.team_search_filter_query_type!r}
TEAM_SEARCH_CONNECTION_TYPE = {cfg.team_search_connection_type!r}
TEAM_SEARCH_NODE_TYPE = {cfg.team_search_node_type!r}
TEAM_SEARCH_USES_EDGES = {str(cfg.team_search_uses_edges)}
TEAM_SEARCH_EDGE_HAS_CURSOR = {str(cfg.team_search_edge_has_cursor)}
TEAM_SEARCH_HAS_PAGEINFO = {str(cfg.team_search_has_page_info)}
TEAM_SEARCH_PAGEINFO_HAS_END_CURSOR = {str(cfg.team_search_pageinfo_has_end_cursor)}

TEAM_BY_ID_QUERY = {team_by_id_body!r}
TEAM_SEARCH_V2_QUERY = {team_search_body!r}


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


def _expect_optional_str(obj: Any, path: str) -> Optional[str]:
    if obj is None:
        return None
    if not isinstance(obj, str):
        raise SerializationError(f"Expected string at {{path}}")
    if not obj:
        raise SerializationError(f"Expected non-empty string at {{path}}")
    return obj


def _is_team_ari(value: str) -> bool:
    if not TEAM_ARI_RE.match(value):
        return False
    suffix = value[len(TEAM_ARI_PREFIX) :]
    try:
        uuid.UUID(suffix)
    except ValueError:
        return False
    return True


def _expect_team_id(obj: Any, path: str, required: bool = True) -> Optional[str]:
    if obj is None and not required:
        return None
    value = _expect_str(obj, path)
    if not _is_team_ari(value):
        raise SerializationError(f"Expected team ARI at {{path}}")
    return value


@dataclass(frozen=True)
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "PageInfo":
        raw = _expect_dict(obj, path)
        has_next = raw.get("hasNextPage")
        if not isinstance(has_next, bool):
            raise SerializationError(f"Expected boolean at {{path}}.hasNextPage")
        end_cursor: Optional[str] = None
        if TEAM_SEARCH_PAGEINFO_HAS_END_CURSOR:
            value = raw.get("endCursor")
            if value is not None:
                end_cursor = _expect_str(value, f"{{path}}.endCursor")
        return PageInfo(has_next_page=has_next, end_cursor=end_cursor)


@dataclass(frozen=True)
class TeamNode:
    id: {id_type}
    display_name: {display_type}
    small_avatar_image_url: {avatar_type}
    state: {state_type}

    @staticmethod
    def from_dict(obj: Any, path: str) -> "TeamNode":
        raw = _expect_dict(obj, path)
        team_id = _expect_team_id(raw.get("id"), f"{{path}}.id", required={str(cfg.team_id_required)})
        display_name = (
            _expect_str(raw.get("displayName"), f"{{path}}.displayName")
            if {str(cfg.team_display_name_required)}
            else _expect_optional_str(raw.get("displayName"), f"{{path}}.displayName")
        )
        avatar = (
            _expect_str(raw.get("smallAvatarImageUrl"), f"{{path}}.smallAvatarImageUrl")
            if {str(cfg.team_avatar_required)}
            else _expect_optional_str(raw.get("smallAvatarImageUrl"), f"{{path}}.smallAvatarImageUrl")
        )
        state = (
            _expect_str(raw.get("state"), f"{{path}}.state")
            if {str(cfg.team_state_required)}
            else _expect_optional_str(raw.get("state"), f"{{path}}.state")
        )
        return TeamNode(
            id=team_id,
            display_name=display_name,
            small_avatar_image_url=avatar,
            state=state,
        )


@dataclass(frozen=True)
class TeamSearchNode:
    team: TeamNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> "TeamSearchNode":
        raw = _expect_dict(obj, path)
        team = raw.get("team")
        if team is None:
            raise SerializationError(f"Missing {{path}}.team")
        return TeamSearchNode(team=TeamNode.from_dict(team, f"{{path}}.team"))


@dataclass(frozen=True)
class TeamSearchEdge:
    cursor: Optional[str]
    node: Union[TeamSearchNode, TeamNode]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "TeamSearchEdge":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if TEAM_SEARCH_EDGE_HAS_CURSOR:
            value = raw.get("cursor")
            if value is not None:
                cursor = _expect_str(value, f"{{path}}.cursor")
        node_obj = raw.get("node")
        if node_obj is None:
            raise SerializationError(f"Missing {{path}}.node")
        if TEAM_SEARCH_NODE_TYPE == TEAM_TYPE_NAME:
            node = TeamNode.from_dict(node_obj, f"{{path}}.node")
        else:
            node = TeamSearchNode.from_dict(node_obj, f"{{path}}.node")
        return TeamSearchEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class TeamSearchConnection:
    page_info: Optional[PageInfo]
    nodes: Optional[List[Union[TeamNode, TeamSearchNode]]]
    edges: Optional[List[TeamSearchEdge]]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "TeamSearchConnection":
        raw = _expect_dict(obj, path)
        page_info: Optional[PageInfo] = None
        if TEAM_SEARCH_HAS_PAGEINFO:
            page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        nodes: Optional[List[Union[TeamNode, TeamSearchNode]]] = None
        edges: Optional[List[TeamSearchEdge]] = None
        if TEAM_SEARCH_USES_EDGES:
            edges_list = _expect_list(raw.get("edges"), f"{{path}}.edges")
            edges = [
                TeamSearchEdge.from_dict(item, f"{{path}}.edges[{{idx}}]")
                for idx, item in enumerate(edges_list)
            ]
        else:
            nodes_list = _expect_list(raw.get("nodes"), f"{{path}}.nodes")
            if TEAM_SEARCH_NODE_TYPE == TEAM_TYPE_NAME:
                nodes = [
                    TeamNode.from_dict(item, f"{{path}}.nodes[{{idx}}]")
                    for idx, item in enumerate(nodes_list)
                ]
            else:
                nodes = [
                    TeamSearchNode.from_dict(item, f"{{path}}.nodes[{{idx}}]")
                    for idx, item in enumerate(nodes_list)
                ]
        return TeamSearchConnection(page_info=page_info, nodes=nodes, edges=edges)


def parse_team_by_id(data: Any) -> TeamNode:
    root = _expect_dict(data, "data")
    team = root.get(TEAM_QUERY_FIELD)
    if team is None:
        raise SerializationError(f"Missing data.{{TEAM_QUERY_FIELD}}")
    return TeamNode.from_dict(team, f"data.{{TEAM_QUERY_FIELD}}")


def parse_team_search_v2(data: Any) -> TeamSearchConnection:
    root = _expect_dict(data, "data")
    if TEAM_SEARCH_PARENT_FIELD:
        parent = root.get(TEAM_SEARCH_PARENT_FIELD)
        if parent is None:
            raise SerializationError(f"Missing data.{{TEAM_SEARCH_PARENT_FIELD}}")
        parent_obj = _expect_dict(parent, f"data.{{TEAM_SEARCH_PARENT_FIELD}}")
        search = parent_obj.get(TEAM_SEARCH_FIELD)
        if search is None:
            raise SerializationError(
                f"Missing data.{{TEAM_SEARCH_PARENT_FIELD}}.{{TEAM_SEARCH_FIELD}}"
            )
        return TeamSearchConnection.from_dict(
            search, f"data.{{TEAM_SEARCH_PARENT_FIELD}}.{{TEAM_SEARCH_FIELD}}"
        )
    search = root.get(TEAM_SEARCH_FIELD)
    if search is None:
        raise SerializationError(f"Missing data.{{TEAM_SEARCH_FIELD}}")
    return TeamSearchConnection.from_dict(search, f"data.{{TEAM_SEARCH_FIELD}}")
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
    output_py = repo_root / "python" / "atlassian" / "graph" / "gen" / "teams_api.py"
    output_py.parent.mkdir(parents=True, exist_ok=True)
    output_py.write_text(_render_python(cfg), encoding="utf-8")

    print(f"Wrote {output_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
