import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_worklogs import iter_issue_worklogs_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_worklogs_pagination_and_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/3/issue/A-1/worklog")
        start_at = int(request.url.params.get("startAt", "0"))
        if start_at == 0:
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 1,
                    "total": 2,
                    "worklogs": [
                        {
                            "id": "200",
                            "author": {"accountId": "u1", "displayName": "User 1"},
                            "started": "2021-01-02T00:00:00.000+0000",
                            "timeSpentSeconds": 60,
                            "created": "2021-01-02T00:00:00.000+0000",
                            "updated": "2021-01-02T00:00:00.000+0000",
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
                    "worklogs": [
                        {
                            "id": "201",
                            "started": "2021-01-03T00:00:00.000+0000",
                            "timeSpentSeconds": 120,
                            "created": "2021-01-03T00:00:00.000+0000",
                            "updated": "2021-01-03T00:00:00.000+0000",
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
        worklogs = list(iter_issue_worklogs_via_rest(client, issue_key="A-1", page_size=1))

    assert len(worklogs) == 2
    assert worklogs[0].issue_key == "A-1"
    assert worklogs[0].worklog_id == "200"
    assert worklogs[0].time_spent_seconds == 60
    assert worklogs[0].author and worklogs[0].author.account_id == "u1"
    assert worklogs[1].author is None
