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
    sprint_type_name: str


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

    sprint_by_id_field = _field(query_def, "sprintById")
    if not sprint_by_id_field:
        raise RuntimeError(f"Missing required field {query_name}.sprintById")
    if not _arg(sprint_by_id_field, "id"):
        raise RuntimeError("Missing required arg sprintById.id")

    sprint_type_name, _, _ = _unwrap_named_type(sprint_by_id_field.get("type") or {})
    if not sprint_type_name:
        raise RuntimeError("Unable to resolve type of sprintById")
    sprint_def = _require_type(types, sprint_type_name)

    for field_name in ("sprintId", "name", "state", "startDate", "endDate", "completionDate"):
        _require_field(sprint_def, field_name, f"type {sprint_type_name}.fields")

    return _Config(sprint_type_name=sprint_type_name)


def _render_python(cfg: _Config) -> str:
    return f"""# Code generated by python/tools/generate_jira_sprint_models.py. DO NOT EDIT.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from atlassian.errors import SerializationError

# Schema type discovered during generation
SPRINT_TYPE_NAME = "{cfg.sprint_type_name}"

JIRA_SPRINT_BY_ID_QUERY = \"\"\"query JiraSprintById(
  $id: ID!
) {{
  sprintById(id: $id) {{
    sprintId
    name
    state
    startDate
    endDate
    completionDate
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
class JiraSprintNode:
    sprint_id: str
    name: Optional[str]
    state: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    completion_date: Optional[str]

    @staticmethod
    def from_dict(obj: Any, path: str) -> \"JiraSprintNode\":
        raw = _expect_dict(obj, path)
        return JiraSprintNode(
            sprint_id=_expect_str(raw.get(\"sprintId\"), f\"{path}.sprintId\"),
            name=_expect_optional_str(raw.get(\"name\"), f\"{path}.name\"),
            state=_expect_optional_str(raw.get(\"state\"), f\"{path}.state\"),
            start_date=_expect_optional_str(raw.get(\"startDate\"), f\"{path}.startDate\"),
            end_date=_expect_optional_str(raw.get(\"endDate\"), f\"{path}.endDate\"),
            completion_date=_expect_optional_str(raw.get(\"completionDate\"), f\"{path}.completionDate\"),
        )


def parse_jira_sprint_by_id(data: Any) -> JiraSprintNode:
    root = _expect_dict(data, \"data\")
    sprint = root.get(\"sprintById\")
    if sprint is None:
        raise SerializationError(\"Missing data.sprintById\")
    return JiraSprintNode.from_dict(sprint, \"data.sprintById\")
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

    out_path = repo_root / "python" / "atlassian" / "graph" / "gen" / "jira_sprints_api.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_python(cfg), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
