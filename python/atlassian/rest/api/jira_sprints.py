from __future__ import annotations

from typing import Dict, Iterator, Optional, Set, Union

from ...canonical_models import JiraSprint
from ...errors import SerializationError
from ..client import JiraRestClient
from ..gen.jira_agile_api import SprintPage
from ..mappers.jira_sprints import map_sprint


def iter_board_sprints_via_rest(
    client: JiraRestClient,
    *,
    board_id: int,
    state: Optional[str] = None,
    page_size: int = 50,
) -> Iterator[JiraSprint]:
    """Iterate over sprints for a Jira Agile board.

    Args:
        client: JiraRestClient instance
        board_id: The ID of the Jira Agile board
        state: Optional filter by sprint state (future, active, closed)
        page_size: Number of sprints per page (default: 50)

    Yields:
        JiraSprint: Canonical sprint objects

    Raises:
        ValueError: If board_id is invalid or page_size is <= 0
        SerializationError: If pagination loops
    """
    if board_id is None or board_id <= 0:
        raise ValueError("board_id must be a positive integer")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    state_clean: Optional[str] = None
    if state is not None:
        state_clean = state.strip().lower()
        if state_clean not in ("future", "active", "closed"):
            raise ValueError("state must be one of: future, active, closed")

    start_at = 0
    seen_start_at: Set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError("Pagination startAt repeated; aborting to prevent infinite loop")
        seen_start_at.add(start_at)

        params: Dict[str, Union[int, str]] = {"startAt": start_at, "maxResults": page_size}
        if state_clean is not None:
            params["state"] = state_clean

        payload = client.get_json(
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params=params,
        )
        page = SprintPage.from_dict(payload, "data")
        values = page.values

        for item in values:
            yield map_sprint(sprint=item)

        has_is_last = isinstance(page.is_last, bool)
        if has_is_last and page.is_last:
            break

        if len(values) < page_size:
            break

        if len(values) == 0:
            if has_is_last and not page.is_last:
                raise SerializationError(
                    "Received empty page with isLast=false; cannot continue pagination"
                )
            break
        start_at += len(values)
