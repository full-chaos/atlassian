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
    issue_type_name: str
    user_type_name: str


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

    issue_type_field = _require_field(issue_def, "issueType", f"type {issue_type_name}.fields")
    issue_type_def = _require_type(types, _unwrap_named_type(issue_type_field.get("type") or {})[0] or "")
    _require_field(issue_type_def, "name", f"type {issue_type_def.get('name')}.fields")

    status_field = _require_field(issue_def, "status", f"type {issue_type_name}.fields")
    status_def = _require_type(types, _unwrap_named_type(status_field.get("type") or {})[0] or "")
    _require_field(status_def, "name", f"type {status_def.get('name')}.fields")

    project_field = _require_field(issue_def, "projectField", f"type {issue_type_name}.fields")
    project_field_def = _require_type(types, _unwrap_named_type(project_field.get("type") or {})[0] or "")
    project_field_project = _require_field(project_field_def, "project", f"type {project_field_def.get('name')}.fields")
    project_def = _require_type(types, _unwrap_named_type(project_field_project.get("type") or {})[0] or "")
    _require_field(project_def, "key", f"type {project_def.get('name')}.fields")
    _require_field(project_def, "cloudId", f"type {project_def.get('name')}.fields")

    for dt_field in ("createdField", "updatedField", "resolutionDateField"):
        dt_def = _require_field(issue_def, dt_field, f"type {issue_type_name}.fields")
        dt_type = _require_type(types, _unwrap_named_type(dt_def.get("type") or {})[0] or "")
        _require_field(dt_type, "dateTime", f"type {dt_type.get('name')}.fields")

    assignee_field = _require_field(issue_def, "assigneeField", f"type {issue_type_name}.fields")
    assignee_def = _require_type(types, _unwrap_named_type(assignee_field.get("type") or {})[0] or "")
    _require_field(assignee_def, "user", f"type {assignee_def.get('name')}.fields")

    reporter_field = _require_field(issue_def, "reporter", f"type {issue_type_name}.fields")
    user_type_name, _, _ = _unwrap_named_type(reporter_field.get("type") or {})
    if not user_type_name:
        raise RuntimeError("Unable to resolve reporter user type")

    user_def = _require_type(types, user_type_name)
    _require_field(user_def, "accountId", f"type {user_type_name}.fields")
    _require_field(user_def, "name", f"type {user_type_name}.fields")

    return _Config(issue_type_name=issue_type_name, user_type_name=user_type_name)


