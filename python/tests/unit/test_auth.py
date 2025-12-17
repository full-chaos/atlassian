import httpx
import respx

from atlassian_graphql.auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from atlassian_graphql.client import GraphQLClient


@respx.mock
def test_bearer_auth_header():
    captured = {}

    def token():
        return "abc123"

    route = respx.post("https://example.com/graphql").mock(
        side_effect=lambda request: _capture_request(request, captured)
    )
    client = GraphQLClient("https://example.com", auth=OAuthBearerAuth(token))
    client.execute("query { test }")
    assert route.called
    assert captured["authorization"] == "Bearer abc123"
    client.close()


@respx.mock
def test_basic_auth_header():
    captured = {}

    route = respx.post("https://example.com/graphql").mock(
        side_effect=lambda request: _capture_request(request, captured)
    )
    client = GraphQLClient(
        "https://example.com", auth=BasicApiTokenAuth("user@example.com", "apitoken")
    )
    client.execute("query { test }")
    assert "Basic " in captured["authorization"]
    client.close()


@respx.mock
def test_cookie_auth_applied():
    captured = {}
    route = respx.post("https://example.com/graphql").mock(
        side_effect=lambda request: _capture_request(request, captured)
    )
    client = GraphQLClient(
        "https://example.com", auth=CookieAuth({"session": "abc", "xsrf": "123"})
    )
    client.execute("query { test }")
    assert "session=abc" in captured["cookie"]
    client.close()


def _capture_request(request: httpx.Request, target: dict):
    for key, value in request.headers.items():
        target[key.lower()] = value
    return httpx.Response(200, json={"data": {"ok": True}})
