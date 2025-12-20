import json

import httpx

from atlassian.auth import OAuthBearerAuth
from atlassian.graph.schema_fetcher import fetch_schema_introspection


def test_schema_fetcher_writes_introspection_json(tmp_path):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request):
        captured["beta"] = request.headers.get_list("X-ExperimentalApi")
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured["query"] = payload.get("query")
        return httpx.Response(
            200,
            json={
                "data": {
                    "__schema": {
                        "queryType": {"name": "Query"},
                        "types": [],
                        "directives": [],
                    }
                }
            },
            request=request,
        )
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        result = fetch_schema_introspection(
            "https://api.atlassian.com",
            OAuthBearerAuth(lambda: "token"),
            output_dir=tmp_path,
            experimental_apis=["featureA", "featureB"],
            timeout_seconds=5.0,
            http_client=http_client,
        )

    assert "__schema" in json.loads(result.introspection_json_path.read_text("utf-8"))["data"]
    assert captured["beta"] == ["featureA", "featureB"]
    assert isinstance(captured["query"], str) and "__schema" in captured["query"]
