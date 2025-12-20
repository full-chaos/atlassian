from pathlib import Path

import httpx

from atlassian.rest.openapi_fetcher import fetch_jira_rest_openapi


def test_fetch_jira_rest_openapi_writes_pretty_json(tmp_path: Path):
    sample = {"openapi": "3.0.1", "info": {"title": "Jira", "version": "x"}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=sample, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        out_path = tmp_path / "swagger.json"
        written = fetch_jira_rest_openapi(
            url="https://example/swagger.json",
            output_path=out_path,
            http_client=http_client,
        )

    assert written == out_path
    text = out_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '"openapi": "3.0.1"' in text
