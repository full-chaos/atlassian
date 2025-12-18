import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.api.jira_projects import iter_projects_with_opsgenie_linkable_teams
from atlassian.graph.client import GraphQLClient


def test_beta_headers_sent_multiple_times():
    captured = {}

    def capture(request: httpx.Request):
        captured["beta"] = request.headers.get_list("X-ExperimentalApi")
        return httpx.Response(200, json={"data": {"ok": True}}, request=request)

    transport = httpx.MockTransport(capture)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://beta.example.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        client.execute("query { ok }", experimental_apis=["featureA", "featureB"])
        assert captured["beta"] == ["featureA", "featureB"]


def test_beta_headers_sent_on_jira_projects_requests():
    betas: list[list[str]] = []
    call_count = {"count": 0}

    def handler(request: httpx.Request):
        betas.append(request.headers.get_list("X-ExperimentalApi"))
        call_count["count"] += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "jira": {
                        "projects": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "edges": [],
                        }
                    }
                }
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://beta.example.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        list(
            iter_projects_with_opsgenie_linkable_teams(
                client,
                cloud_id="cloud-123",
                project_types=["SOFTWARE"],
                page_size=10,
                experimental_apis=["featureA", "featureB"],
            )
        )

    assert call_count["count"] == 1
    assert betas and betas[0] == ["featureA", "featureB"]
