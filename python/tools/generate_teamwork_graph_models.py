from __future__ import annotations

import json
import os
import re
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


TEAMWORK_GRAPH_QUERY_FIELDS = (
    "teamworkGraph_teamActiveProjects",
    "teamworkGraph_teamUsers",
    "teamworkGraph_userTeams",
    "teamworkGraph_userManager",
    "teamworkGraph_userDirectReports",
)


@dataclass(frozen=True)
class _QueryConfig:
    name: str
    id_arg_name: str
    id_arg_type: str
    first_arg_type: Optional[str]
    after_arg_type: Optional[str]
    opt_in_target: str


@dataclass(frozen=True)
class _AriNodeDataType:
    type_name: str
    id_field: Optional[str]
    account_id_field: Optional[str]
    name_field: Optional[str]
    display_name_field: Optional[str]
    key_field: Optional[str]


@dataclass(frozen=True)
class _Config:
    connection_type_name: str
    edge_type_name: str
    node_type_name: str
    column_type_name: str
    value_union_type_name: str
    pageinfo_type_name: str
    pageinfo_has_end_cursor: bool
    pageinfo_has_start_cursor: bool
    pageinfo_has_previous_page: bool
    edge_has_cursor: bool
    connection_version_field: str
    query_type_name: str
    opt_in_directive: str
    opt_in_target: str
    ari_node_type_name: str
    ari_node_data_union_name: Optional[str]
    node_list_type_name: str
    path_type_name: str
    string_object_type_name: str
    int_object_type_name: str
    float_object_type_name: str
    boolean_object_type_name: str
    timestamp_object_type_name: str
    data_types: List[_AriNodeDataType]
    queries: List[_QueryConfig]


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


def _field_name(type_def: Dict[str, Any], name: str) -> Optional[str]:
    field = _field(type_def, name)
    if not field:
        return None
    field_name = field.get("name")
    return field_name if isinstance(field_name, str) and field_name else None


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


def _require_opt_in_directive(schema: Dict[str, Any]) -> None:
    directives = schema.get("directives")
    if not isinstance(directives, list):
        raise RuntimeError("Introspection JSON missing __schema.directives[]")
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        if directive.get("name") == "optIn":
            return
    raise RuntimeError("Missing @optIn directive in schema")


_OPT_IN_RE = re.compile(r"@optIn\(to: \"(?P<target>[^\"]+)\"\)")


def _extract_opt_in_target(field_def: Dict[str, Any], name: str) -> str:
    desc = field_def.get("description")
    if not isinstance(desc, str):
        raise RuntimeError(f"Missing description for {name} to extract optIn target")
    match = _OPT_IN_RE.search(desc)
    if not match:
        raise RuntimeError(f"Missing @optIn target in {name} description")
    target = match.group("target")
    if not target:
        raise RuntimeError(f"Empty @optIn target in {name} description")
    return target


def _discover_queries(
    query_def: Dict[str, Any],
) -> List[Tuple[Dict[str, Any], str]]:
    fields = query_def.get("fields")
    if not isinstance(fields, list):
        raise RuntimeError("Query type missing fields")
    found = {f.get("name"): f for f in fields if isinstance(f, dict)}
    out: List[Tuple[Dict[str, Any], str]] = []
    for name in TEAMWORK_GRAPH_QUERY_FIELDS:
        field_def = found.get(name)
        if not field_def:
            raise RuntimeError(f"Missing required teamworkGraph query field: {name}")
        out.append((field_def, name))
    return out