def _render_python(cfg: _Config) -> str:
    return f"""# Code generated by python/tools/generate_jira_issue_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from atlassian.errors import SerializationError

# Schema types discovered during generation
ISSUE_TYPE_NAME = "{cfg.issue_type_name}"
USER_TYPE_NAME = "{cfg.user_type_name}"

JIRA_ISSUE_BY_KEY_QUERY = \"\"\"query JiraIssueByKey(
  $cloudId: ID!,
  $key: String!
) {{
  issueByKey(key: $key, cloudId: $cloudId) {{
    key
    issueType {{ name }}
    status {{ name }}
    projectField {{
      project {{ key cloudId }}
    }}
    createdField {{ dateTime }}
    updatedField {{ dateTime }}
    resolutionDateField {{ dateTime }}
    assigneeField {{
      user {{ accountId name }}
    }}
    reporter {{ accountId name }}
  }}
}}
\"\"\"


def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise SerializationError(f\"Expected object at {path}\")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise SerializationError(f\"Expected string at {path}\")
    return obj


def _expect_optional_str(obj: Any, path: str) -> Optional[str]:
    if obj is None:
        return None
    if not isinstance(obj, str):
        raise SerializationError(f\"Expected string at {path}\")
    if not obj:
        raise SerializationError(f\"Expected non-empty string at {path}\")
    return obj


@dataclass(frozen=True)
class JiraUser:
    account_id: str
    name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraUser\":
        raw = _expect_dict(obj, path)
        return JiraUser(
            account_id=_expect_str(raw.get(\"accountId\"), f\"{path}.accountId\"),
            name=_expect_str(raw.get(\"name\"), f\"{path}.name\"),
        )


@dataclass(frozen=True)
class JiraIssueType:
    name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraIssueType\":
        raw = _expect_dict(obj, path)
        return JiraIssueType(name=_expect_str(raw.get(\"name\"), f\"{path}.name\"))


@dataclass(frozen=True)
class JiraStatus:
    name: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraStatus\":
        raw = _expect_dict(obj, path)
        return JiraStatus(name=_expect_str(raw.get(\"name\"), f\"{path}.name\"))


@dataclass(frozen=True)
class JiraProject:
    key: str
    cloud_id: str

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraProject\":
        raw = _expect_dict(obj, path)
        return JiraProject(
            key=_expect_str(raw.get(\"key\"), f\"{path}.key\"),
            cloud_id=_expect_str(raw.get(\"cloudId\"), f\"{path}.cloudId\"),
        )


@dataclass(frozen=True)
class JiraProjectField:
    project: JiraProject

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraProjectField\":
        raw = _expect_dict(obj, path)
        return JiraProjectField(
            project=JiraProject.from_dict(raw.get(\"project\"), f\"{path}.project\"),
        )


@dataclass(frozen=True)
class JiraDateTimePickerField:
    date_time: Optional[str]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraDateTimePickerField\":
        raw = _expect_dict(obj, path)
        return JiraDateTimePickerField(
            date_time=_expect_optional_str(raw.get(\"dateTime\"), f\"{path}.dateTime\")
        )


@dataclass(frozen=True)
class JiraSingleSelectUserPickerField:
    user: Optional[JiraUser]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraSingleSelectUserPickerField\":
        raw = _expect_dict(obj, path)
        user_raw = raw.get(\"user\")
        user = JiraUser.from_dict(user_raw, f\"{path}.user\") if user_raw is not None else None
        return JiraSingleSelectUserPickerField(user=user)


@dataclass(frozen=True)
class JiraIssueNode:
    key: str
    issue_type: JiraIssueType
    status: JiraStatus
    project_field: JiraProjectField
    created_field: JiraDateTimePickerField
    updated_field: JiraDateTimePickerField
    resolution_date_field: Optional[JiraDateTimePickerField]
    assignee_field: Optional[JiraSingleSelectUserPickerField]
    reporter: Optional[JiraUser]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraIssueNode\":
        raw = _expect_dict(obj, path)
        resolution_raw = raw.get(\"resolutionDateField\")
        assignee_raw = raw.get(\"assigneeField\")
        reporter_raw = raw.get(\"reporter\")
        return JiraIssueNode(
            key=_expect_str(raw.get(\"key\"), f\"{path}.key\"),
            issue_type=JiraIssueType.from_dict(raw.get(\"issueType\"), f\"{path}.issueType\"),
            status=JiraStatus.from_dict(raw.get(\"status\"), f\"{path}.status\"),
            project_field=JiraProjectField.from_dict(raw.get(\"projectField\"), f\"{path}.projectField\"),
            created_field=JiraDateTimePickerField.from_dict(raw.get(\"createdField\"), f\"{path}.createdField\"),
            updated_field=JiraDateTimePickerField.from_dict(raw.get(\"updatedField\"), f\"{path}.updatedField\"),
            resolution_date_field=JiraDateTimePickerField.from_dict(resolution_raw, f\"{path}.resolutionDateField\")
            if resolution_raw is not None
            else None,
            assignee_field=JiraSingleSelectUserPickerField.from_dict(assignee_raw, f\"{path}.assigneeField\")
            if assignee_raw is not None
            else None,
            reporter=JiraUser.from_dict(reporter_raw, f\"{path}.reporter\") if reporter_raw is not None else None,
        )


def parse_jira_issue_by_key(data: Any) -> JiraIssueNode:
    root = _expect_dict(data, \"data\")
    issue = root.get(\"issueByKey\")
    if issue is None:
        raise SerializationError(\"Missing data.issueByKey\")
    return JiraIssueNode.from_dict(issue, \"data.issueByKey\")
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

    out_path = repo_root / "python" / "atlassian" / "graph" / "gen" / "jira_issues_api.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
