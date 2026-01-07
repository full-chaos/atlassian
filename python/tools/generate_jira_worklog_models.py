from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    pageinfo_has_end_cursor: bool
    edge_has_cursor: bool


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


def _require_field(type_def: Dict[str, Any], name: str, path: str) -> Dict[str, Any]:
    found = _field(type_def, name)
    if not found:
        raise RuntimeError(f"Missing required field {path}.{name}")
    return found


def _require_type(types: Dict[str, Dict[str, Any]], name: str) -> Dict[str, Any]:
    type_def = types.get(name)
    if not type_def:
        raise RuntimeError(f"Missing type definition: {name}")
    return type_def


def _discover_config(schema: Dict[str, Any]) -> _Config:
    types = _types_map(schema)

    query_type = schema.get("queryType")
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    if not isinstance(query_name, str) or not query_name:
        raise RuntimeError("Introspection JSON missing __schema.queryType.name")
    query_def = _require_type(types, query_name)

    issue_by_key_field = _field(query_def, "issueByKey")
    if not issue_by_key_field:
        raise RuntimeError(f"Missing required field {query_name}.issueByKey")
    for arg_name in ("key", "cloudId"):
        if not _arg(issue_by_key_field, arg_name):
            raise RuntimeError(f"Missing required arg issueByKey.{arg_name}")

    issue_type_name, _, _ = _unwrap_named_type(issue_by_key_field.get("type") or {})
    if not issue_type_name:
        raise RuntimeError("Unable to resolve type of issueByKey")
    issue_def = _require_type(types, issue_type_name)

    worklogs_field = _require_field(issue_def, "worklogs", f"type {issue_type_name}.fields")
    for arg_name in ("first", "after"):
        if not _arg(worklogs_field, arg_name):
            raise RuntimeError(f"Missing required arg issue.worklogs.{arg_name}")

    worklogs_conn_name, _, _ = _unwrap_named_type(worklogs_field.get("type") or {})
    if not worklogs_conn_name:
        raise RuntimeError("Unable to resolve worklogs connection type")
    worklogs_conn_def = _require_type(types, worklogs_conn_name)

    pageinfo_field = _require_field(worklogs_conn_def, "pageInfo", f"type {worklogs_conn_name}.fields")
    edges_field = _require_field(worklogs_conn_def, "edges", f"type {worklogs_conn_name}.fields")

    pageinfo_name, _, _ = _unwrap_named_type(pageinfo_field.get("type") or {})
    pageinfo_def = _require_type(types, pageinfo_name or "")
    _require_field(pageinfo_def, "hasNextPage", f"type {pageinfo_name}.fields")
    pageinfo_has_end_cursor = _field(pageinfo_def, "endCursor") is not None

    edges_name, _, _ = _unwrap_named_type(edges_field.get("type") or {})
    edges_def = _require_type(types, edges_name or "")
    edge_has_cursor = _field(edges_def, "cursor") is not None
    node_field = _require_field(edges_def, "node", f"type {edges_name}.fields")
    node_name, _, _ = _unwrap_named_type(node_field.get("type") or {})
    worklog_def = _require_type(types, node_name or "")

    _require_field(worklog_def, "worklogId", f"type {node_name}.fields")
    _require_field(worklog_def, "author", f"type {node_name}.fields")
    time_spent_field = _require_field(worklog_def, "timeSpent", f"type {node_name}.fields")
    _require_field(worklog_def, "created", f"type {node_name}.fields")
    _require_field(worklog_def, "updated", f"type {node_name}.fields")
    _require_field(worklog_def, "startDate", f"type {node_name}.fields")

    estimate_name, _, _ = _unwrap_named_type(time_spent_field.get("type") or {})
    estimate_def = _require_type(types, estimate_name or "")
    _require_field(estimate_def, "timeInSeconds", f"type {estimate_name}.fields")

    user_def = _require_type(types, "User")
    _require_field(user_def, "accountId", "type User.fields")
    _require_field(user_def, "name", "type User.fields")

    return _Config(
        pageinfo_has_end_cursor=pageinfo_has_end_cursor,
        edge_has_cursor=edge_has_cursor,
    )


