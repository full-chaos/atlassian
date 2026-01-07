from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...canonical_models import JiraIssue, JiraUser
from ..gen.jira_api import IssueBean


def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"Expected object at {path}")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise ValueError(f"Expected string at {path}")
    value = obj.strip()
    if not value:
        raise ValueError(f"Expected non-empty string at {path}")
    return value


def _expect_list(obj: Any, path: str) -> List[Any]:
    if not isinstance(obj, list):
        raise ValueError(f"Expected list at {path}")
    return obj


def _maybe_user(obj: Any, path: str) -> Optional[JiraUser]:
    if obj is None:
        return None
    raw = _expect_dict(obj, path)
    account_id = raw.get("accountId")
    display_name = raw.get("displayName")
    email = raw.get("emailAddress")
    email_value: Optional[str] = None
    if email is not None:
        if not isinstance(email, str):
            raise ValueError(f"Expected string at {path}.emailAddress")
        if email.strip():
            email_value = email.strip()
    return JiraUser(
        account_id=_expect_str(account_id, f"{path}.accountId"),
        display_name=_expect_str(display_name, f"{path}.displayName"),
        email=email_value,
    )


def _parse_story_points(fields: Dict[str, Any], field_name: Optional[str]) -> Optional[float]:
    if not field_name:
        return None
    field_key = field_name.strip()
    if not field_key:
        raise ValueError("story_points_field must be non-empty when provided")
    raw = fields.get(field_key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"issue.fields.{field_key} must be a number when present")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"issue.fields.{field_key} must be a number when present") from exc
    raise ValueError(f"issue.fields.{field_key} must be a number when present")


def _coerce_sprint_id(value: Any, path: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{path} must be a string or integer")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        raise ValueError(f"{path} must be an integer")
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{path} must be non-empty")
        return cleaned
    raise ValueError(f"{path} must be a string or integer")


def _parse_sprint_ids(fields: Dict[str, Any], field_name: Optional[str]) -> List[str]:
    if not field_name:
        return []
    field_key = field_name.strip()
    if not field_key:
        raise ValueError("sprint_ids_field must be non-empty when provided")
    raw = fields.get(field_key)
    if raw is None:
        return []
    items = _expect_list(raw, f"issue.fields.{field_key}")
    out: List[str] = []
    for idx, item in enumerate(items):
        path = f"issue.fields.{field_key}[{idx}]"
        if isinstance(item, dict):
            sprint_id = item.get("id")
            if sprint_id is None:
                raise ValueError(f"{path}.id is required")
            out.append(_coerce_sprint_id(sprint_id, f"{path}.id"))
        else:
            out.append(_coerce_sprint_id(item, path))
    return out


def map_issue(
    *,
    cloud_id: str,
    issue: IssueBean,
    story_points_field: Optional[str] = None,
    sprint_ids_field: Optional[str] = None,
) -> JiraIssue:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if issue is None:
        raise ValueError("issue is required")

    issue_key = _expect_str(issue.key, "issue.key")
    fields = _expect_dict(issue.fields, "issue.fields")

    project = _expect_dict(fields.get("project"), "issue.fields.project")
    project_key = _expect_str(project.get("key"), "issue.fields.project.key")

    issuetype = _expect_dict(fields.get("issuetype"), "issue.fields.issuetype")
    issue_type = _expect_str(issuetype.get("name"), "issue.fields.issuetype.name")

    status_obj = _expect_dict(fields.get("status"), "issue.fields.status")
    status = _expect_str(status_obj.get("name"), "issue.fields.status.name")

    created_at = _expect_str(fields.get("created"), "issue.fields.created")
    updated_at = _expect_str(fields.get("updated"), "issue.fields.updated")

    resolved_at: Optional[str] = None
    resolutiondate = fields.get("resolutiondate")
    if resolutiondate is not None:
        if not isinstance(resolutiondate, str):
            raise ValueError("issue.fields.resolutiondate must be a string when present")
        if resolutiondate.strip():
            resolved_at = resolutiondate.strip()

    labels: List[str] = []
    raw_labels = fields.get("labels")
    if raw_labels is not None:
        for idx, item in enumerate(_expect_list(raw_labels, "issue.fields.labels")):
            labels.append(_expect_str(item, f"issue.fields.labels[{idx}]"))

    components: List[str] = []
    raw_components = fields.get("components")
    if raw_components is not None:
        for idx, comp in enumerate(_expect_list(raw_components, "issue.fields.components")):
            comp_obj = _expect_dict(comp, f"issue.fields.components[{idx}]")
            components.append(_expect_str(comp_obj.get("name"), f"issue.fields.components[{idx}].name"))

    assignee = _maybe_user(fields.get("assignee"), "issue.fields.assignee")
    reporter = _maybe_user(fields.get("reporter"), "issue.fields.reporter")

    story_points = _parse_story_points(fields, story_points_field)
    sprint_ids = _parse_sprint_ids(fields, sprint_ids_field)

    return JiraIssue(
        cloud_id=cloud_id_clean,
        key=issue_key,
        project_key=project_key,
        issue_type=issue_type,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        resolved_at=resolved_at,
        assignee=assignee,
        reporter=reporter,
        labels=labels,
        components=components,
        story_points=story_points,
        sprint_ids=sprint_ids,
    )
