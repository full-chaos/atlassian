import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.rest.api.jira_issues import iter_issues_via_rest
from atlassian.rest.client import JiraRestClient


def test_jira_rest_issues_pagination_and_mapping():
    story_points_field = "customfield_10016"
    sprint_ids_field = "customfield_10020"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/3/search")
        start_at = int(request.url.params.get("startAt", "0"))
        assert request.url.params.get("jql")
        fields_param = request.url.params.get("fields")
        assert fields_param
        assert story_points_field in fields_param
        assert sprint_ids_field in fields_param
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
                                story_points_field: 5,
                                sprint_ids_field: [{"id": 101}, {"id": "102"}],
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
                                story_points_field: 3.5,
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
                story_points_field=story_points_field,
                sprint_ids_field=sprint_ids_field,
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
    assert issues[0].story_points == 5.0
    assert issues[0].sprint_ids == ["101", "102"]
    assert issues[1].assignee and issues[1].assignee.account_id == "u1"
    assert issues[1].story_points == 3.5
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


def test_iter_issues_via_rest_rejects_invalid_sprint_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 1,
                "total": 1,
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
                            "customfield_10020": {"id": 101},
                        },
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
        with pytest.raises(ValueError):
            list(
                iter_issues_via_rest(
                    client,
                    cloud_id="cloud-123",
                    jql="project = A",
                    page_size=1,
                    sprint_ids_field="customfield_10020",
                )
            )


def test_iter_issues_via_rest_uses_env_fields(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_JIRA_STORY_POINTS_FIELD", "customfield_10016")
    monkeypatch.setenv("ATLASSIAN_JIRA_SPRINT_IDS_FIELD", "customfield_10020")

    def handler(request: httpx.Request) -> httpx.Response:
        fields_param = request.url.params.get("fields")
        assert fields_param
        assert "customfield_10016" in fields_param
        assert "customfield_10020" in fields_param
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 1,
                "total": 1,
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
                            "customfield_10016": "13",
                            "customfield_10020": [101, 102],
                        },
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
        issues = list(
            iter_issues_via_rest(
                client,
                cloud_id="cloud-123",
                jql="project = A",
                page_size=1,
            )
        )

    assert issues[0].story_points == 13.0
    assert issues[0].sprint_ids == ["101", "102"]