def _discover_config(schema: Dict[str, Any]) -> _Config:
    types = _types_map(schema)
    _require_opt_in_directive(schema)

    query_type = schema.get("queryType")
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    if not isinstance(query_name, str) or not query_name:
        raise RuntimeError("Introspection JSON missing __schema.queryType.name")
    query_def = _require_type(types, query_name)

    query_fields = _discover_queries(query_def)

    opt_in_targets = set()
    query_configs: List[_QueryConfig] = []
    connection_type_name: Optional[str] = None

    for field_def, name in query_fields:
        opt_in_target = _extract_opt_in_target(field_def, name)
        opt_in_targets.add(opt_in_target)

        id_arg = _arg(field_def, "teamId") or _arg(field_def, "userId")
        if not id_arg or not isinstance(id_arg.get("type"), dict):
            raise RuntimeError(f"Missing teamId/userId arg on {name}")
        id_arg_name = "teamId" if _arg(field_def, "teamId") else "userId"
        id_arg_type = _type_ref_to_gql(id_arg["type"])

        first_arg = _arg(field_def, "first")
        after_arg = _arg(field_def, "after")
        first_arg_type = _type_ref_to_gql(first_arg["type"]) if first_arg else None
        after_arg_type = _type_ref_to_gql(after_arg["type"]) if after_arg else None

        return_type_name, _, _ = _unwrap_named_type(field_def.get("type") or {})
        if not return_type_name:
            raise RuntimeError(f"Unable to resolve return type for {name}")
        if connection_type_name is None:
            connection_type_name = return_type_name
        elif connection_type_name != return_type_name:
            raise RuntimeError(
                f"Mismatched teamworkGraph return types: {connection_type_name} vs {return_type_name}"
            )

        query_configs.append(
            _QueryConfig(
                name=name,
                id_arg_name=id_arg_name,
                id_arg_type=id_arg_type,
                first_arg_type=first_arg_type,
                after_arg_type=after_arg_type,
                opt_in_target=opt_in_target,
            )
        )

    if not connection_type_name:
        raise RuntimeError("Unable to determine teamworkGraph connection type")
    if len(opt_in_targets) != 1:
        raise RuntimeError(
            "teamworkGraph queries did not agree on a single optIn target"
        )
    opt_in_target = next(iter(opt_in_targets))

    connection_def = _require_type(types, connection_type_name)
    pageinfo_field = _require_field(
        connection_def, "pageInfo", f"type {connection_type_name}.fields"
    )
    edges_field = _require_field(
        connection_def, "edges", f"type {connection_type_name}.fields"
    )
    version_field = _require_field(
        connection_def, "version", f"type {connection_type_name}.fields"
    )

    pageinfo_type_name, _, _ = _unwrap_named_type(pageinfo_field.get("type") or {})
    if not pageinfo_type_name:
        raise RuntimeError("Unable to resolve PageInfo type")
    pageinfo_def = _require_type(types, pageinfo_type_name)
    _require_field(pageinfo_def, "hasNextPage", f"type {pageinfo_type_name}.fields")
    pageinfo_has_end_cursor = _field(pageinfo_def, "endCursor") is not None
    pageinfo_has_start_cursor = _field(pageinfo_def, "startCursor") is not None
    pageinfo_has_previous_page = _field(pageinfo_def, "hasPreviousPage") is not None

    edge_type_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
    if not edge_type_name:
        raise RuntimeError("Unable to resolve edge type")
    edge_def = _require_type(types, edge_type_name)
    edge_has_cursor = _field(edge_def, "cursor") is not None
    node_field = _require_field(edge_def, "node", f"type {edge_type_name}.fields")

    node_type_name, _, _ = _unwrap_named_type(node_field.get("type") or {})
    if not node_type_name:
        raise RuntimeError("Unable to resolve edge node type")
    node_def = _require_type(types, node_type_name)
    columns_field = _require_field(node_def, "columns", f"type {node_type_name}.fields")

    column_type_name, _, _ = _unwrap_named_type(columns_field.get("type") or {})
    if not column_type_name:
        raise RuntimeError("Unable to resolve column type")
    column_def = _require_type(types, column_type_name)
    _require_field(column_def, "key", f"type {column_type_name}.fields")
    value_field = _require_field(column_def, "value", f"type {column_type_name}.fields")

    value_union_type_name, value_union_kind, _ = _unwrap_named_type(
        value_field.get("type") or {}
    )
    if not value_union_type_name or value_union_kind not in {"UNION", "INTERFACE"}:
        raise RuntimeError("Column value is not a union type")
    value_union_def = _require_type(types, value_union_type_name)

    value_possible_defs = _possible_type_defs(types, value_union_def)
    value_possible_names = {item.get("name") for item in value_possible_defs}

    def _require_possible(name: str) -> str:
        if name not in value_possible_names:
            raise RuntimeError(
                f"Missing {name} in {value_union_type_name} possible types"
            )
        return name

    ari_node_type_name = _require_possible("GraphStoreCypherQueryV2AriNode")
    node_list_type_name = _require_possible("GraphStoreCypherQueryV2NodeList")
    path_type_name = _require_possible("GraphStoreCypherQueryV2Path")
    string_object_type_name = _require_possible("GraphStoreCypherQueryV2StringObject")
    int_object_type_name = _require_possible("GraphStoreCypherQueryV2IntObject")
    float_object_type_name = _require_possible("GraphStoreCypherQueryV2FloatObject")
    boolean_object_type_name = _require_possible("GraphStoreCypherQueryV2BooleanObject")
    timestamp_object_type_name = _require_possible(
        "GraphStoreCypherQueryV2TimestampObject"
    )

    ari_node_def = _require_type(types, ari_node_type_name)
    _require_field(ari_node_def, "id", f"type {ari_node_type_name}.fields")
    ari_data_field = _require_field(
        ari_node_def, "data", f"type {ari_node_type_name}.fields"
    )

    data_union_name, data_union_kind, _ = _unwrap_named_type(
        ari_data_field.get("type") or {}
    )
    if not data_union_name or data_union_kind not in {"UNION", "INTERFACE"}:
        raise RuntimeError("AriNode.data is not a union type")
    data_union_def = _require_type(types, data_union_name)
    data_possible_defs = _possible_type_defs(types, data_union_def)

    data_type_candidates = [
        "TeamV2",
        "AtlassianAccountUser",
        "JiraProject",
        "TownsquareProject",
    ]
    data_types: List[_AriNodeDataType] = []
    for candidate in data_type_candidates:
        candidate_def = next(
            (item for item in data_possible_defs if item.get("name") == candidate),
            None,
        )
        if not candidate_def:
            continue
        data_types.append(
            _AriNodeDataType(
                type_name=candidate,
                id_field=_field_name(candidate_def, "id"),
                account_id_field=_field_name(candidate_def, "accountId"),
                name_field=_field_name(candidate_def, "name"),
                display_name_field=_field_name(candidate_def, "displayName"),
                key_field=_field_name(candidate_def, "key"),
            )
        )

    return _Config(
        connection_type_name=connection_type_name,
        edge_type_name=edge_type_name,
        node_type_name=node_type_name,
        column_type_name=column_type_name,
        value_union_type_name=value_union_type_name,
        pageinfo_type_name=pageinfo_type_name,
        pageinfo_has_end_cursor=pageinfo_has_end_cursor,
        pageinfo_has_start_cursor=pageinfo_has_start_cursor,
        pageinfo_has_previous_page=pageinfo_has_previous_page,
        edge_has_cursor=edge_has_cursor,
        connection_version_field=version_field.get("name") or "version",
        query_type_name=query_name,
        opt_in_directive="optIn",
        opt_in_target=opt_in_target,
        ari_node_type_name=ari_node_type_name,
        ari_node_data_union_name=data_union_name,
        node_list_type_name=node_list_type_name,
        path_type_name=path_type_name,
        string_object_type_name=string_object_type_name,
        int_object_type_name=int_object_type_name,
        float_object_type_name=float_object_type_name,
        boolean_object_type_name=boolean_object_type_name,
        timestamp_object_type_name=timestamp_object_type_name,
        data_types=data_types,
        queries=query_configs,
    )


