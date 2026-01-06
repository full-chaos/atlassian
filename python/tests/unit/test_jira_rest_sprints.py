import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_sprints import iter_board_sprints_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_sprints_pagination_and_mapping():
    """Test pagination and mapping of sprints from Jira Agile API."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/agile/1.0/board/10/sprint")
        start_at = int(request.url.params.get("startAt", "0"))
        if start_at == 0:
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 1,
                    "isLast": False,
                    "values": [
                        {
                            "id": 100,
                            "name": "Sprint 1",
                            "state": "active",
                            "startDate": "2021-01-01T00:00:00.000Z",
                            "endDate": "2021-01-15T00:00:00.000Z",
                        }
                    ],
                },
                request=request,
            )
        if start_at == 1:
            return httpx.Response(
                200,
                json={
                    "startAt": 1,
                    "maxResults": 1,
                    "isLast": True,
                    "values": [
                        {
                            "id": 101,
                            "name": "Sprint 2",
                            "state": "closed",
                            "startDate": "2021-01-16T00:00:00.000Z",
                            "endDate": "2021-01-30T00:00:00.000Z",
                            "completeDate": "2021-01-30T12:00:00.000Z",
                        }
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
        sprints = list(iter_board_sprints_via_rest(client, board_id=10, page_size=1))

    assert len(sprints) == 2
    assert sprints[0].id == "100"
    assert sprints[0].name == "Sprint 1"
    assert sprints[0].state == "active"
    assert sprints[0].start_at == "2021-01-01T00:00:00.000Z"
    assert sprints[0].end_at == "2021-01-15T00:00:00.000Z"
    assert sprints[0].complete_at is None

    assert sprints[1].id == "101"
    assert sprints[1].name == "Sprint 2"
    assert sprints[1].state == "closed"
    assert sprints[1].complete_at == "2021-01-30T12:00:00.000Z"


def test_iter_board_sprints_requires_positive_board_id():
    """Test that board_id must be a positive integer."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        with pytest.raises(ValueError, match="board_id must be a positive integer"):
            list(iter_board_sprints_via_rest(client, board_id=0))

        with pytest.raises(ValueError, match="board_id must be a positive integer"):
            list(iter_board_sprints_via_rest(client, board_id=-1))


def test_iter_board_sprints_validates_state_filter():
    """Test that state filter is validated."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        with pytest.raises(ValueError, match="state must be one of"):
            list(iter_board_sprints_via_rest(client, board_id=10, state="invalid"))


def test_iter_board_sprints_with_state_filter():
    """Test that state filter is passed to API."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("state") == "active"
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 50,
                "isLast": True,
                "values": [
                    {
                        "id": 100,
                        "name": "Sprint 1",
                        "state": "active",
                    }
                ],
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        sprints = list(iter_board_sprints_via_rest(client, board_id=10, state="active"))

    assert len(sprints) == 1
    assert sprints[0].state == "active"
