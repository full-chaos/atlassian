import json

import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_issues import get_issue_by_key
from atlassian.graph.client import GraphQLClient


def test_jira_issue_by_key_graphql_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload.get("operationName") == "JiraIssueByKey"
        assert payload.get("variables") == {"cloudId": "cloud-123", "key": "A-1"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "issueByKey": {
                        "key": "A-1",
                        "issueType": {"name": "Bug"},
                        "status": {"name": "Done"},
                        "projectField": {"project": {"key": "A", "cloudId": "cloud-123"}},
                        "createdField": {"dateTime": "2021-01-01T00:00:00Z"},
                        "updatedField": {"dateTime": "2021-01-02T00:00:00Z"},
                        "resolutionDateField": {"dateTime": "2021-01-03T00:00:00Z"},
                        "assigneeField": {"user": {"accountId": "u1", "name": "User One"}},
                        "reporter": {"accountId": "u2", "name": "User Two"},
                    }
                }
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        issue = get_issue_by_key(client, "cloud-123", "A-1")

    assert issue.key == "A-1"
    assert issue.project_key == "A"
    assert issue.issue_type == "Bug"
    assert issue.status == "Done"
    assert issue.assignee and issue.assignee.account_id == "u1"
    assert issue.reporter and issue.reporter.account_id == "u2"
    assert issue.resolved_at == "2021-01-03T00:00:00Z"
