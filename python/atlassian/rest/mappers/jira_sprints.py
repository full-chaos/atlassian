from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraSprint
from ..gen.jira_agile_api import Sprint


def map_sprint(*, sprint: Sprint) -> JiraSprint:
    """Map a Jira Agile API Sprint to a canonical JiraSprint."""
    if sprint is None:
        raise ValueError("sprint is required")

    sprint_id = sprint.id
    if sprint_id is None:
        raise ValueError("sprint.id is required")

    name = sprint.name
    if name is None or not name.strip():
        raise ValueError("sprint.name is required")

    state = sprint.state
    if state is None or not state.strip():
        raise ValueError("sprint.state is required")

    start_at: Optional[str] = None
    if sprint.start_date is not None and sprint.start_date.strip():
        start_at = sprint.start_date.strip()

    end_at: Optional[str] = None
    if sprint.end_date is not None and sprint.end_date.strip():
        end_at = sprint.end_date.strip()

    complete_at: Optional[str] = None
    if sprint.complete_date is not None and sprint.complete_date.strip():
        complete_at = sprint.complete_date.strip()

    return JiraSprint(
        id=str(sprint_id),
        name=name.strip(),
        state=state.strip(),
        start_at=start_at,
        end_at=end_at,
        complete_at=complete_at,
    )
