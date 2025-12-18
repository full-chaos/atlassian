from datetime import datetime, timedelta, timezone

import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_projects import iter_projects_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_projects_pagination_and_type_filtering():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer token"
        assert request.url.path.endswith("/rest/api/3/project/search")

        start_at = int(request.url.params.get("startAt", "0"))
        max_results = int(request.url.params.get("maxResults", "0"))
        assert max_results == 2
        calls.append(start_at)

        if start_at == 0:
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 2,
                    "total": 3,
                    "isLast": False,
                    "values": [
                        {"key": "A", "name": " Project A ", "projectTypeKey": "software"},
                        {"key": "B", "name": "Project B", "projectTypeKey": "business"},
                    ],
                },
                request=request,
            )
        if start_at == 2:
            return httpx.Response(
                200,
                json={
                    "startAt": 2,
                    "maxResults": 2,
                    "total": 3,
                    "isLast": True,
                    "values": [
                        {"key": "C", "name": "Project C", "projectTypeKey": "software"},
                    ],
                },
                request=request,
            )
        raise AssertionError(f"unexpected startAt={start_at}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        results = list(
            iter_projects_via_rest(
                client,
                cloud_id="cloud-123",
                project_types=["SOFTWARE"],
                page_size=2,
            )
        )

    assert [r.project.key for r in results] == ["A", "C"]
    assert results[0].project.name == "Project A"
    assert results[0].project.cloud_id == "cloud-123"
    assert results[0].opsgenie_teams == []
    assert calls == [0, 2]


def test_jira_rest_client_retries_on_429_retry_after_seconds():
    now = datetime(2021, 5, 10, 10, 59, 58, tzinfo=timezone.utc)
    current = {"now": now}

    def now_fn():
        return current["now"]

    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        current["now"] = current["now"] + timedelta(seconds=seconds)

    responses = [
        lambda request: httpx.Response(429, headers={"Retry-After": "2"}, json={}, request=request),
        lambda request: httpx.Response(
            200,
            json={"isLast": True, "total": 0, "values": []},
            request=request,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)(request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=1,
            time_provider=now_fn,
            sleeper=sleeper,
            http_client=http_client,
        )
        payload = client.get_json("/rest/api/3/project/search", params={"startAt": 0, "maxResults": 1})

    assert payload["values"] == []
    assert slept and pytest.approx(slept[0], rel=0.01) == 2.0


def test_iter_projects_via_rest_requires_cloud_id():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        with pytest.raises(ValueError):
            list(iter_projects_via_rest(client, cloud_id=" ", project_types=["SOFTWARE"], page_size=1))
