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
    query_input_type: str
    search_result_kind: str
    connection_type_name: str
    error_type_name: Optional[str]
    component_result_kind: str
    component_type_name: str
    owner_team_type_name: Optional[str]
    pageinfo_has_end_cursor: bool
    edge_has_cursor: bool
    connection_has_nodes: bool
    query_error_has_extensions: bool
    query_error_extensions_has_status_code: bool
    component_type_id_field: str
    component_description_field: str
    owner_team_field: str
    owner_team_id_field: str
    owner_team_name_field: str


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


def _field(type_def: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    fields = type_def.get("fields")
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


def _require_type(types: Dict[str, Dict[str, Any]], name: str) -> Dict[str, Any]:
    type_def = types.get(name)
    if not type_def:
        raise RuntimeError(f"Missing type definition: {name}")
    return type_def


def _require_field(type_def: Dict[str, Any], name: str, path: str) -> Dict[str, Any]:
    found = _field(type_def, name)
    if not found:
        raise RuntimeError(f"Missing required field {path}.{name}")
    return found


def _possible_type_defs(
    types: Dict[str, Dict[str, Any]], type_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
    possibles = type_def.get("possibleTypes")
    if not isinstance(possibles, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in possibles:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        candidate = types.get(name)
        if candidate:
            out.append(candidate)
    return out


def _has_fields(type_def: Dict[str, Any], names: Sequence[str]) -> bool:
    for name in names:
        if _field(type_def, name) is None:
            return False
    return True


def _discover_connection_type(
    type_defs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for candidate in type_defs:
        if _has_fields(candidate, ["pageInfo", "edges"]):
            return candidate
    return None


def _discover_error_type(type_defs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for candidate in type_defs:
        if _field(candidate, "message") is not None:
            return candidate
    return None


def _discover_component_type(
    type_defs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for candidate in type_defs:
        if _has_fields(candidate, ["id", "name", "typeId"]):
            return candidate
    return None


def _discover_config(schema: Dict[str, Any]) -> _Config:
    types = _types_map(schema)

    query_type = schema.get("queryType")
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    if not isinstance(query_name, str) or not query_name:
        raise RuntimeError("Introspection JSON missing __schema.queryType.name")
    query_def = _require_type(types, query_name)

    compass_field = _field(query_def, "compass")
    if not compass_field:
        raise RuntimeError(f"Missing required field {query_name}.compass")
    compass_type_name, _, _ = _unwrap_named_type(compass_field.get("type") or {})
    if not compass_type_name:
        raise RuntimeError("Unable to resolve type for Query.compass")
    compass_def = _require_type(types, compass_type_name)

    search_field = _field(compass_def, "searchComponents")
    if not search_field:
        raise RuntimeError(
            f"Missing required field {compass_type_name}.searchComponents"
        )

    for arg_name in ("cloudId", "query"):
        if not _arg(search_field, arg_name):
            raise RuntimeError(f"Missing required arg searchComponents.{arg_name}")

    cloud_arg = _arg(search_field, "cloudId")
    if not cloud_arg or not isinstance(cloud_arg.get("type"), dict):
        raise RuntimeError("searchComponents.cloudId missing type info")
    cloud_id_type = _type_ref_to_gql(cloud_arg["type"])

    query_arg = _arg(search_field, "query")
    if not query_arg or not isinstance(query_arg.get("type"), dict):
        raise RuntimeError("searchComponents.query missing type info")
    query_input_type = _type_ref_to_gql(query_arg["type"])

    search_return_name, search_return_kind, _ = _unwrap_named_type(
        search_field.get("type") or {}
    )
    if not search_return_name or not search_return_kind:
        raise RuntimeError("Unable to resolve searchComponents return type")
    search_return_def = _require_type(types, search_return_name)

    connection_def: Optional[Dict[str, Any]] = None
    error_def: Optional[Dict[str, Any]] = None
    if search_return_kind in {"UNION", "INTERFACE"}:
        possible_defs = _possible_type_defs(types, search_return_def)
        connection_def = _discover_connection_type(possible_defs)
        error_def = _discover_error_type(possible_defs)
    else:
        connection_def = search_return_def

    if not connection_def:
        raise RuntimeError("Unable to determine Compass search connection type")
    connection_type_name = connection_def.get("name")
    if not isinstance(connection_type_name, str) or not connection_type_name:
        raise RuntimeError("Invalid connection type name")

    page_info_field = _require_field(
        connection_def, "pageInfo", f"type {connection_type_name}.fields"
    )
    edges_field = _require_field(
        connection_def, "edges", f"type {connection_type_name}.fields"
    )
    nodes_field = _field(connection_def, "nodes")
    connection_has_nodes = nodes_field is not None

    pageinfo_type_name, _, _ = _unwrap_named_type(page_info_field.get("type") or {})
    if not pageinfo_type_name:
        raise RuntimeError("Unable to resolve PageInfo type for Compass search")
    pageinfo_def = _require_type(types, pageinfo_type_name)
    _require_field(pageinfo_def, "hasNextPage", f"type {pageinfo_type_name}.fields")
    pageinfo_has_end_cursor = _field(pageinfo_def, "endCursor") is not None

    edge_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
    if not edge_type_name:
        raise RuntimeError("Unable to resolve edge type for Compass search")
    edge_def = _require_type(types, edge_type_name)
    edge_has_cursor = _field(edge_def, "cursor") is not None

    node_field = _require_field(edge_def, "node", f"type {edge_type_name}.fields")
    node_type_name, _, _ = _unwrap_named_type(node_field.get("type") or {})
    if not node_type_name:
        raise RuntimeError("Unable to resolve Compass search node type")
    node_def = _require_type(types, node_type_name)

    component_field = _require_field(
        node_def, "component", f"type {node_type_name}.fields"
    )
    component_type_name, component_type_kind, _ = _unwrap_named_type(
        component_field.get("type") or {}
    )
    if not component_type_name or not component_type_kind:
        raise RuntimeError("Unable to resolve component type for Compass search")
    component_def = _require_type(types, component_type_name)

    component_result_kind = component_type_kind
    component_error_def: Optional[Dict[str, Any]] = None
    if component_type_kind in {"UNION", "INTERFACE"}:
        possible_component_defs = _possible_type_defs(types, component_def)
        component_object_def = _discover_component_type(possible_component_defs)
        if not component_object_def:
            raise RuntimeError("Unable to determine CompassComponent type in union")
        component_def = component_object_def
        component_type_name = component_def.get("name")
        if not isinstance(component_type_name, str) or not component_type_name:
            raise RuntimeError("Invalid CompassComponent type name")
        component_error_def = _discover_error_type(possible_component_defs)
    _require_field(component_def, "id", f"type {component_type_name}.fields")
    _require_field(component_def, "name", f"type {component_type_name}.fields")
    type_id_field = _require_field(
        component_def, "typeId", f"type {component_type_name}.fields"
    )
    description_field = _require_field(
        component_def, "description", f"type {component_type_name}.fields"
    )
    owner_team_field = _require_field(
        component_def, "ownerTeam", f"type {component_type_name}.fields"
    )

    owner_team_type_name, _, _ = _unwrap_named_type(owner_team_field.get("type") or {})
    if not owner_team_type_name:
        raise RuntimeError("Unable to resolve ownerTeam type")
    owner_team_def = _require_type(types, owner_team_type_name)
    owner_team_id = _require_field(
        owner_team_def, "id", f"type {owner_team_type_name}.fields"
    )
    owner_team_name = _require_field(
        owner_team_def, "displayName", f"type {owner_team_type_name}.fields"
    )

    error_type_name: Optional[str] = None
    query_error_has_extensions = False
    query_error_extensions_has_status_code = False
    effective_error_def = error_def or component_error_def
    if effective_error_def:
        error_type_name = (
            effective_error_def.get("name")
            if isinstance(effective_error_def.get("name"), str)
            else None
        )
        if error_type_name:
            extensions_field = _field(effective_error_def, "extensions")
            if extensions_field:
                query_error_has_extensions = True
                ext_type_name, _, _ = _unwrap_named_type(
                    extensions_field.get("type") or {}
                )
                if ext_type_name:
                    ext_def = types.get(ext_type_name)
                    if ext_def and _field(ext_def, "statusCode") is not None:
                        query_error_extensions_has_status_code = True

    return _Config(
        cloud_id_type=cloud_id_type,
        query_input_type=query_input_type,
        search_result_kind=search_return_kind,
        connection_type_name=connection_type_name,
        error_type_name=error_type_name,
        component_result_kind=component_result_kind,
        component_type_name=component_type_name,
        owner_team_type_name=owner_team_type_name,
        pageinfo_has_end_cursor=pageinfo_has_end_cursor,
        edge_has_cursor=edge_has_cursor,
        connection_has_nodes=connection_has_nodes,
        query_error_has_extensions=query_error_has_extensions,
        query_error_extensions_has_status_code=query_error_extensions_has_status_code,
        component_type_id_field=type_id_field.get("name") or "typeId",
        component_description_field=description_field.get("name") or "description",
        owner_team_field=owner_team_field.get("name") or "ownerTeam",
        owner_team_id_field=owner_team_id.get("name") or "id",
        owner_team_name_field=owner_team_name.get("name") or "displayName",
    )


def _render_python(cfg: _Config) -> str:
    pageinfo_select = "hasNextPage"
    if cfg.pageinfo_has_end_cursor:
        pageinfo_select += " endCursor"

    edges_select = "node {"
    if cfg.edge_has_cursor:
        edges_select = "cursor\n        node {"

    owner_team_select = f"{cfg.owner_team_field} {{ {cfg.owner_team_id_field} {cfg.owner_team_name_field} }}"

    component_select = "\n        ".join(
        [
            "__typename",
            f"... on {cfg.component_type_name} {{",
            "  id",
            "  name",
            f"  {cfg.component_type_id_field}",
            f"  {cfg.component_description_field}",
            f"  {owner_team_select}",
            "}",
        ]
    )
    if cfg.error_type_name:
        component_select = "\n        ".join(
            [
                component_select,
                f"... on {cfg.error_type_name} {{",
                "  message",
                "  extensions { statusCode }"
                if cfg.query_error_extensions_has_status_code
                else "",
                "}",
            ]
        )

    component_select = "\n        ".join(
        line for line in component_select.splitlines() if line
    )

    nodes_select = ""
    if cfg.connection_has_nodes:
        nodes_select = (
            "\n      nodes {\n        component {\n        "
            + component_select
            + "\n        }\n      }"
        )

    search_query = f"""query CompassSearchComponents(
  $cloudId: {cfg.cloud_id_type},
  $query: {cfg.query_input_type}
) {{
  compass {{
    searchComponents(cloudId: $cloudId, query: $query) {{
      __typename
      ... on {cfg.connection_type_name} {{
        pageInfo {{ {pageinfo_select} }}
        edges {{
          {edges_select}
            component {{
        {component_select}
            }}
          }}
        }}{nodes_select}
      }}
"""

    if cfg.error_type_name:
        search_query += f"""      ... on {cfg.error_type_name} {{
        message
"""
        if cfg.query_error_extensions_has_status_code:
            search_query += "        extensions { statusCode }\n"
        search_query += "      }\n"

    search_query += """    }
  }
}
"""

    return f"""# Code generated by python/tools/generate_compass_component_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from atlassian.errors import SerializationError

CONNECTION_TYPE_NAME = {cfg.connection_type_name!r}
COMPONENT_TYPE_NAME = {cfg.component_type_name!r}
ERROR_TYPE_NAME = {cfg.error_type_name!r}
PAGEINFO_HAS_END_CURSOR = {str(cfg.pageinfo_has_end_cursor)}
EDGE_HAS_CURSOR = {str(cfg.edge_has_cursor)}
CONNECTION_HAS_NODES = {str(cfg.connection_has_nodes)}
QUERY_ERROR_HAS_EXTENSIONS = {str(cfg.query_error_has_extensions)}
QUERY_ERROR_EXTENSIONS_HAS_STATUS_CODE = {str(cfg.query_error_extensions_has_status_code)}
SEARCH_RESULT_KIND = {cfg.search_result_kind!r}
COMPONENT_RESULT_KIND = {cfg.component_result_kind!r}

COMPONENT_TYPE_ID_FIELD = {cfg.component_type_id_field!r}
COMPONENT_DESCRIPTION_FIELD = {cfg.component_description_field!r}
OWNER_TEAM_FIELD = {cfg.owner_team_field!r}
OWNER_TEAM_ID_FIELD = {cfg.owner_team_id_field!r}
OWNER_TEAM_NAME_FIELD = {cfg.owner_team_name_field!r}

COMPASS_SEARCH_COMPONENTS_QUERY = {search_query!r}


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


def _expect_bool(obj: Any, path: str) -> bool:
    if not isinstance(obj, bool):
        raise SerializationError(f"Expected boolean at {{path}}")
    return obj


def _expect_int(obj: Any, path: str) -> int:
    if not isinstance(obj, int):
        raise SerializationError(f"Expected integer at {{path}}")
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
class QueryError:
    message: str
    status_code: Optional[int] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "QueryError":
        raw = _expect_dict(obj, path)
        message = _expect_str(raw.get("message"), f"{{path}}.message")
        status_code: Optional[int] = None
        if QUERY_ERROR_HAS_EXTENSIONS:
            ext_raw = raw.get("extensions")
            if ext_raw is not None:
                ext = _expect_dict(ext_raw, f"{{path}}.extensions")
                if QUERY_ERROR_EXTENSIONS_HAS_STATUS_CODE:
                    value = ext.get("statusCode")
                    if value is not None:
                        status_code = _expect_int(value, f"{{path}}.extensions.statusCode")
        return QueryError(message=message, status_code=status_code)


@dataclass(frozen=True)
class CompassTeamRef:
    id: str
    display_name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassTeamRef":
        raw = _expect_dict(obj, path)
        return CompassTeamRef(
            id=_expect_str(raw.get(OWNER_TEAM_ID_FIELD), f"{{path}}.{{OWNER_TEAM_ID_FIELD}}"),
            display_name=_expect_str(raw.get(OWNER_TEAM_NAME_FIELD), f"{{path}}.{{OWNER_TEAM_NAME_FIELD}}"),
        )


@dataclass(frozen=True)
class CompassComponent:
    id: str
    name: str
    type_id: str
    description: Optional[str]
    owner_team: Optional[CompassTeamRef]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassComponent":
        raw = _expect_dict(obj, path)
        owner_raw = raw.get(OWNER_TEAM_FIELD)
        return CompassComponent(
            id=_expect_str(raw.get("id"), f"{{path}}.id"),
            name=_expect_str(raw.get("name"), f"{{path}}.name"),
            type_id=_expect_str(raw.get(COMPONENT_TYPE_ID_FIELD), f"{{path}}.{{COMPONENT_TYPE_ID_FIELD}}"),
            description=_expect_optional_str(
                raw.get(COMPONENT_DESCRIPTION_FIELD), f"{{path}}.{{COMPONENT_DESCRIPTION_FIELD}}"
            ),
            owner_team=CompassTeamRef.from_dict(owner_raw, f"{{path}}.{{OWNER_TEAM_FIELD}}")
            if owner_raw is not None
            else None,
        )


@dataclass(frozen=True)
class CompassComponentNode:
    component: Optional[CompassComponent]
    error: Optional[QueryError]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassComponentNode":
        raw = _expect_dict(obj, path)
        component_raw = raw.get("component")
        if component_raw is None:
            raise SerializationError(f"Missing {{path}}.component")
        component_obj = _expect_dict(component_raw, f"{{path}}.component")
        typename = component_obj.get("__typename")
        if typename == COMPONENT_TYPE_NAME or (COMPONENT_RESULT_KIND == "OBJECT" and typename is None):
            return CompassComponentNode(
                component=CompassComponent.from_dict(component_obj, f"{{path}}.component"),
                error=None,
            )
        if ERROR_TYPE_NAME and typename == ERROR_TYPE_NAME:
            return CompassComponentNode(
                component=None,
                error=QueryError.from_dict(component_obj, f"{{path}}.component"),
            )
        if "message" in component_obj and ERROR_TYPE_NAME:
            return CompassComponentNode(
                component=None,
                error=QueryError.from_dict(component_obj, f"{{path}}.component"),
            )
        if "id" in component_obj and "name" in component_obj:
            return CompassComponentNode(
                component=CompassComponent.from_dict(component_obj, f"{{path}}.component"),
                error=None,
            )
        raise SerializationError(f"Unexpected component type at {{path}}.component")


@dataclass(frozen=True)
class CompassComponentEdge:
    cursor: Optional[str]
    node: CompassComponentNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassComponentEdge":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if EDGE_HAS_CURSOR:
            value = raw.get("cursor")
            if value is not None:
                cursor = _expect_str(value, f"{{path}}.cursor")
        node = CompassComponentNode.from_dict(raw.get("node"), f"{{path}}.node")
        return CompassComponentEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class CompassSearchComponentConnection:
    page_info: PageInfo
    edges: List[CompassComponentEdge]
    nodes: Optional[List[CompassComponentNode]] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassSearchComponentConnection":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        edges_list = _expect_list(raw.get("edges"), f"{{path}}.edges")
        edges = [
            CompassComponentEdge.from_dict(item, f"{{path}}.edges[{{idx}}]")
            for idx, item in enumerate(edges_list)
        ]
        nodes: Optional[List[CompassComponentNode]] = None
        if CONNECTION_HAS_NODES:
            nodes_list = _expect_list(raw.get("nodes"), f"{{path}}.nodes")
            nodes = [
                CompassComponentNode.from_dict(item, f"{{path}}.nodes[{{idx}}]")
                for idx, item in enumerate(nodes_list)
            ]
        return CompassSearchComponentConnection(page_info=page_info, edges=edges, nodes=nodes)


def parse_compass_search_components(data: Any) -> Union[CompassSearchComponentConnection, QueryError]:
    root = _expect_dict(data, "data")
    compass = root.get("compass")
    if compass is None:
        raise SerializationError("Missing data.compass")
    compass_obj = _expect_dict(compass, "data.compass")
    result = compass_obj.get("searchComponents")
    if result is None:
        raise SerializationError("Missing data.compass.searchComponents")
    result_obj = _expect_dict(result, "data.compass.searchComponents")
    typename = result_obj.get("__typename")
    if typename == CONNECTION_TYPE_NAME or (SEARCH_RESULT_KIND == "OBJECT" and typename is None):
        return CompassSearchComponentConnection.from_dict(result_obj, "data.compass.searchComponents")
    if ERROR_TYPE_NAME and typename == ERROR_TYPE_NAME:
        return QueryError.from_dict(result_obj, "data.compass.searchComponents")
    if "pageInfo" in result_obj and "edges" in result_obj:
        return CompassSearchComponentConnection.from_dict(result_obj, "data.compass.searchComponents")
    if ERROR_TYPE_NAME and "message" in result_obj:
        return QueryError.from_dict(result_obj, "data.compass.searchComponents")
    raise SerializationError("Unexpected searchComponents response type")
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
    output_py = (
        repo_root
        / "python"
        / "atlassian"
        / "graph"
        / "gen"
        / "compass_components_api.py"
    )
    output_py.parent.mkdir(parents=True, exist_ok=True)
    output_py.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {output_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
