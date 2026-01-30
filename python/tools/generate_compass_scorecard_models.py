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
    component_id_type: str
    component_result_kind: str
    component_type_name: str
    error_type_name: Optional[str]
    scorecards_field_name: str
    connection_type_name: str
    pageinfo_has_end_cursor: bool
    edge_has_cursor: bool
    connection_has_nodes: bool
    query_error_has_extensions: bool
    query_error_extensions_has_status_code: bool
    score_field_name: str
    score_field_nullable: bool
    max_score_field_name: Optional[str]
    max_score_field_nullable: bool
    evaluated_at_field_name: Optional[str]
    evaluated_at_field_nullable: bool
    scorecard_field_name: Optional[str]
    scorecard_id_field_name: str
    scorecard_id_field_nullable: bool
    scorecard_name_field_name: Optional[str]
    scorecard_name_field_nullable: bool


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


def _is_nullable(type_ref: Dict[str, Any]) -> bool:
    if not isinstance(type_ref, dict):
        return True
    return type_ref.get("kind") != "NON_NULL"


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
        if _has_fields(candidate, ["id", "name"]):
            return candidate
    return None


def _discover_scorecards_field(
    types: Dict[str, Dict[str, Any]], component_def: Dict[str, Any]
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    fields = component_def.get("fields")
    if not isinstance(fields, list):
        raise RuntimeError("CompassComponent type has no fields")
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        if not isinstance(field_name, str) or not field_name:
            continue
        type_name, type_kind, _ = _unwrap_named_type(field.get("type") or {})
        if not type_name or not type_kind:
            continue
        type_def = types.get(type_name)
        if not type_def:
            continue
        connection_def: Optional[Dict[str, Any]] = None
        if type_kind in {"UNION", "INTERFACE"}:
            possible_defs = _possible_type_defs(types, type_def)
            connection_def = _discover_connection_type(possible_defs)
        else:
            if _has_fields(type_def, ["pageInfo", "edges"]):
                connection_def = type_def
        if not connection_def:
            continue
        edges_field = _field(connection_def, "edges")
        if not edges_field:
            continue
        edge_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
        if not edge_type_name:
            continue
        edge_def = types.get(edge_type_name)
        if not edge_def:
            continue
        node_field = _field(edge_def, "node")
        if not node_field:
            continue
        node_type_name, _, _ = _unwrap_named_type(node_field.get("type") or {})
        if not node_type_name:
            continue
        node_def = types.get(node_type_name)
        if not node_def:
            continue
        if _field(node_def, "score") is None:
            continue
        if (
            _field(node_def, "scorecard") is None
            and _field(node_def, "scorecardId") is None
        ):
            continue
        return field_name, connection_def, node_def
    raise RuntimeError("Unable to locate scorecards field on CompassComponent")


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

    component_field = _field(compass_def, "component")
    if not component_field:
        raise RuntimeError(f"Missing required field {compass_type_name}.component")
    id_arg = _arg(component_field, "id")
    if not id_arg or not isinstance(id_arg.get("type"), dict):
        raise RuntimeError("component.id missing type info")
    component_id_type = _type_ref_to_gql(id_arg["type"])

    component_return_name, component_return_kind, _ = _unwrap_named_type(
        component_field.get("type") or {}
    )
    if not component_return_name or not component_return_kind:
        raise RuntimeError("Unable to resolve component return type")
    component_return_def = _require_type(types, component_return_name)

    component_def = component_return_def
    error_def: Optional[Dict[str, Any]] = None
    if component_return_kind in {"UNION", "INTERFACE"}:
        possible_defs = _possible_type_defs(types, component_return_def)
        component_object_def = _discover_component_type(possible_defs)
        if not component_object_def:
            raise RuntimeError("Unable to determine CompassComponent type in union")
        component_def = component_object_def
        error_def = _discover_error_type(possible_defs)

    component_type_name = component_def.get("name")
    if not isinstance(component_type_name, str) or not component_type_name:
        raise RuntimeError("Invalid CompassComponent type name")

    scorecards_field_name, connection_def, node_def = _discover_scorecards_field(
        types, component_def
    )

    connection_type_name = connection_def.get("name")
    if not isinstance(connection_type_name, str) or not connection_type_name:
        raise RuntimeError("Invalid scorecards connection type name")

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
        raise RuntimeError("Unable to resolve PageInfo type for Compass scorecards")
    pageinfo_def = _require_type(types, pageinfo_type_name)
    _require_field(pageinfo_def, "hasNextPage", f"type {pageinfo_type_name}.fields")
    pageinfo_has_end_cursor = _field(pageinfo_def, "endCursor") is not None

    edge_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
    if not edge_type_name:
        raise RuntimeError("Unable to resolve edge type for Compass scorecards")
    edge_def = _require_type(types, edge_type_name)
    edge_has_cursor = _field(edge_def, "cursor") is not None

    score_field = _require_field(
        node_def, "score", f"type {node_def.get('name')}.fields"
    )
    score_field_name = score_field.get("name") or "score"
    score_field_nullable = _is_nullable(score_field.get("type") or {})

    max_score_field = _field(node_def, "maxScore")
    max_score_field_name = max_score_field.get("name") if max_score_field else None
    max_score_field_nullable = True
    if max_score_field:
        max_score_field_nullable = _is_nullable(max_score_field.get("type") or {})

    evaluated_field = _field(node_def, "evaluatedAt")
    evaluated_at_field_name = evaluated_field.get("name") if evaluated_field else None
    evaluated_at_field_nullable = True
    if evaluated_field:
        evaluated_at_field_nullable = _is_nullable(evaluated_field.get("type") or {})

    scorecard_field = _field(node_def, "scorecard")
    scorecard_id_field_name = "scorecardId"
    scorecard_id_field_nullable = False
    scorecard_name_field_name: Optional[str] = None
    scorecard_name_field_nullable = True
    if scorecard_field:
        scorecard_field_name = scorecard_field.get("name")
        scorecard_type_name, _, _ = _unwrap_named_type(
            scorecard_field.get("type") or {}
        )
        if not scorecard_type_name:
            raise RuntimeError("Unable to resolve scorecard type for scorecards")
        scorecard_def = _require_type(types, scorecard_type_name)
        scorecard_id = _require_field(
            scorecard_def, "id", f"type {scorecard_type_name}.fields"
        )
        scorecard_id_field_name = scorecard_id.get("name") or "id"
        scorecard_id_field_nullable = _is_nullable(scorecard_id.get("type") or {})
        name_field = _field(scorecard_def, "name") or _field(
            scorecard_def, "displayName"
        )
        if name_field:
            scorecard_name_field_name = name_field.get("name")
            scorecard_name_field_nullable = _is_nullable(name_field.get("type") or {})
    else:
        scorecard_field_name = None
        scorecard_id_field = _field(node_def, "scorecardId")
        if not scorecard_id_field:
            raise RuntimeError("Scorecard node missing scorecard or scorecardId field")
        scorecard_id_field_name = scorecard_id_field.get("name") or "scorecardId"
        scorecard_id_field_nullable = _is_nullable(scorecard_id_field.get("type") or {})

    error_type_name: Optional[str] = None
    query_error_has_extensions = False
    query_error_extensions_has_status_code = False
    if error_def:
        error_type_name = (
            error_def.get("name") if isinstance(error_def.get("name"), str) else None
        )
        if error_type_name:
            extensions_field = _field(error_def, "extensions")
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
        component_id_type=component_id_type,
        component_result_kind=component_return_kind,
        component_type_name=component_type_name,
        error_type_name=error_type_name,
        scorecards_field_name=scorecards_field_name,
        connection_type_name=connection_type_name,
        pageinfo_has_end_cursor=pageinfo_has_end_cursor,
        edge_has_cursor=edge_has_cursor,
        connection_has_nodes=connection_has_nodes,
        query_error_has_extensions=query_error_has_extensions,
        query_error_extensions_has_status_code=query_error_extensions_has_status_code,
        score_field_name=score_field_name,
        score_field_nullable=score_field_nullable,
        max_score_field_name=max_score_field_name,
        max_score_field_nullable=max_score_field_nullable,
        evaluated_at_field_name=evaluated_at_field_name,
        evaluated_at_field_nullable=evaluated_at_field_nullable,
        scorecard_field_name=scorecard_field_name,
        scorecard_id_field_name=scorecard_id_field_name,
        scorecard_id_field_nullable=scorecard_id_field_nullable,
        scorecard_name_field_name=scorecard_name_field_name,
        scorecard_name_field_nullable=scorecard_name_field_nullable,
    )


