import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_issues import iter_issues_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_issues_pagination_and_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/3/search")
        start_at = int(request.url.params.get("startAt", "0"))
        assert request.url.params.get("jql")
        assert request.url.params.get("fields")
        if start_at == 0:
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 2,
                    "total": 3,
                    "issues": [
                        {
                            "id": "1",
                            "key": "A-1",
                            "fields": {
                                "project": {"key": "A"},
                                "issuetype": {"name": "Bug"},
                                "status": {"name": "Done"},
                                "created": "2021-01-01T00:00:00.000+0000",
                                "updated": "2021-01-02T00:00:00.000+0000",
                                "labels": ["l1"],
                                "components": [{"name": "Comp1"}],
                            },
                        },
                        {
                            "id": "2",
                            "key": "A-2",
                            "fields": {
                                "project": {"key": "A"},
                                "issuetype": {"name": "Task"},
                                "status": {"name": "To Do"},
                                "created": "2021-01-03T00:00:00.000+0000",
                                "updated": "2021-01-04T00:00:00.000+0000",
                                "assignee": {"accountId": "u1", "displayName": "User 1"},
                                "reporter": {"accountId": "u2", "displayName": "User 2"},
                            },
                        },
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
                    "issues": [
                        {
                            "id": "3",
                            "key": "A-3",
                            "fields": {
                                "project": {"key": "A"},
                                "issuetype": {"name": "Story"},
                                "status": {"name": "In Progress"},
                                "created": "2021-01-05T00:00:00.000+0000",
                                "updated": "2021-01-06T00:00:00.000+0000",
                                "resolutiondate": "2021-01-07T00:00:00.000+0000",
                            },
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
        issues = list(
            iter_issues_via_rest(
                client,
                cloud_id="cloud-123",
                jql="project = A ORDER BY created DESC",
                page_size=2,
            )
        )

    assert len(issues) == 3
    assert issues[0].cloud_id == "cloud-123"
    assert issues[0].key == "A-1"
    assert issues[0].project_key == "A"
    assert issues[0].issue_type == "Bug"
    assert issues[0].status == "Done"
    assert issues[0].labels == ["l1"]
    assert issues[0].components == ["Comp1"]
    assert issues[1].assignee and issues[1].assignee.account_id == "u1"
    assert issues[2].resolved_at == "2021-01-07T00:00:00.000+0000"


def test_iter_issues_via_rest_requires_cloud_id():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = JiraRestClient(
            "https://api.atlassian.com/ex/jira/cloud-123",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        with pytest.raises(ValueError):
            list(iter_issues_via_rest(client, cloud_id=" ", jql="project=A", page_size=1))
