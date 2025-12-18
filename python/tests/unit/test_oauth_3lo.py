import json

import httpx

from atlassian.graph.client import GraphQLClient
from atlassian.oauth_3lo import OAuthRefreshTokenAuth


def test_oauth_refresh_token_auth_applies_and_caches_token():
    calls = {"token": 0, "graphql": 0, "auth": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            calls["token"] += 1
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["grant_type"] == "refresh_token"
            assert payload["client_id"] == "client-id"
            assert payload["client_secret"] == "client-secret"
            assert payload["refresh_token"] == "refresh-token"
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
                request=request,
            )
        if request.url.path == "/graphql":
            calls["graphql"] += 1
            calls["auth"].append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"data": {"ok": True}}, request=request)
        return httpx.Response(404, json={"error": "not found"}, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        auth = OAuthRefreshTokenAuth(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_url="https://example.com/oauth/token",
            http_client=http_client,
        )
        client = GraphQLClient(
            "https://example.com",
            auth=auth,
            http_client=http_client,
        )
        client.execute("query { ok }")
        client.execute("query { ok }")

    assert calls["token"] == 1
    assert calls["graphql"] == 2
    assert calls["auth"] == ["Bearer access-1", "Bearer access-1"]
