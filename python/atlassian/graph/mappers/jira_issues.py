from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraIssue, JiraUser
from ..gen import jira_issues_api as api


def _require_non_empty(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def _map_user(user: Optional[api.JiraUser], path: str) -> Optional[JiraUser]:
    if user is None:
        return None
    account_id = _require_non_empty(user.account_id, f"{path}.accountId")
    display_name = _require_non_empty(user.name, f"{path}.name")
    return JiraUser(account_id=account_id, display_name=display_name, email=None)


def map_issue(*, cloud_id: str, issue: api.JiraIssueNode) -> JiraIssue:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if issue is None:
        raise ValueError("issue is required")

    issue_key = _require_non_empty(issue.key, "issue.key")
    issue_type = _require_non_empty(issue.issue_type.name, "issue.issueType.name")
    status = _require_non_empty(issue.status.name, "issue.status.name")

    project = issue.project_field.project
    project_key = _require_non_empty(project.key, "issue.projectField.project.key")
    project_cloud_id = _require_non_empty(project.cloud_id, "issue.projectField.project.cloudId")
    if project_cloud_id != cloud_id_clean:
        raise ValueError("issue.projectField.project.cloudId does not match cloud_id")

    created_at = _require_non_empty(issue.created_field.date_time, "issue.createdField.dateTime")
    updated_at = _require_non_empty(issue.updated_field.date_time, "issue.updatedField.dateTime")

    resolved_at = None
    if issue.resolution_date_field is not None and issue.resolution_date_field.date_time:
        resolved_at = issue.resolution_date_field.date_time.strip()

    assignee_user = (
        issue.assignee_field.user if issue.assignee_field is not None else None
    )
    reporter_user = issue.reporter

    return JiraIssue(
        cloud_id=project_cloud_id,
        key=issue_key,
        project_key=project_key,
        issue_type=issue_type,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        resolved_at=resolved_at,
        assignee=_map_user(assignee_user, "issue.assigneeField.user"),
        reporter=_map_user(reporter_user, "issue.reporter"),
        labels=[],
        components=[],
        story_points=None,
        sprint_ids=[],
    )
