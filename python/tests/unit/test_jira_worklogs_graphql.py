import json

import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_worklogs import iter_issue_worklogs_via_graphql
from atlassian.graph.client import GraphQLClient


def test_jira_worklogs_graphql_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append(payload)
        after = (payload.get("variables") or {}).get("after")
        if after in (None, ""):
            data = {
                "data": {
                    "issue": {
                        "worklogs": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                            "edges": [
                                {
                                    "cursor": "e1",
                                    "node": {
                                        "worklogId": "w1",
                                        "author": {"accountId": "u1", "name": "User One"},
                                        "timeSpent": {"timeInSeconds": 60},
                                        "created": "2021-01-01T00:00:00Z",
                                        "updated": "2021-01-01T01:00:00Z",
                                        "startDate": "2021-01-01T00:00:00Z",
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        else:
            data = {
                "data": {
                    "issue": {
                        "worklogs": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "edges": [
                                {
                                    "cursor": "e2",
                                    "node": {
                                        "worklogId": "w2",
                                        "author": {"accountId": "u2", "name": "User Two"},
                                        "timeSpent": {"timeInSeconds": 120},
                                        "created": "2021-01-02T00:00:00Z",
                                        "updated": "2021-01-02T01:00:00Z",
                                        "startDate": "2021-01-02T00:00:00Z",
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        worklogs = list(
            iter_issue_worklogs_via_graphql(
                client,
                cloud_id="cloud-123",
                issue_key="A-1",
                page_size=1,
            )
        )

    assert [wl.worklog_id for wl in worklogs] == ["w1", "w2"]
    assert worklogs[0].author and worklogs[0].author.account_id == "u1"
    assert worklogs[1].time_spent_seconds == 120
    assert len(calls) == 2
