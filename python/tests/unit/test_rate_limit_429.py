from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_projects import iter_projects_with_opsgenie_linkable_teams
from atlassian.graph.client import GraphQLClient


def test_jira_projects_retries_on_429_retry_after_timestamp():
    now = datetime(2021, 5, 10, 10, 59, 58, tzinfo=timezone.utc)
    current = {"now": now}

    def now_fn():
        return current["now"]

    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        current["now"] = current["now"] + timedelta(seconds=seconds)

    responses = [
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "2021-05-10T11:00Z"},
            json={"extensions": {"requestId": "abc-123"}},
            request=request,
        ),
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "jira": {
                        "projects": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "edges": [],
                        }
                    }
                }
            },
            request=request,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload.get("operationName") == "JiraProjectsPage"
        return responses.pop(0)(request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=1,
            time_provider=now_fn,
            sleeper=sleeper,
            http_client=http_client,
        )
        results = list(
            iter_projects_with_opsgenie_linkable_teams(
                client,
                cloud_id="cloud-123",
                project_types=["SOFTWARE"],
                page_size=50,
            )
        )

    assert results == []
    assert slept and pytest.approx(slept[0], rel=0.01) == 2.0
