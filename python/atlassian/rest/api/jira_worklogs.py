from __future__ import annotations

from typing import Iterator

from ...canonical_models import JiraWorklog
from ...errors import SerializationError
from ..client import JiraRestClient
from ..gen import jira_api as api
from ..mappers.jira_worklogs import map_worklog


def iter_issue_worklogs_via_rest(
    client: JiraRestClient,
    *,
    issue_key: str,
    page_size: int = 100,
) -> Iterator[JiraWorklog]:
    issue_key_clean = (issue_key or "").strip()
    if not issue_key_clean:
        raise ValueError("issue_key is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    start_at = 0
    seen_start_at: set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError("Pagination startAt repeated; aborting to prevent infinite loop")
        seen_start_at.add(start_at)

        payload = client.get_json(
            f"/rest/api/3/issue/{issue_key_clean}/worklog",
            params={"startAt": start_at, "maxResults": page_size},
        )
        page = api.PageOfWorklogs.from_dict(payload, "data")
        worklogs = page.worklogs

        for wl in worklogs:
            yield map_worklog(issue_key=issue_key_clean, worklog=wl)

        has_total = isinstance(page.total, int) and page.total >= 0
        if has_total:
            if start_at + len(worklogs) >= page.total:
                break
        else:
            if len(worklogs) < page_size:
                break

        if len(worklogs) == 0:
            break
        start_at += len(worklogs)