def _render_ari_node_data_selection(cfg: _Config) -> List[str]:
    lines = ["__typename"]
    for data_type in cfg.data_types:
        fields: List[str] = []
        for name in (
            data_type.id_field,
            data_type.account_id_field,
            data_type.name_field,
            data_type.display_name_field,
            data_type.key_field,
        ):
            if name and name not in fields:
                fields.append(name)
        if not fields:
            continue
        fields_line = " ".join(fields)
        lines.append(f"... on {data_type.type_name} {{ {fields_line} }}")
    return lines


def _render_value_selection(cfg: _Config) -> str:
    data_lines = _render_ari_node_data_selection(cfg)
    data_block = "\n".join(
        ["      data {"] + [f"        {line}" for line in data_lines] + ["      }"]
    )
    node_block = "\n".join(
        [
            f"    ... on {cfg.ari_node_type_name} {{",
            "      id",
            data_block,
            "    }",
        ]
    )
    node_list_block = "\n".join(
        [
            f"    ... on {cfg.node_list_type_name} {{",
            "      nodes {",
            "        id",
            data_block,
            "      }",
            "    }",
        ]
    )
    blocks = [
        "    __typename",
        node_block,
        node_list_block,
        f"    ... on {cfg.string_object_type_name} {{ value }}",
        f"    ... on {cfg.int_object_type_name} {{ value }}",
        f"    ... on {cfg.float_object_type_name} {{ value }}",
        f"    ... on {cfg.boolean_object_type_name} {{ value }}",
        f"    ... on {cfg.timestamp_object_type_name} {{ value }}",
        f"    ... on {cfg.path_type_name} {{ elements }}",
    ]
    return "\n".join(blocks)


