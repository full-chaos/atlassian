import json

import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_projects import iter_projects_with_opsgenie_linkable_teams
from atlassian.graph.client import GraphQLClient
from atlassian.graph.gen import jira_projects_api as api


def _resp(request: httpx.Request, payload: dict, status_code: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=request,
    )


def test_jira_projects_pagination_outer_and_nested():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        op = body.get("operationName")
        vars = body.get("variables") or {}
        calls.append({"op": op, "vars": vars})

        if op == "JiraProjectsPage":
            after = vars.get("after")
            if after in (None, ""):
                return _resp(
                    request,
                    {
                        "data": {
                            "jira": {
                                "projects": {
                                    "pageInfo": {
                                        "hasNextPage": True,
                                        "endCursor": "P1",
                                    },
                                    "edges": [
                                        {
                                            "cursor": "pc1",
                                            "node": {
                                                "id": "projA",
                                                "key": "A",
                                                "name": "Project A",
                                                "opsgenieTeams": {
                                                    "pageInfo": {
                                                        "hasNextPage": True,
                                                        "endCursor": "TA1",
                                                    },
                                                    "edges": [
                                                        {
                                                            "cursor": "tc1",
                                                            "node": {"id": "t1", "name": "Team 1"},
                                                        },
                                                        {
                                                            "cursor": "tc2",
                                                            "node": {"id": "t2", "name": "Team 2"},
                                                        },
                                                    ],
                                                },
                                            },
                                        },
                                        {
                                            "cursor": "pc2",
                                            "node": {
                                                "id": "projB",
                                                "key": "B",
                                                "name": "Project B",
                                                "opsgenieTeams": {
                                                    "pageInfo": {
                                                        "hasNextPage": False,
                                                        "endCursor": None,
                                                    },
                                                    "edges": [],
                                                },
                                            },
                                        },
                                    ],
                                }
                            }
                        }
                    },
                )

            if after == "P1":
                return _resp(
                    request,
                    {
                        "data": {
                            "jira": {
                                "projects": {
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                    "edges": [
                                        {
                                            "cursor": "pc3",
                                            "node": {
                                                "id": "projC",
                                                "key": "C",
                                                "name": "Project C",
                                                "opsgenieTeams": {
                                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                                    "edges": [
                                                        {
                                                            "cursor": "tc4",
                                                            "node": {"id": "t4", "name": "Team 4"},
                                                        }
                                                    ],
                                                },
                                            },
                                        }
                                    ],
                                }
                            }
                        }
                    },
                )

            raise AssertionError(f"unexpected after cursor: {after!r}")

        if op == "JiraProjectOpsgenieTeamsPage":
            after = vars.get("after")
            if after != "TA1":
                raise AssertionError(f"unexpected opsgenie after: {after!r}")

            if api.REFETCH_STRATEGY == "node":
                assert vars.get("projectId") == "projA"
                payload = {
                    "data": {
                        "project": {
                            "opsgenieTeams": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "edges": [
                                    {
                                        "cursor": "tc3",
                                        "node": {"id": "t3", "name": "Team 3"},
                                    }
                                ],
                            }
                        }
                    }
                }
            else:
                assert vars.get("cloudId") == "cloud-123"
                assert vars.get("projectKey") == "A"
                payload = {
                    "data": {
                        "jira": {
                            "project": {
                                "opsgenieTeams": {
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                    "edges": [
                                        {
                                            "cursor": "tc3",
                                            "node": {"id": "t3", "name": "Team 3"},
                                        }
                                    ],
                                }
                            }
                        }
                    }
                }
            return _resp(request, payload)

        raise AssertionError(f"unexpected operationName: {op!r}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        results = list(
            iter_projects_with_opsgenie_linkable_teams(
                client,
                cloud_id="cloud-123",
                project_types=["software"],
                page_size=2,
            )
        )

    assert [r.project.key for r in results] == ["A", "B", "C"]
    assert [t.id for t in results[0].opsgenie_teams] == ["t1", "t2", "t3"]
    assert [t.id for t in results[1].opsgenie_teams] == []
    assert [t.id for t in results[2].opsgenie_teams] == ["t4"]

    assert [c["op"] for c in calls] == [
        "JiraProjectsPage",
        "JiraProjectOpsgenieTeamsPage",
        "JiraProjectsPage",
    ]
