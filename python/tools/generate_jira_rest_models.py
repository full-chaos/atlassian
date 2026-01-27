from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(str(path))
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI document must be a JSON object")
    return payload


def _ref_name(ref: str) -> str:
    prefix = "#/components/schemas/"
    if not isinstance(ref, str) or not ref.startswith(prefix):
        raise ValueError(f"Unsupported $ref: {ref!r}")
    return ref[len(prefix) :]


def _get_schema(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    schemas = doc.get("components", {}).get("schemas")
    if not isinstance(schemas, dict):
        raise ValueError("OpenAPI document missing components.schemas")
    schema = schemas.get(name)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema not found: {name}")
    return schema


def _get_operation_schema_ref(doc: Dict[str, Any], *, path: str, method: str) -> str:
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI document missing paths")
    raw_path = paths.get(path)
    if not isinstance(raw_path, dict):
        raise ValueError(f"OpenAPI path not found: {path}")
    op = raw_path.get(method.lower())
    if not isinstance(op, dict):
        raise ValueError(f"OpenAPI operation not found: {method.upper()} {path}")
    responses = op.get("responses")
    if not isinstance(responses, dict):
        raise ValueError(
            f"OpenAPI operation missing responses: {method.upper()} {path}"
        )
    resp = responses.get("200")
    if not isinstance(resp, dict):
        raise ValueError(
            f"OpenAPI operation missing 200 response: {method.upper()} {path}"
        )
    content = resp.get("content")
    if not isinstance(content, dict):
        raise ValueError(
            f"OpenAPI 200 response missing content: {method.upper()} {path}"
        )
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        raise ValueError(
            f"OpenAPI 200 response missing application/json content: {method.upper()} {path}"
        )
    schema = app_json.get("schema")
    if not isinstance(schema, dict):
        raise ValueError(
            f"OpenAPI 200 response missing schema: {method.upper()} {path}"
        )
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref:
        raise ValueError(
            f"OpenAPI 200 response schema is not a $ref: {method.upper()} {path}"
        )
    return ref


def _expect_property(
    schema: Dict[str, Any], prop: str, *, type_: Optional[str] = None
) -> Dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("Schema missing properties")
    raw = properties.get(prop)
    if not isinstance(raw, dict):
        raise ValueError(f"Schema missing property {prop!r}")
    if type_ is not None:
        found = raw.get("type")
        if found != type_:
            raise ValueError(
                f"Property {prop!r} expected type={type_!r}, got {found!r}"
            )
    return raw


def _property_ref(prop_schema: Dict[str, Any]) -> str:
    ref = prop_schema.get("$ref")
    if isinstance(ref, str) and ref:
        return ref
    all_of = prop_schema.get("allOf")
    if isinstance(all_of, list) and len(all_of) == 1 and isinstance(all_of[0], dict):
        inner = all_of[0].get("$ref")
        if isinstance(inner, str) and inner:
            return inner
    raise ValueError("Property schema does not contain a supported $ref/allOf")


def _generate(doc: Dict[str, Any]) -> str:
    page_projects_ref = _get_operation_schema_ref(
        doc, path="/rest/api/3/project/search", method="get"
    )
    search_results_ref = _get_operation_schema_ref(
        doc, path="/rest/api/3/search", method="get"
    )
    page_changelog_ref = _get_operation_schema_ref(
        doc, path="/rest/api/3/issue/{issueIdOrKey}/changelog", method="get"
    )
    page_worklogs_ref = _get_operation_schema_ref(
        doc, path="/rest/api/3/issue/{issueIdOrKey}/worklog", method="get"
    )
    page_versions_ref = _get_operation_schema_ref(
        doc, path="/rest/api/3/project/{projectIdOrKey}/version", method="get"
    )

    page_projects_name = _ref_name(page_projects_ref)
    search_results_name = _ref_name(search_results_ref)
    page_changelog_name = _ref_name(page_changelog_ref)
    page_worklogs_name = _ref_name(page_worklogs_ref)

    page_projects_schema = _get_schema(doc, page_projects_name)
    projects_items_ref = _property_ref(
        _expect_property(page_projects_schema, "values", type_="array")["items"]
    )
    project_name = _ref_name(projects_items_ref)

    search_results_schema = _get_schema(doc, search_results_name)
    issue_items_ref = _property_ref(
        _expect_property(search_results_schema, "issues", type_="array")["items"]
    )
    issue_name = _ref_name(issue_items_ref)

    page_changelog_schema = _get_schema(doc, page_changelog_name)
    changelog_items_ref = _property_ref(
        _expect_property(page_changelog_schema, "values", type_="array")["items"]
    )
    changelog_name = _ref_name(changelog_items_ref)

    changelog_schema = _get_schema(doc, changelog_name)
    author_ref = _property_ref(_expect_property(changelog_schema, "author"))
    user_details_name = _ref_name(author_ref)

    change_items_ref = _property_ref(
        _expect_property(changelog_schema, "items", type_="array")["items"]
    )
    change_details_name = _ref_name(change_items_ref)

    page_worklogs_schema = _get_schema(doc, page_worklogs_name)
    worklog_items_ref = _property_ref(
        _expect_property(page_worklogs_schema, "worklogs", type_="array")["items"]
    )
    worklog_name = _ref_name(worklog_items_ref)

    worklog_schema = _get_schema(doc, worklog_name)
    worklog_author_ref = _property_ref(_expect_property(worklog_schema, "author"))
    if _ref_name(worklog_author_ref) != user_details_name:
        raise ValueError(
            f"Worklog.author expected {user_details_name} but got {_ref_name(worklog_author_ref)}"
        )

    page_versions_name = _ref_name(page_versions_ref)
    page_versions_schema = _get_schema(doc, page_versions_name)
    version_items_ref = _property_ref(
        _expect_property(page_versions_schema, "values", type_="array")["items"]
    )
    version_name = _ref_name(version_items_ref)

    # Ensure the properties we rely on exist in the derived schemas.
    for prop in ("startAt", "maxResults", "total"):
        _expect_property(_get_schema(doc, page_worklogs_name), prop)
    for prop in ("key", "name", "projectTypeKey"):
        _expect_property(_get_schema(doc, project_name), prop)
    for prop in ("id", "key", "fields"):
        _expect_property(
            _get_schema(doc, issue_name), prop if prop != "fields" else "fields"
        )
    for prop in ("id", "created", "items"):
        _expect_property(_get_schema(doc, changelog_name), prop)
    for prop in ("field", "from", "to", "fromString", "toString"):
        _expect_property(_get_schema(doc, change_details_name), prop)
    for prop in ("accountId", "displayName", "emailAddress"):
        _expect_property(_get_schema(doc, user_details_name), prop)
    for prop in ("id", "started", "timeSpentSeconds", "created", "updated", "author"):
        _expect_property(_get_schema(doc, worklog_name), prop)
    for prop in ("id", "name", "projectId", "released"):
        _expect_property(_get_schema(doc, version_name), prop)
    for prop in ("startAt", "maxResults", "total", "values"):
        _expect_property(_get_schema(doc, page_versions_name), prop)

    # Deterministic output. Do not import this module from the generator.
    header = (
        "# Code generated by python/tools/generate_jira_rest_models.py. DO NOT EDIT.\n"
        "from __future__ import annotations\n\n"
        "from dataclasses import dataclass\n"
        "from typing import Any, Dict, List, Optional\n\n"
        "from atlassian.errors import SerializationError\n\n"
    )

    helpers = """\
def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise SerializationError(f"Expected object at {path}")
    return obj


def _expect_list(obj: Any, path: str) -> List[Any]:
    if not isinstance(obj, list):
        raise SerializationError(f"Expected list at {path}")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise SerializationError(f"Expected string at {path}")
    return obj


def _expect_bool(obj: Any, path: str) -> bool:
    if not isinstance(obj, bool):
        raise SerializationError(f"Expected boolean at {path}")
    return obj


def _expect_int(obj: Any, path: str) -> int:
    if isinstance(obj, bool) or not isinstance(obj, int):
        raise SerializationError(f"Expected integer at {path}")
    return obj


def _expect_obj(obj: Any, path: str) -> Dict[str, Any]:
    # Jira issue fields are modeled as a free-form object in the OpenAPI spec.
    return _expect_dict(obj, path)

"""

    models: List[str] = []

    # UserDetails
    models.append(
        f"""\
@dataclass(frozen=True)
class {user_details_name}:
    account_id: Optional[str]
    display_name: Optional[str]
    email_address: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{user_details_name}":
        raw = _expect_dict(obj, path)
        account_id: Optional[str] = None
        if raw.get("accountId") is not None:
            account_id = _expect_str(raw.get("accountId"), f"{{path}}.accountId")
        display_name: Optional[str] = None
        if raw.get("displayName") is not None:
            display_name = _expect_str(raw.get("displayName"), f"{{path}}.displayName")
        email_address: Optional[str] = None
        if raw.get("emailAddress") is not None:
            email_address = _expect_str(raw.get("emailAddress"), f"{{path}}.emailAddress")
        return {user_details_name}(
            account_id=account_id,
            display_name=display_name,
            email_address=email_address,
        )

"""
    )

    # Project
    models.append(
        f"""\
@dataclass(frozen=True)
class {project_name}:
    id: Optional[str]
    key: Optional[str]
    name: Optional[str]
    project_type_key: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{project_name}":
        raw = _expect_dict(obj, path)
        project_id: Optional[str] = None
        if raw.get("id") is not None:
            project_id = _expect_str(raw.get("id"), f"{{path}}.id")
        key: Optional[str] = None
        if raw.get("key") is not None:
            key = _expect_str(raw.get("key"), f"{{path}}.key")
        name: Optional[str] = None
        if raw.get("name") is not None:
            name = _expect_str(raw.get("name"), f"{{path}}.name")
        project_type_key: Optional[str] = None
        if raw.get("projectTypeKey") is not None:
            project_type_key = _expect_str(raw.get("projectTypeKey"), f"{{path}}.projectTypeKey")
        return {project_name}(
            id=project_id,
            key=key,
            name=name,
            project_type_key=project_type_key,
        )

"""
    )

    # PageBeanProject
    models.append(
        f"""\
@dataclass(frozen=True)
class {page_projects_name}:
    start_at: Optional[int]
    max_results: Optional[int]
    total: Optional[int]
    is_last: Optional[bool]
    values: List[{project_name}]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{page_projects_name}":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{{path}}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{{path}}.maxResults")
        total: Optional[int] = None
        if raw.get("total") is not None:
            total = _expect_int(raw.get("total"), f"{{path}}.total")
        is_last: Optional[bool] = None
        if raw.get("isLast") is not None:
            is_last = _expect_bool(raw.get("isLast"), f"{{path}}.isLast")
        values_raw = raw.get("values")
        values_list = _expect_list(values_raw, f"{{path}}.values") if values_raw is not None else []
        values = [
            {project_name}.from_dict(item, f"{{path}}.values[{{idx}}]")
            for idx, item in enumerate(values_list)
        ]
        return {page_projects_name}(
            start_at=start_at,
            max_results=max_results,
            total=total,
            is_last=is_last,
            values=values,
        )

"""
    )

    # IssueBean
    models.append(
        f"""\
@dataclass(frozen=True)
class {issue_name}:
    id: Optional[str]
    key: Optional[str]
    fields: Dict[str, Any]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{issue_name}":
        raw = _expect_dict(obj, path)
        issue_id: Optional[str] = None
        if raw.get("id") is not None:
            issue_id = _expect_str(raw.get("id"), f"{{path}}.id")
        key: Optional[str] = None
        if raw.get("key") is not None:
            key = _expect_str(raw.get("key"), f"{{path}}.key")
        fields_raw = raw.get("fields")
        fields = _expect_obj(fields_raw, f"{{path}}.fields") if fields_raw is not None else {{}}
        return {issue_name}(id=issue_id, key=key, fields=fields)

"""
    )

    # SearchResults
    models.append(
        f"""\
@dataclass(frozen=True)
class {search_results_name}:
    start_at: Optional[int]
    max_results: Optional[int]
    total: Optional[int]
    issues: List[{issue_name}]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{search_results_name}":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{{path}}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{{path}}.maxResults")
        total: Optional[int] = None
        if raw.get("total") is not None:
            total = _expect_int(raw.get("total"), f"{{path}}.total")
        issues_raw = raw.get("issues")
        issues_list = _expect_list(issues_raw, f"{{path}}.issues") if issues_raw is not None else []
        issues = [
            {issue_name}.from_dict(item, f"{{path}}.issues[{{idx}}]")
            for idx, item in enumerate(issues_list)
        ]
        return {search_results_name}(
            start_at=start_at,
            max_results=max_results,
            total=total,
            issues=issues,
        )

"""
    )

    # ChangeDetails
    models.append(
        f"""\
@dataclass(frozen=True)
class {change_details_name}:
    field: Optional[str]
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    from_string: Optional[str] = None
    to_string: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{change_details_name}":
        raw = _expect_dict(obj, path)
        field: Optional[str] = None
        if raw.get("field") is not None:
            field = _expect_str(raw.get("field"), f"{{path}}.field")
        from_value: Optional[str] = None
        if raw.get("from") is not None:
            from_value = _expect_str(raw.get("from"), f"{{path}}.from")
        to_value: Optional[str] = None
        if raw.get("to") is not None:
            to_value = _expect_str(raw.get("to"), f"{{path}}.to")
        from_string: Optional[str] = None
        if raw.get("fromString") is not None:
            from_string = _expect_str(raw.get("fromString"), f"{{path}}.fromString")
        to_string: Optional[str] = None
        if raw.get("toString") is not None:
            to_string = _expect_str(raw.get("toString"), f"{{path}}.toString")
        return {change_details_name}(
            field=field,
            from_value=from_value,
            to_value=to_value,
            from_string=from_string,
            to_string=to_string,
        )

"""
    )

    # Changelog
    models.append(
        f"""\
@dataclass(frozen=True)
class {changelog_name}:
    id: Optional[str]
    created: Optional[str]
    items: List[{change_details_name}]
    author: Optional[{user_details_name}] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{changelog_name}":
        raw = _expect_dict(obj, path)
        event_id: Optional[str] = None
        if raw.get("id") is not None:
            event_id = _expect_str(raw.get("id"), f"{{path}}.id")
        created: Optional[str] = None
        if raw.get("created") is not None:
            created = _expect_str(raw.get("created"), f"{{path}}.created")
        author: Optional[{user_details_name}] = None
        if raw.get("author") is not None:
            author = {user_details_name}.from_dict(raw.get("author"), f"{{path}}.author")
        items_raw = raw.get("items")
        items_list = _expect_list(items_raw, f"{{path}}.items") if items_raw is not None else []
        items = [
            {change_details_name}.from_dict(item, f"{{path}}.items[{{idx}}]")
            for idx, item in enumerate(items_list)
        ]
        return {changelog_name}(
            id=event_id,
            created=created,
            items=items,
            author=author,
        )

"""
    )

    # PageBeanChangelog
    models.append(
        f"""\
@dataclass(frozen=True)
class {page_changelog_name}:
    start_at: Optional[int]
    max_results: Optional[int]
    total: Optional[int]
    is_last: Optional[bool]
    values: List[{changelog_name}]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{page_changelog_name}":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{{path}}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{{path}}.maxResults")
        total: Optional[int] = None
        if raw.get("total") is not None:
            total = _expect_int(raw.get("total"), f"{{path}}.total")
        is_last: Optional[bool] = None
        if raw.get("isLast") is not None:
            is_last = _expect_bool(raw.get("isLast"), f"{{path}}.isLast")
        values_raw = raw.get("values")
        values_list = _expect_list(values_raw, f"{{path}}.values") if values_raw is not None else []
        values = [
            {changelog_name}.from_dict(item, f"{{path}}.values[{{idx}}]")
            for idx, item in enumerate(values_list)
        ]
        return {page_changelog_name}(
            start_at=start_at,
            max_results=max_results,
            total=total,
            is_last=is_last,
            values=values,
        )

"""
    )

    # Worklog
    models.append(
        f"""\
@dataclass(frozen=True)
class {worklog_name}:
    id: Optional[str]
    started: Optional[str]
    time_spent_seconds: Optional[int]
    created: Optional[str]
    updated: Optional[str]
    author: Optional[{user_details_name}] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{worklog_name}":
        raw = _expect_dict(obj, path)
        worklog_id: Optional[str] = None
        if raw.get("id") is not None:
            worklog_id = _expect_str(raw.get("id"), f"{{path}}.id")
        started: Optional[str] = None
        if raw.get("started") is not None:
            started = _expect_str(raw.get("started"), f"{{path}}.started")
        time_spent_seconds: Optional[int] = None
        if raw.get("timeSpentSeconds") is not None:
            time_spent_seconds = _expect_int(raw.get("timeSpentSeconds"), f"{{path}}.timeSpentSeconds")
        created: Optional[str] = None
        if raw.get("created") is not None:
            created = _expect_str(raw.get("created"), f"{{path}}.created")
        updated: Optional[str] = None
        if raw.get("updated") is not None:
            updated = _expect_str(raw.get("updated"), f"{{path}}.updated")
        author: Optional[{user_details_name}] = None
        if raw.get("author") is not None:
            author = {user_details_name}.from_dict(raw.get("author"), f"{{path}}.author")
        return {worklog_name}(
            id=worklog_id,
            started=started,
            time_spent_seconds=time_spent_seconds,
            created=created,
            updated=updated,
            author=author,
        )

"""
    )

    # PageOfWorklogs
    models.append(
        f"""\
@dataclass(frozen=True)
class {page_worklogs_name}:
    start_at: Optional[int]
    max_results: Optional[int]
    total: Optional[int]
    worklogs: List[{worklog_name}]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{page_worklogs_name}":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{{path}}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{{path}}.maxResults")
        total: Optional[int] = None
        if raw.get("total") is not None:
            total = _expect_int(raw.get("total"), f"{{path}}.total")
        worklogs_raw = raw.get("worklogs")
        worklogs_list = _expect_list(worklogs_raw, f"{{path}}.worklogs") if worklogs_raw is not None else []
        worklogs = [
            {worklog_name}.from_dict(item, f"{{path}}.worklogs[{{idx}}]")
            for idx, item in enumerate(worklogs_list)
        ]
        return {page_worklogs_name}(
            start_at=start_at,
            max_results=max_results,
            total=total,
            worklogs=worklogs,
        )

"""
    )

    # PageBeanVersion
    models.append(
        f"""\
@dataclass(frozen=True)
class {page_versions_name}:
    start_at: Optional[int]
    max_results: Optional[int]
    total: Optional[int]
    is_last: Optional[bool]
    values: List[{version_name}]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{page_versions_name}":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{{path}}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{{path}}.maxResults")
        total: Optional[int] = None
        if raw.get("total") is not None:
            total = _expect_int(raw.get("total"), f"{{path}}.total")
        is_last: Optional[bool] = None
        if raw.get("isLast") is not None:
            is_last = _expect_bool(raw.get("isLast"), f"{{path}}.isLast")
        values_raw = raw.get("values")
        values_list = _expect_list(values_raw, f"{{path}}.values") if values_raw is not None else []
        values = [
            {version_name}.from_dict(item, f"{{path}}.values[{{idx}}]")
            for idx, item in enumerate(values_list)
        ]
        return {page_versions_name}(
            start_at=start_at,
            max_results=max_results,
            total=total,
            is_last=is_last,
            values=values,
        )

"""
    )

    # Version
    models.append(
        f"""\
@dataclass(frozen=True)
class {version_name}:
    id: Optional[str]
    name: Optional[str]
    project_id: Optional[int] = None
    released: Optional[bool] = None
    release_date: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "{version_name}":
        raw = _expect_dict(obj, path)
        version_id: Optional[str] = None
        if raw.get("id") is not None:
            version_id = _expect_str(raw.get("id"), f"{{path}}.id")
        name: Optional[str] = None
        if raw.get("name") is not None:
            name = _expect_str(raw.get("name"), f"{{path}}.name")
        project_id: Optional[int] = None
        if raw.get("projectId") is not None:
            project_id = _expect_int(raw.get("projectId"), f"{{path}}.projectId")
        released: Optional[bool] = None
        if raw.get("released") is not None:
            released = _expect_bool(raw.get("released"), f"{{path}}.released")
        release_date: Optional[str] = None
        if raw.get("releaseDate") is not None:
            # Versions can have date-only strings "2010-07-06"
            release_date = _expect_str(raw.get("releaseDate"), f"{{path}}.releaseDate")
        return {version_name}(
            id=version_id,
            name=name,
            project_id=project_id,
            released=released,
            release_date=release_date,
        )

"""
    )

    return header + helpers + "\n".join(models)


@dataclass(frozen=True)
class Args:
    spec: Path
    out: Path


def _parse_args() -> Args:
    repo_root = Path(__file__).resolve().parents[2]
    default_spec = repo_root / "openapi" / "jira-rest.swagger-v3.json"
    default_out = repo_root / "python" / "atlassian" / "rest" / "gen" / "jira_api.py"

    parser = argparse.ArgumentParser(
        description="Generate minimal Jira REST API models from the Jira Cloud OpenAPI spec."
    )
    parser.add_argument(
        "--spec", default=str(default_spec), help="Path to swagger-v3 JSON"
    )
    parser.add_argument("--out", default=str(default_out), help="Output .py file path")
    ns = parser.parse_args()
    return Args(spec=Path(ns.spec), out=Path(ns.out))


def main() -> int:
    args = _parse_args()
    doc = _read_json(args.spec)
    rendered = _generate(doc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
