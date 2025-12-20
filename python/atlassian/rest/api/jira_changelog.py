from __future__ import annotations

from typing import Iterator

from ...canonical_models import JiraChangelogEvent
from ...errors import SerializationError
from ..client import JiraRestClient
from ..gen import jira_api as api
from ..mappers.jira_changelog import map_changelog_event


def iter_issue_changelog_via_rest(
    client: JiraRestClient,
    *,
    issue_key: str,
    page_size: int = 100,
) -> Iterator[JiraChangelogEvent]:
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
            f"/rest/api/3/issue/{issue_key_clean}/changelog",
            params={"startAt": start_at, "maxResults": page_size},
        )
        page = api.PageBeanChangelog.from_dict(payload, "data")
        values = page.values

        for item in values:
            yield map_changelog_event(issue_key=issue_key_clean, changelog=item)

        has_is_last = isinstance(page.is_last, bool)
        if has_is_last and page.is_last:
            break

        has_total = isinstance(page.total, int) and page.total >= 0
        if has_total:
            if start_at + len(values) >= page.total:
                break
        else:
            if len(values) < page_size:
                break

        if len(values) == 0:
            if has_is_last and not page.is_last:
                raise SerializationError(
                    "Received empty page with isLast=false; cannot continue pagination"
                )
            break
        start_at += len(values)