def _render_python(cfg: _Config) -> str:
    pageinfo_select = "hasNextPage"
    if cfg.pageinfo_has_end_cursor:
        pageinfo_select += " endCursor"

    edges_select = "node {"
    if cfg.edge_has_cursor:
        edges_select = "cursor\n          node {"

    scorecard_select = ""
    if cfg.scorecard_field_name:
        scorecard_name_select = (
            f" {cfg.scorecard_name_field_name}" if cfg.scorecard_name_field_name else ""
        )
        scorecard_select = (
            f"{cfg.scorecard_field_name} {{ {cfg.scorecard_id_field_name}"
            f"{scorecard_name_select} }}"
        )

    node_fields = [cfg.score_field_name]
    if cfg.max_score_field_name:
        node_fields.append(cfg.max_score_field_name)
    if cfg.evaluated_at_field_name:
        node_fields.append(cfg.evaluated_at_field_name)
    if scorecard_select:
        node_fields.append(scorecard_select)
    else:
        node_fields.append(cfg.scorecard_id_field_name)

    node_select = "\n            ".join(node_fields)

    nodes_select = ""
    if cfg.connection_has_nodes:
        nodes_select = "\n        nodes {\n          " + node_select + "\n        }"

    query = f"""query CompassComponentScorecards(
  $componentId: {cfg.component_id_type}
) {{
  compass {{
    component(id: $componentId) {{
      __typename
      ... on {cfg.component_type_name} {{
        {cfg.scorecards_field_name} {{
          pageInfo {{ {pageinfo_select} }}
          edges {{
            {edges_select}
              {node_select}
            }}
          }}{nodes_select}
        }}
      }}
"""

    if cfg.error_type_name:
        query += f"""      ... on {cfg.error_type_name} {{
        message
"""
        if cfg.query_error_extensions_has_status_code:
            query += "        extensions { statusCode }\n"
        query += "      }\n"

    query += """    }
  }
}
"""

    scorecard_name_field_name = cfg.scorecard_name_field_name or ""
    max_score_field_name = cfg.max_score_field_name or ""
    evaluated_at_field_name = cfg.evaluated_at_field_name or ""
    scorecard_field_name = cfg.scorecard_field_name or ""

    return f"""# Code generated by python/tools/generate_compass_scorecard_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from atlassian.errors import SerializationError

COMPONENT_TYPE_NAME = {cfg.component_type_name!r}
ERROR_TYPE_NAME = {cfg.error_type_name!r}
PAGEINFO_HAS_END_CURSOR = {str(cfg.pageinfo_has_end_cursor)}
EDGE_HAS_CURSOR = {str(cfg.edge_has_cursor)}
CONNECTION_HAS_NODES = {str(cfg.connection_has_nodes)}
QUERY_ERROR_HAS_EXTENSIONS = {str(cfg.query_error_has_extensions)}
QUERY_ERROR_EXTENSIONS_HAS_STATUS_CODE = {str(cfg.query_error_extensions_has_status_code)}
COMPONENT_RESULT_KIND = {cfg.component_result_kind!r}

SCORECARDS_FIELD_NAME = {cfg.scorecards_field_name!r}
SCORE_FIELD_NAME = {cfg.score_field_name!r}
SCORE_FIELD_NULLABLE = {str(cfg.score_field_nullable)}
MAX_SCORE_FIELD_NAME = {max_score_field_name!r}
MAX_SCORE_FIELD_NULLABLE = {str(cfg.max_score_field_nullable)}
EVALUATED_AT_FIELD_NAME = {evaluated_at_field_name!r}
EVALUATED_AT_FIELD_NULLABLE = {str(cfg.evaluated_at_field_nullable)}
SCORECARD_FIELD_NAME = {scorecard_field_name!r}
SCORECARD_ID_FIELD_NAME = {cfg.scorecard_id_field_name!r}
SCORECARD_ID_FIELD_NULLABLE = {str(cfg.scorecard_id_field_nullable)}
SCORECARD_NAME_FIELD_NAME = {scorecard_name_field_name!r}
SCORECARD_NAME_FIELD_NULLABLE = {str(cfg.scorecard_name_field_nullable)}

COMPASS_COMPONENT_SCORECARDS_QUERY = {query!r}


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


def _expect_float(obj: Any, path: str) -> float:
    if not isinstance(obj, (int, float)) or isinstance(obj, bool):
        raise SerializationError(f"Expected number at {{path}}")
    return float(obj)


def _expect_optional_float(obj: Any, path: str) -> Optional[float]:
    if obj is None:
        return None
    return _expect_float(obj, path)


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
class CompassScorecardRef:
    id: str
    name: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassScorecardRef":
        raw = _expect_dict(obj, path)
        scorecard_id = raw.get(SCORECARD_ID_FIELD_NAME)
        if SCORECARD_ID_FIELD_NULLABLE:
            scorecard_id = _expect_optional_str(scorecard_id, f"{{path}}.{{SCORECARD_ID_FIELD_NAME}}")
        else:
            scorecard_id = _expect_str(scorecard_id, f"{{path}}.{{SCORECARD_ID_FIELD_NAME}}")
        scorecard_name: Optional[str] = None
        if SCORECARD_NAME_FIELD_NAME:
            name_value = raw.get(SCORECARD_NAME_FIELD_NAME)
            if SCORECARD_NAME_FIELD_NULLABLE:
                scorecard_name = _expect_optional_str(
                    name_value, f"{{path}}.{{SCORECARD_NAME_FIELD_NAME}}"
                )
            else:
                scorecard_name = _expect_str(
                    name_value, f"{{path}}.{{SCORECARD_NAME_FIELD_NAME}}"
                )
        if scorecard_id is None:
            raise SerializationError(f"Expected non-empty string at {{path}}.{{SCORECARD_ID_FIELD_NAME}}")
        return CompassScorecardRef(id=scorecard_id, name=scorecard_name)


@dataclass(frozen=True)
class CompassScorecardNode:
    scorecard_id: str
    scorecard_name: Optional[str]
    score: float
    max_score: Optional[float] = None
    evaluated_at: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassScorecardNode":
        raw = _expect_dict(obj, path)
        if SCORE_FIELD_NULLABLE:
            score_value = _expect_optional_float(raw.get(SCORE_FIELD_NAME), f"{{path}}.{{SCORE_FIELD_NAME}}")
            if score_value is None:
                raise SerializationError(f"Expected number at {{path}}.{{SCORE_FIELD_NAME}}")
        else:
            score_value = _expect_float(raw.get(SCORE_FIELD_NAME), f"{{path}}.{{SCORE_FIELD_NAME}}")
        max_score: Optional[float] = None
        if MAX_SCORE_FIELD_NAME:
            value = raw.get(MAX_SCORE_FIELD_NAME)
            if MAX_SCORE_FIELD_NULLABLE:
                max_score = _expect_optional_float(value, f"{{path}}.{{MAX_SCORE_FIELD_NAME}}")
            else:
                max_score = _expect_float(value, f"{{path}}.{{MAX_SCORE_FIELD_NAME}}")
        evaluated_at: Optional[str] = None
        if EVALUATED_AT_FIELD_NAME:
            value = raw.get(EVALUATED_AT_FIELD_NAME)
            if EVALUATED_AT_FIELD_NULLABLE:
                evaluated_at = _expect_optional_str(value, f"{{path}}.{{EVALUATED_AT_FIELD_NAME}}")
            else:
                evaluated_at = _expect_str(value, f"{{path}}.{{EVALUATED_AT_FIELD_NAME}}")
        scorecard_id = ""
        scorecard_name: Optional[str] = None
        if SCORECARD_FIELD_NAME:
            scorecard_raw = raw.get(SCORECARD_FIELD_NAME)
            scorecard = CompassScorecardRef.from_dict(
                scorecard_raw, f"{{path}}.{{SCORECARD_FIELD_NAME}}"
            )
            scorecard_id = scorecard.id
            scorecard_name = scorecard.name
        else:
            scorecard_id = _expect_str(
                raw.get(SCORECARD_ID_FIELD_NAME), f"{{path}}.{{SCORECARD_ID_FIELD_NAME}}"
            )
        return CompassScorecardNode(
            scorecard_id=scorecard_id,
            scorecard_name=scorecard_name,
            score=score_value,
            max_score=max_score,
            evaluated_at=evaluated_at,
        )


@dataclass(frozen=True)
class CompassScorecardEdge:
    cursor: Optional[str]
    node: CompassScorecardNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassScorecardEdge":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if EDGE_HAS_CURSOR:
            value = raw.get("cursor")
            if value is not None:
                cursor = _expect_str(value, f"{{path}}.cursor")
        node = CompassScorecardNode.from_dict(raw.get("node"), f"{{path}}.node")
        return CompassScorecardEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class CompassScorecardConnection:
    page_info: PageInfo
    edges: List[CompassScorecardEdge]
    nodes: Optional[List[CompassScorecardNode]] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "CompassScorecardConnection":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        edges_list = _expect_list(raw.get("edges"), f"{{path}}.edges")
        edges = [
            CompassScorecardEdge.from_dict(item, f"{{path}}.edges[{{idx}}]")
            for idx, item in enumerate(edges_list)
        ]
        nodes: Optional[List[CompassScorecardNode]] = None
        if CONNECTION_HAS_NODES:
            nodes_list = _expect_list(raw.get("nodes"), f"{{path}}.nodes")
            nodes = [
                CompassScorecardNode.from_dict(item, f"{{path}}.nodes[{{idx}}]")
                for idx, item in enumerate(nodes_list)
            ]
        return CompassScorecardConnection(page_info=page_info, edges=edges, nodes=nodes)


def parse_compass_component_scorecards(
    data: Any,
) -> Union[CompassScorecardConnection, QueryError]:
    root = _expect_dict(data, "data")
    compass = root.get("compass")
    if compass is None:
        raise SerializationError("Missing data.compass")
    compass_obj = _expect_dict(compass, "data.compass")
    component = compass_obj.get("component")
    if component is None:
        raise SerializationError("Missing data.compass.component")
    component_obj = _expect_dict(component, "data.compass.component")
    typename = component_obj.get("__typename")
    if typename == COMPONENT_TYPE_NAME or (COMPONENT_RESULT_KIND == "OBJECT" and typename is None):
        scorecards = component_obj.get(SCORECARDS_FIELD_NAME)
        if scorecards is None:
            raise SerializationError(
                f"Missing data.compass.component.{{SCORECARDS_FIELD_NAME}}"
            )
        return CompassScorecardConnection.from_dict(
            scorecards, f"data.compass.component.{{SCORECARDS_FIELD_NAME}}"
        )
    if ERROR_TYPE_NAME and typename == ERROR_TYPE_NAME:
        return QueryError.from_dict(component_obj, "data.compass.component")
    if ERROR_TYPE_NAME and "message" in component_obj:
        return QueryError.from_dict(component_obj, "data.compass.component")
    raise SerializationError("Unexpected component response type")
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
        / "compass_scorecards_api.py"
    )
    output_py.parent.mkdir(parents=True, exist_ok=True)
    output_py.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {output_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
