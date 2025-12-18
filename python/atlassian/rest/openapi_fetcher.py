from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

import httpx

from ..errors import SerializationError, TransportError


DEFAULT_JIRA_REST_OPENAPI_URL = "https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json"


def fetch_jira_rest_openapi(
    *,
    url: str = DEFAULT_JIRA_REST_OPENAPI_URL,
    output_path: Union[str, Path] = "openapi/jira-rest.swagger-v3.json",
    timeout_seconds: float = 30.0,
    http_client: Optional[httpx.Client] = None,
) -> Path:
    if not url or not url.strip():
        raise ValueError("url is required")
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    owns_client = http_client is None
    client = http_client if http_client is not None else httpx.Client(timeout=timeout_seconds)
    try:
        response = client.get(url)
    except httpx.RequestError as exc:
        raise TransportError(status_code=0, body_snippet=str(exc)) from exc
    finally:
        if owns_client:
            client.close()

    try:
        if response.status_code != 200:
            raise TransportError(status_code=response.status_code, body_snippet=response.text[:200])

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise SerializationError(f"Failed to parse JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise SerializationError("Expected OpenAPI document to be a JSON object")

        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return out_path
    finally:
        response.close()
