from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraUser, JiraWorklog
from ..gen import jira_worklogs_api as api


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


def map_worklog(*, issue_key: str, worklog: api.JiraWorklogNode) -> JiraWorklog:
    issue_key_clean = (issue_key or "").strip()
    if not issue_key_clean:
        raise ValueError("issue_key is required")
    if worklog is None:
        raise ValueError("worklog is required")

    worklog_id = _require_non_empty(worklog.worklog_id, "worklog.worklogId")
    started_at = _require_non_empty(worklog.started, "worklog.startDate")
    created_at = _require_non_empty(worklog.created, "worklog.created")
    updated_at = _require_non_empty(worklog.updated, "worklog.updated")

    time_spent = worklog.time_spent.time_in_seconds
    if time_spent is None:
        raise ValueError("worklog.timeSpent.timeInSeconds is required")
    if not isinstance(time_spent, int) or isinstance(time_spent, bool) or time_spent < 0:
        raise ValueError("worklog.timeSpent.timeInSeconds must be >= 0")

    return JiraWorklog(
        issue_key=issue_key_clean,
        worklog_id=worklog_id,
        started_at=started_at,
        time_spent_seconds=time_spent,
        created_at=created_at,
        updated_at=updated_at,
        author=_map_user(worklog.author, "worklog.author"),
    )
