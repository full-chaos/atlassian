import json

import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_sprints import get_sprint_by_id
from atlassian.graph.client import GraphQLClient


def test_jira_sprint_by_id_graphql_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload.get("operationName") == "JiraSprintById"
        assert payload.get("variables") == {"id": "sprint-1"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "sprintById": {
                        "sprintId": "42",
                        "name": "Sprint 42",
                        "state": "ACTIVE",
                        "startDate": "2021-01-01T00:00:00Z",
                        "endDate": "2021-01-14T00:00:00Z",
                        "completionDate": "2021-01-15T00:00:00Z",
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
        sprint = get_sprint_by_id(client, "sprint-1")

    assert sprint.id == "42"
    assert sprint.name == "Sprint 42"
    assert sprint.state == "ACTIVE"
    assert sprint.start_at == "2021-01-01T00:00:00Z"
