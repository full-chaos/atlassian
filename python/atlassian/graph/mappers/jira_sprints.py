from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraSprint
from ..gen import jira_sprints_api as api


def _require_non_empty(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def map_sprint(*, sprint: api.JiraSprintNode) -> JiraSprint:
    if sprint is None:
        raise ValueError("sprint is required")

    sprint_id = _require_non_empty(sprint.sprint_id, "sprint.sprintId")
    name = _require_non_empty(sprint.name, "sprint.name")
    state = _require_non_empty(sprint.state, "sprint.state")

    start_at = sprint.start_date.strip() if isinstance(sprint.start_date, str) and sprint.start_date.strip() else None
    end_at = sprint.end_date.strip() if isinstance(sprint.end_date, str) and sprint.end_date.strip() else None
    complete_at = (
        sprint.completion_date.strip()
        if isinstance(sprint.completion_date, str) and sprint.completion_date.strip()
        else None
    )

    return JiraSprint(
        id=sprint_id,
        name=name,
        state=state,
        start_at=start_at,
        end_at=end_at,
        complete_at=complete_at,
    )
