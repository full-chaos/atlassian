import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_changelog import iter_issue_changelog_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_changelog_pagination_and_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/3/issue/A-1/changelog")
        start_at = int(request.url.params.get("startAt", "0"))
        if start_at == 0:
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 1,
                    "total": 2,
                    "isLast": False,
                    "values": [
                        {
                            "id": "100",
                            "created": "2021-01-02T00:00:00.000+0000",
                            "author": {"accountId": "u1", "displayName": "User 1"},
                            "items": [
                                {"field": "status", "fromString": "To Do", "toString": "In Progress"}
                            ],
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
                    "total": 2,
                    "isLast": True,
                    "values": [
                        {
                            "id": "101",
                            "created": "2021-01-03T00:00:00.000+0000",
                            "items": [{"field": "assignee", "from": "u1", "to": "u2"}],
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
        events = list(iter_issue_changelog_via_rest(client, issue_key="A-1", page_size=1))

    assert len(events) == 2
    assert events[0].issue_key == "A-1"
    assert events[0].event_id == "100"
    assert events[0].author and events[0].author.account_id == "u1"
    assert events[0].items[0].field == "status"
    assert events[1].author is None
