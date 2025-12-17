import httpx
import respx

from atlassian_graphql.auth import OAuthBearerAuth
from atlassian_graphql.client import GraphQLClient


@respx.mock
def test_beta_headers_sent_multiple_times():
    captured = {}

    def capture(request: httpx.Request):
        captured["beta"] = request.headers.get_list("X-ExperimentalApi")
        return httpx.Response(200, json={"data": {"ok": True}})

    route = respx.post("https://beta.example.com/graphql").mock(side_effect=capture)
    client = GraphQLClient(
        "https://beta.example.com", auth=OAuthBearerAuth(lambda: "token")
    )
    client.execute("query { ok }", experimental_apis=["featureA", "featureB"])
    assert route.called
    assert captured["beta"] == ["featureA", "featureB"]
    client.close()