def _render_query(cfg: _Config, query: _QueryConfig) -> str:
    var_lines = [f"  ${query.id_arg_name}: {query.id_arg_type},"]
    arg_lines = [f"{query.id_arg_name}: ${query.id_arg_name}"]
    if query.first_arg_type:
        var_lines.append(f"  $first: {query.first_arg_type},")
        arg_lines.append("first: $first")
    if query.after_arg_type:
        var_lines.append(f"  $after: {query.after_arg_type},")
        arg_lines.append("after: $after")
    var_block = "\n".join(var_lines)
    args_block = "\n      ".join(arg_lines)

    pageinfo_fields = ["hasNextPage"]
    if cfg.pageinfo_has_end_cursor:
        pageinfo_fields.append("endCursor")
    if cfg.pageinfo_has_start_cursor:
        pageinfo_fields.append("startCursor")
    if cfg.pageinfo_has_previous_page:
        pageinfo_fields.append("hasPreviousPage")
    pageinfo_block = " ".join(pageinfo_fields)

    value_block = _render_value_selection(cfg)
    query_body = f"""query {query.name.replace("teamworkGraph_", "TeamworkGraph_")}(
{var_block}
) {{
  {query.name}(
      {args_block}
    ) @optIn(to: \"{query.opt_in_target}\") {{
      {cfg.connection_version_field}
      pageInfo {{ {pageinfo_block} }}
      edges {{
        {"cursor" if cfg.edge_has_cursor else ""}
        node {{
          columns {{
            key
            value {{
{value_block}
            }}
          }}
        }}
      }}
    }}
}}
"""
    return "\n".join(line for line in query_body.splitlines() if line.rstrip()) + "\n"