def _render_python(cfg: _Config) -> str:
    return f"""# Code generated by python/tools/generate_jira_worklog_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from atlassian.errors import SerializationError

PAGEINFO_HAS_END_CURSOR = {str(cfg.pageinfo_has_end_cursor)}
WORKLOGS_EDGE_HAS_CURSOR = {str(cfg.edge_has_cursor)}

JIRA_ISSUE_WORKLOGS_PAGE_QUERY = \"\"\"query JiraIssueWorklogsPage(
  $cloudId: ID!,
  $key: String!,
  $first: Int!,
  $after: String
) {{
  issue: issueByKey(key: $key, cloudId: $cloudId) {{
    worklogs(first: $first, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      edges {{
        cursor
        node {{
          worklogId
          author {{ accountId name }}
          timeSpent {{ timeInSeconds }}
          created
          updated
          startDate
        }}
      }}
    }}
  }}
}}
\"\"\"


def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise SerializationError(f\"Expected object at {{path}}\")
    return obj


def _expect_list(obj: Any, path: str) -> List[Any]:
    if not isinstance(obj, list):
        raise SerializationError(f\"Expected list at {{path}}\")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise SerializationError(f\"Expected string at {{path}}\")
    return obj


def _expect_optional_str(obj: Any, path: str) -> Optional[str]:
    if obj is None:
        return None
    if not isinstance(obj, str):
        raise SerializationError(f\"Expected string at {{path}}\")
    if not obj:
        raise SerializationError(f\"Expected non-empty string at {{path}}\")
    return obj


def _expect_int(obj: Any, path: str) -> int:
    if not isinstance(obj, int) or isinstance(obj, bool):
        raise SerializationError(f\"Expected integer at {{path}}\")
    return obj


@dataclass(frozen=True)
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"PageInfo\":
        raw = _expect_dict(obj, path)
        has_next = raw.get(\"hasNextPage\")
        if not isinstance(has_next, bool):
            raise SerializationError(f\"Expected boolean at {{path}}.hasNextPage\")
        end_cursor: Optional[str] = None
        if PAGEINFO_HAS_END_CURSOR:
            value = raw.get(\"endCursor\")
            if value is not None:
                end_cursor = _expect_str(value, f\"{{path}}.endCursor\")
        return PageInfo(has_next_page=has_next, end_cursor=end_cursor)


@dataclass(frozen=True)
class JiraUser:
    account_id: str
    name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraUser\":
        raw = _expect_dict(obj, path)
        return JiraUser(
            account_id=_expect_str(raw.get(\"accountId\"), f\"{{path}}.accountId\"),
            name=_expect_str(raw.get(\"name\"), f\"{{path}}.name\"),
        )


@dataclass(frozen=True)
class JiraEstimate:
    time_in_seconds: Optional[int]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraEstimate\":
        raw = _expect_dict(obj, path)
        value = raw.get(\"timeInSeconds\")
        if value is None:
            return JiraEstimate(time_in_seconds=None)
        return JiraEstimate(time_in_seconds=_expect_int(value, f\"{{path}}.timeInSeconds\"))


@dataclass(frozen=True)
class JiraWorklogNode:
    worklog_id: str
    author: Optional[JiraUser]
    time_spent: JiraEstimate
    created: str
    updated: Optional[str]
    started: Optional[str]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraWorklogNode\":
        raw = _expect_dict(obj, path)
        author_raw = raw.get(\"author\")
        return JiraWorklogNode(
            worklog_id=_expect_str(raw.get(\"worklogId\"), f\"{{path}}.worklogId\"),
            author=JiraUser.from_dict(author_raw, f\"{{path}}.author\") if author_raw is not None else None,
            time_spent=JiraEstimate.from_dict(raw.get(\"timeSpent\"), f\"{{path}}.timeSpent\"),
            created=_expect_str(raw.get(\"created\"), f\"{{path}}.created\"),
            updated=_expect_optional_str(raw.get(\"updated\"), f\"{{path}}.updated\"),
            started=_expect_optional_str(raw.get(\"startDate\"), f\"{{path}}.startDate\"),
        )


@dataclass(frozen=True)
class JiraWorklogEdge:
    cursor: Optional[str]
    node: JiraWorklogNode

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraWorklogEdge\":
        raw = _expect_dict(obj, path)
        cursor: Optional[str] = None
        if WORKLOGS_EDGE_HAS_CURSOR:
            value = raw.get(\"cursor\")
            if value is not None:
                cursor = _expect_str(value, f\"{{path}}.cursor\")
        node = JiraWorklogNode.from_dict(raw.get(\"node\"), f\"{{path}}.node\")
        return JiraWorklogEdge(cursor=cursor, node=node)


@dataclass(frozen=True)
class JiraWorklogConnection:
    page_info: PageInfo
    edges: List[JiraWorklogEdge]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraWorklogConnection\":
        raw = _expect_dict(obj, path)
        page_info = PageInfo.from_dict(raw.get(\"pageInfo\"), f\"{{path}}.pageInfo\")
        edges_list = _expect_list(raw.get(\"edges\"), f\"{{path}}.edges\")
        edges = [
            JiraWorklogEdge.from_dict(item, f\"{{path}}.edges[{{idx}}]\")
            for idx, item in enumerate(edges_list)
        ]
        return JiraWorklogConnection(page_info=page_info, edges=edges)


def parse_issue_worklogs_page(data: Any) -> JiraWorklogConnection:
    root = _expect_dict(data, \"data\")
    issue = root.get(\"issue\")
    if issue is None:
        raise SerializationError(\"Missing data.issue\")
    issue_obj = _expect_dict(issue, \"data.issue\")
    worklogs = issue_obj.get(\"worklogs\")
    if worklogs is None:
        raise SerializationError(\"Missing data.issue.worklogs\")
    return JiraWorklogConnection.from_dict(worklogs, \"data.issue.worklogs\")
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    token_file = Path(os.getenv("ATLASSIAN_OAUTH_TOKEN_FILE", repo_root / "oauth_tokens.txt"))
    _load_env_file(token_file)

    schema_path = repo_root / "graphql" / "schema.introspection.json"
    if not schema_path.exists():
        base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
        if not base_url and (
            os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN") or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
        ):
            base_url = "https://api.atlassian.com"
        if not base_url:
            raise RuntimeError(f"Missing {schema_path} and ATLASSIAN_GQL_BASE_URL not set")
        auth = _build_auth_from_env()
        if auth is None:
            raise RuntimeError("No credentials available in env vars to fetch schema")
        fetch_schema_introspection(
            base_url=base_url,
            auth=auth,
            output_dir=str(schema_path.parent),
            experimental_apis=_env_experimental_apis(),
        )

    schema = _load_introspection(schema_path)
    cfg = _discover_config(schema)

    out_path = repo_root / "python" / "atlassian" / "graph" / "gen" / "jira_worklogs_api.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
