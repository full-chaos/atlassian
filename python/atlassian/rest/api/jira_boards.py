from __future__ import annotations

from typing import Iterator

from ...canonical_models import JiraBoard
from ...errors import SerializationError
from ..client import JiraRestClient
from ..env import auth_from_env, jira_rest_base_url_from_env
from ..gen import jira_agile_api as api
from ..mappers.jira_boards import map_rest_board


def iter_boards_via_rest(
    client: JiraRestClient,
    page_size: int = 50,
) -> Iterator[JiraBoard]:
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    start_at = 0
    seen_start_at: set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError(
                "Pagination startAt repeated; aborting to prevent infinite loop"
            )
        seen_start_at.add(start_at)

        payload = client.get_json(
            "/rest/agile/1.0/board",
            params={"startAt": start_at, "maxResults": page_size},
        )
        page = api.BoardPage.from_dict(payload, "data")
        values = page.values

        for item in values:
            yield map_rest_board(board=item)

        has_is_last = isinstance(page.is_last, bool)
        if has_is_last and page.is_last:
            break

        if len(values) < page_size:
            break

        if len(values) == 0:
            break

        start_at += len(values)


def list_boards_via_rest(
    page_size: int = 50,
) -> Iterator[JiraBoard]:
    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env("")
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        yield from iter_boards_via_rest(client, page_size)
