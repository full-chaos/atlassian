from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraUser, JiraWorklog
from ..gen.jira_api import UserDetails, Worklog


def _require_non_empty(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def _map_user(user: Optional[UserDetails], path: str) -> Optional[JiraUser]:
    if user is None:
        return None
    account_id = user.account_id
    display_name = user.display_name
    email = user.email_address
    return JiraUser(
        account_id=_require_non_empty(account_id, f"{path}.accountId"),
        display_name=_require_non_empty(display_name, f"{path}.displayName"),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
    )


def map_worklog(*, issue_key: str, worklog: Worklog) -> JiraWorklog:
    issue_key_clean = (issue_key or "").strip()
    if not issue_key_clean:
        raise ValueError("issue_key is required")
    if worklog is None:
        raise ValueError("worklog is required")

    worklog_id = _require_non_empty(worklog.id, "worklog.id")
    started_at = _require_non_empty(worklog.started, "worklog.started")
    created_at = _require_non_empty(worklog.created, "worklog.created")
    updated_at = _require_non_empty(worklog.updated, "worklog.updated")

    tss = worklog.time_spent_seconds
    if not isinstance(tss, int) or isinstance(tss, bool) or tss < 0:
        raise ValueError("worklog.timeSpentSeconds is required and must be >= 0")

    return JiraWorklog(
        issue_key=issue_key_clean,
        worklog_id=worklog_id,
        started_at=started_at,
        time_spent_seconds=tss,
        created_at=created_at,
        updated_at=updated_at,
        author=_map_user(worklog.author, "worklog.author"),
    )
