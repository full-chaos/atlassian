import httpx

from atlassian.auth import BasicApiTokenAuth, CookieAuth, OAuthBearerAuth
from atlassian.graph.client import GraphQLClient


def test_bearer_auth_header():
    captured = {}

    def token():
        return "abc123"

    transport = httpx.MockTransport(lambda request: _capture_request(request, captured))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://example.com",
            auth=OAuthBearerAuth(token),
            http_client=http_client,
        )
        client.execute("query { test }")
        assert captured["authorization"] == "Bearer abc123"


def test_bearer_auth_strips_bearer_prefix():
    captured = {}

    def token():
        return "Bearer abc123"

    transport = httpx.MockTransport(lambda request: _capture_request(request, captured))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://example.com",
            auth=OAuthBearerAuth(token),
            http_client=http_client,
        )
        client.execute("query { test }")
        assert captured["authorization"] == "Bearer abc123"


def test_basic_auth_header():
    captured = {}

    transport = httpx.MockTransport(lambda request: _capture_request(request, captured))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://example.com",
            auth=BasicApiTokenAuth("user@example.com", "apitoken"),
            http_client=http_client,
        )
        client.execute("query { test }")
        assert "Basic " in captured["authorization"]


def test_cookie_auth_applied():
    captured = {}
    transport = httpx.MockTransport(lambda request: _capture_request(request, captured))
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://example.com",
            auth=CookieAuth({"session": "abc", "xsrf": "123"}),
            http_client=http_client,
        )
        client.execute("query { test }")
        assert "session=abc" in captured["cookie"]


def _capture_request(request: httpx.Request, target: dict):
    for key, value in request.headers.items():
        target[key.lower()] = value
    return httpx.Response(200, json={"data": {"ok": True}}, request=request)