def _render_python(cfg: _Config) -> str:
    query_constants = []
    for query in cfg.queries:
        query_text = _render_query(cfg, query)
        constant_name = query.name.upper()
        query_constants.append((constant_name, query_text))

    constants_block = "\n".join(f"{name} = {text!r}" for name, text in query_constants)

    parse_funcs = []
    for query in cfg.queries:
        func_name = f"parse_{query.name}"
        parse_funcs.append(
            f"""
def {func_name}(data: Any) -> GraphStoreCypherQueryV2Connection:
    root = _expect_dict(data, "data")
    result = root.get("{query.name}")
    if result is None:
        raise SerializationError("Missing data.{query.name}")
    return GraphStoreCypherQueryV2Connection.from_dict(result, "data.{query.name}")
"""
        )

    data_type_map_lines = []
    for data_type in cfg.data_types:
        line = f"    {data_type.type_name!r}: ("
        line += f"{data_type.id_field!r}, {data_type.account_id_field!r}, {data_type.name_field!r}, "
        line += f"{data_type.display_name_field!r}, {data_type.key_field!r}),"
        data_type_map_lines.append(line)

    data_type_map = "\n".join(data_type_map_lines)

    return f"""# Code generated by python/tools/generate_teamwork_graph_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from atlassian.errors import SerializationError

# Teamwork Graph APIs are EAP/experimental. They require @optIn(to: \"{cfg.opt_in_target}\")
# and are not available for OAuth-authenticated requests.
# Manager relationship queries require the X-Force-Dynamo: true header.

TEAMWORK_GRAPH_OPT_IN = {cfg.opt_in_target!r}

{constants_block}


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
    if not isinstance(obj, (float, int)):
        raise SerializationError(f"Expected float at {{path}}")
    return float(obj)


@dataclass(frozen=True)
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str]
    start_cursor: Optional[str]
    has_previous_page: Optional[bool]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "PageInfo":
        raw = _expect_dict(obj, path)
        has_next = _expect_bool(raw.get("hasNextPage"), f"{{path}}.hasNextPage")
        end_cursor = (
            _expect_optional_str(raw.get("endCursor"), f"{{path}}.endCursor")
            if {str(cfg.pageinfo_has_end_cursor)}
            else None
        )
        start_cursor = (
            _expect_optional_str(raw.get("startCursor"), f"{{path}}.startCursor")
            if {str(cfg.pageinfo_has_start_cursor)}
            else None
        )
        has_previous = (
            _expect_bool(raw.get("hasPreviousPage"), f"{{path}}.hasPreviousPage")
            if {str(cfg.pageinfo_has_previous_page)}
            else None
        )
        return PageInfo(
            has_next_page=has_next,
            end_cursor=end_cursor,
            start_cursor=start_cursor,
            has_previous_page=has_previous,
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2AriNodeData:
    typename: str
    id: Optional[str]
    account_id: Optional[str]
    name: Optional[str]
    display_name: Optional[str]
    key: Optional[str]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2AriNodeData":
        raw = _expect_dict(obj, path)
        typename = _expect_str(raw.get("__typename"), f"{{path}}.__typename")
        mapping = {{
{data_type_map}
        }}
        id_field, account_field, name_field, display_field, key_field = mapping.get(
            typename, ("id", "accountId", "name", "displayName", "key")
        )
        return GraphStoreCypherQueryV2AriNodeData(
            typename=typename,
            id=_expect_optional_str(raw.get(id_field), f"{{path}}.{{id_field}}")
            if id_field
            else None,
            account_id=_expect_optional_str(
                raw.get(account_field), f"{{path}}.{{account_field}}"
            )
            if account_field
            else None,
            name=_expect_optional_str(raw.get(name_field), f"{{path}}.{{name_field}}")
            if name_field
            else None,
            display_name=_expect_optional_str(
                raw.get(display_field), f"{{path}}.{{display_field}}"
            )
            if display_field
            else None,
            key=_expect_optional_str(raw.get(key_field), f"{{path}}.{{key_field}}")
            if key_field
            else None,
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2AriNode:
    id: str
    data: Optional[GraphStoreCypherQueryV2AriNodeData]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2AriNode":
        raw = _expect_dict(obj, path)
        data_raw = raw.get("data")
        return GraphStoreCypherQueryV2AriNode(
            id=_expect_str(raw.get("id"), f"{{path}}.id"),
            data=GraphStoreCypherQueryV2AriNodeData.from_dict(
                data_raw, f"{{path}}.data"
            )
            if data_raw is not None
            else None,
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2NodeList:
    nodes: List[GraphStoreCypherQueryV2AriNode]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2NodeList":
        raw = _expect_dict(obj, path)
        nodes_raw = _expect_list(raw.get("nodes"), f"{{path}}.nodes")
        return GraphStoreCypherQueryV2NodeList(
            nodes=[
                GraphStoreCypherQueryV2AriNode.from_dict(item, f"{{path}}.nodes[{{idx}}]")
                for idx, item in enumerate(nodes_raw)
            ]
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2Path:
    elements: List[str]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2Path":
        raw = _expect_dict(obj, path)
        elements = _expect_list(raw.get("elements"), f"{{path}}.elements")
        return GraphStoreCypherQueryV2Path(
            elements=[
                _expect_str(item, f"{{path}}.elements[{{idx}}]")
                for idx, item in enumerate(elements)
            ]
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2StringObject:
    value: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2StringObject":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2StringObject(
            value=_expect_str(raw.get("value"), f"{{path}}.value")
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2IntObject:
    value: int

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2IntObject":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2IntObject(
            value=_expect_int(raw.get("value"), f"{{path}}.value")
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2FloatObject:
    value: float

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2FloatObject":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2FloatObject(
            value=_expect_float(raw.get("value"), f"{{path}}.value")
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2BooleanObject:
    value: bool

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2BooleanObject":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2BooleanObject(
            value=_expect_bool(raw.get("value"), f"{{path}}.value")
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2TimestampObject:
    value: int

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2TimestampObject":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2TimestampObject(
            value=_expect_int(raw.get("value"), f"{{path}}.value")
        )


GraphStoreCypherQueryV2Value = Union[
    GraphStoreCypherQueryV2AriNode,
    GraphStoreCypherQueryV2NodeList,
    GraphStoreCypherQueryV2Path,
    GraphStoreCypherQueryV2StringObject,
    GraphStoreCypherQueryV2IntObject,
    GraphStoreCypherQueryV2FloatObject,
    GraphStoreCypherQueryV2BooleanObject,
    GraphStoreCypherQueryV2TimestampObject,
]


def _parse_value(obj: Any, path: str) -> Optional[GraphStoreCypherQueryV2Value]:
    if obj is None:
        return None
    raw = _expect_dict(obj, path)
    typename = raw.get("__typename")
    if typename == {cfg.ari_node_type_name!r}:
        return GraphStoreCypherQueryV2AriNode.from_dict(raw, path)
    if typename == {cfg.node_list_type_name!r}:
        return GraphStoreCypherQueryV2NodeList.from_dict(raw, path)
    if typename == {cfg.path_type_name!r}:
        return GraphStoreCypherQueryV2Path.from_dict(raw, path)
    if typename == {cfg.string_object_type_name!r}:
        return GraphStoreCypherQueryV2StringObject.from_dict(raw, path)
    if typename == {cfg.int_object_type_name!r}:
        return GraphStoreCypherQueryV2IntObject.from_dict(raw, path)
    if typename == {cfg.float_object_type_name!r}:
        return GraphStoreCypherQueryV2FloatObject.from_dict(raw, path)
    if typename == {cfg.boolean_object_type_name!r}:
        return GraphStoreCypherQueryV2BooleanObject.from_dict(raw, path)
    if typename == {cfg.timestamp_object_type_name!r}:
        return GraphStoreCypherQueryV2TimestampObject.from_dict(raw, path)
    if "id" in raw and "data" in raw:
        return GraphStoreCypherQueryV2AriNode.from_dict(raw, path)
    if "nodes" in raw:
        return GraphStoreCypherQueryV2NodeList.from_dict(raw, path)
    if "elements" in raw:
        return GraphStoreCypherQueryV2Path.from_dict(raw, path)
    if "value" in raw:
        value = raw.get("value")
        if isinstance(value, bool):
            return GraphStoreCypherQueryV2BooleanObject.from_dict(raw, path)
        if isinstance(value, int):
            return GraphStoreCypherQueryV2IntObject.from_dict(raw, path)
        if isinstance(value, float):
            return GraphStoreCypherQueryV2FloatObject.from_dict(raw, path)
        if isinstance(value, str):
            return GraphStoreCypherQueryV2StringObject.from_dict(raw, path)
    raise SerializationError(f"Unexpected value type at {{path}}")


@dataclass(frozen=True)
class GraphStoreCypherQueryV2Column:
    key: str
    value: Optional[GraphStoreCypherQueryV2Value]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2Column":
        raw = _expect_dict(obj, path)
        return GraphStoreCypherQueryV2Column(
            key=_expect_str(raw.get("key"), f"{{path}}.key"),
            value=_parse_value(raw.get("value"), f"{{path}}.value"),
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2Node:
    columns: List[GraphStoreCypherQueryV2Column]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2Node":
        raw = _expect_dict(obj, path)
        columns_raw = _expect_list(raw.get("columns"), f"{{path}}.columns")
        return GraphStoreCypherQueryV2Node(
            columns=[
                GraphStoreCypherQueryV2Column.from_dict(
                    item, f"{{path}}.columns[{{idx}}]"
                )
                for idx, item in enumerate(columns_raw)
            ]
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2Edge:
    cursor: Optional[str]
    node: GraphStoreCypherQueryV2Node

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2Edge":
        raw = _expect_dict(obj, path)
        cursor = (
            _expect_optional_str(raw.get("cursor"), f"{{path}}.cursor")
            if {str(cfg.edge_has_cursor)}
            else None
        )
        node = raw.get("node")
        if node is None:
            raise SerializationError(f"Missing {{path}}.node")
        return GraphStoreCypherQueryV2Edge(
            cursor=cursor,
            node=GraphStoreCypherQueryV2Node.from_dict(node, f"{{path}}.node"),
        )


@dataclass(frozen=True)
class GraphStoreCypherQueryV2Connection:
    page_info: PageInfo
    edges: List[GraphStoreCypherQueryV2Edge]
    version: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> "GraphStoreCypherQueryV2Connection":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get("pageInfo"), f"{{path}}.pageInfo")
        edges_raw = _expect_list(raw.get("edges"), f"{{path}}.edges")
        edges = [
            GraphStoreCypherQueryV2Edge.from_dict(item, f"{{path}}.edges[{{idx}}]")
            for idx, item in enumerate(edges_raw)
        ]
        version = _expect_str(raw.get("{cfg.connection_version_field}"), f"{{path}}.{cfg.connection_version_field}")
        return GraphStoreCypherQueryV2Connection(
            page_info=page_info,
            edges=edges,
            version=version,
        )


{"".join(parse_funcs)}
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
        repo_root / "python" / "atlassian" / "graph" / "gen" / "teamwork_graph_api.py"
    )
    output_py.parent.mkdir(parents=True, exist_ok=True)
    output_py.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {output_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
