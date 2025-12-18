from datetime import datetime, timedelta, timezone

import httpx
import pytest

from atlassian.auth import OAuthBearerAuth
from atlassian.errors import (
    GraphQLOperationError,
    LocalRateLimitError,
    RateLimitError,
    SerializationError,
    TransportError,
)
from atlassian.graph.client import GraphQLClient


def test_execute_returns_data():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"data": {"ok": True}}, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        result = client.execute("query { ok }")
        assert result.data == {"ok": True}


def test_strict_mode_raises_on_errors():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={"data": {"partial": True}, "errors": [{"message": "bad"}]},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            strict=True,
            http_client=http_client,
        )
        with pytest.raises(GraphQLOperationError):
            client.execute("query { broken }")


def test_retries_on_429_with_retry_after_timestamp():
    now = datetime(2021, 5, 10, 10, 59, 58, tzinfo=timezone.utc)
    current = {"now": now}

    def now_fn():
        return current["now"]

    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        current["now"] = current["now"] + timedelta(seconds=seconds)

    responses = [
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "2021-05-10T11:00Z"},
            request=request,
        ),
        lambda request: httpx.Response(200, json={"data": {"ok": True}}, request=request),
    ]

    def handler(request: httpx.Request):
        return responses.pop(0)(request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=1,
            time_provider=now_fn,
            sleeper=sleeper,
            http_client=http_client,
        )
        result = client.execute("query { ok }")
        assert result.data == {"ok": True}
        assert slept and pytest.approx(slept[0], rel=0.01) == 2.0


def test_raises_rate_limit_error_on_invalid_retry_after():
    def handler(request: httpx.Request):
        return httpx.Response(
            429,
            headers={"Retry-After": "invalid"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=0,
            http_client=http_client,
        )
        with pytest.raises(RateLimitError) as excinfo:
            client.execute("query { ok }")
        assert excinfo.value.header_value == "invalid"
        assert excinfo.value.attempts == 1


def test_retry_after_in_past_retries_immediately():
    now = datetime(2021, 5, 10, 11, 0, 1, tzinfo=timezone.utc)
    current = {"now": now}

    def now_fn():
        return current["now"]

    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        current["now"] = current["now"] + timedelta(seconds=seconds)

    responses = [
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "2021-05-10T11:00Z"},
            request=request,
        ),
        lambda request: httpx.Response(200, json={"data": {"ok": True}}, request=request),
    ]

    def handler(request: httpx.Request):
        return responses.pop(0)(request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=1,
            time_provider=now_fn,
            sleeper=sleeper,
            http_client=http_client,
        )
        result = client.execute("query { ok }")
        assert result.data == {"ok": True}
        assert slept == []


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_does_not_retry_on_5xx(status_code):
    call_count = {"count": 0}

    def handler(request):
        call_count["count"] += 1
        return httpx.Response(status_code, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            max_retries_429=2,
            http_client=http_client,
        )
        with pytest.raises(TransportError):
            client.execute("query { fail }")
        assert call_count["count"] == 1


def test_local_throttling_fails_when_wait_exceeds_max():
    now = datetime(2021, 5, 10, 10, 0, 0, tzinfo=timezone.utc)
    current = {"now": now}

    def now_fn():
        return current["now"]

    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        current["now"] = current["now"] + timedelta(seconds=seconds)

    call_count = {"count": 0}

    def handler(request: httpx.Request):
        call_count["count"] += 1
        return httpx.Response(200, json={"data": {"ok": True}}, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            enable_local_throttling=True,
            max_wait_seconds=5,
            time_provider=now_fn,
            sleeper=sleeper,
            http_client=http_client,
        )
        with pytest.raises(LocalRateLimitError):
            client.execute("query { ok }", estimated_cost=20000)
        assert call_count["count"] == 0
        assert slept  # waited locally before giving up


def test_invalid_json_raises_serialization_error():
    def handler(request: httpx.Request):
        return httpx.Response(200, content=b"not-json", request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=5.0) as http_client:
        client = GraphQLClient(
            "https://api.atlassian.com",
            auth=OAuthBearerAuth(lambda: "token"),
            http_client=http_client,
        )
        with pytest.raises(SerializationError):
            client.execute("query { ok }")
