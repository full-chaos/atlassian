from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import httpx

from ..auth import AuthProvider
from ..errors import (
    GraphQLOperationError,
    RateLimitError,
    SerializationError,
    TransportError,
)
from ..logging import get_logger, sanitize_headers
from ..models import GraphQLResult, parse_error_items
from ..retry import parse_retry_after
from .throttle import TokenBucket


class GraphQLClient:
    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        timeout_seconds: float = 15.0,
        strict: bool = False,
        logger=None,
        user_agent: Optional[str] = None,
        max_retries_429: int = 2,
        max_wait_seconds: int = 60,
        enable_local_throttling: bool = False,
        sleeper: Callable[[float], None] | None = None,
        time_provider: Callable[[], datetime] | None = None,
        http_client: httpx.Client | None = None,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        if auth is None:
            raise ValueError("auth is required")
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.strict = strict
        self.max_retries_429 = max(0, max_retries_429)
        self.max_wait_seconds = max(0, max_wait_seconds)
        self.enable_local_throttling = enable_local_throttling
        self._logger = get_logger(logger)
        self._graphql_url = (
            self.base_url
            if self.base_url.endswith("/graphql")
            else f"{self.base_url}/graphql"
        )
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client(timeout=timeout_seconds)
        self._sleeper = sleeper if sleeper is not None else time.sleep
        self._now = (
            time_provider
            if time_provider is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._bucket_capacity = 10000.0
        self._bucket_refill_rate = self._bucket_capacity / 60.0
        self._token_bucket = (
            TokenBucket(
                capacity=self._bucket_capacity,
                refill_rate_per_sec=self._bucket_refill_rate,
                now=self._now,
                sleeper=self._sleeper,
            )
            if self.enable_local_throttling
            else None
        )
        self._user_agent = user_agent or "atlassian-graphql-python/0.1.0"
        self._base_headers: List[tuple[str, str]] = [
            ("Content-Type", "application/json"),
            ("Accept", "application/json"),
            ("User-Agent", self._user_agent),
        ]

    def _consume_local_budget(self, estimated_cost: float) -> None:
        if self._token_bucket is None:
            return
        wait_time = self._token_bucket.consume(
            float(estimated_cost),
            float(self.max_wait_seconds),
        )
        self._logger.debug(
            "Local throttling applied",
            extra={
                "endpoint": self._graphql_url,
                "estimated_cost": estimated_cost,
                "wait_seconds": round(wait_time, 4),
            },
        )

    def _build_headers(self, experimental_apis: Optional[List[str]]) -> httpx.Headers:
        header_items: List[tuple[str, str]] = list(self._base_headers)
        if experimental_apis:
            for beta in experimental_apis:
                if beta:
                    header_items.append(("X-ExperimentalApi", beta))
        headers = httpx.Headers(header_items)
        self.auth.apply(headers)
        return headers

    def _extract_request_id(self, response: httpx.Response) -> Optional[str]:
        try:
            payload = response.json()
        except Exception:
            return None
        if isinstance(payload, dict):
            extensions = payload.get("extensions")
            if isinstance(extensions, dict):
                for key in ("requestId", "request_id", "requestid"):
                    value = extensions.get(key)
                    if isinstance(value, str):
                        return value
        return None

    def execute(
        self,
        query: str,
        variables: Optional[Dict] = None,
        operation_name: Optional[str] = None,
        experimental_apis: Optional[List[str]] = None,
        estimated_cost: int = 1,
    ) -> GraphQLResult:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        payload: Dict[str, object] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        cost_value = 1 if estimated_cost is None else estimated_cost
        if cost_value < 0:
            cost_value = 0

        retries = 0
        while True:
            attempt_number = retries + 1
            self._consume_local_budget(cost_value)
            headers = self._build_headers(experimental_apis)
            cookies = self.auth.get_cookies() if hasattr(self.auth, "get_cookies") else None
            start = time.perf_counter()
            try:
                response = self._client.post(
                    self._graphql_url,
                    headers=headers,
                    json=payload,
                    cookies=cookies,
                )
            except httpx.RequestError as exc:
                self._logger.error("HTTP request failed", exc_info=exc)
                raise TransportError(status_code=0, body_snippet=str(exc)) from exc

            try:
                duration = time.perf_counter() - start
                self._logger.debug(
                    "GraphQL request completed",
                    extra={
                        "operationName": operation_name,
                        "attempt": attempt_number,
                        "status_code": response.status_code,
                        "duration_sec": round(duration, 4),
                        "headers": sanitize_headers(headers),
                    },
                )

                if response.status_code == 429:
                    retry_header = response.headers.get("Retry-After")
                    request_id = self._extract_request_id(response)
                    try:
                        retry_at, parser_used = parse_retry_after(retry_header)
                        self._logger.debug(
                            "Parsed Retry-After header",
                            extra={
                                "retry_after": retry_header,
                                "parser": parser_used,
                                "retry_at": retry_at.isoformat(),
                                "operationName": operation_name,
                            },
                        )
                    except ValueError as exc:
                        self._logger.debug(
                            "Retry-After parsing failed",
                            extra={
                                "retry_after": retry_header,
                                "parser": None,
                                "operationName": operation_name,
                            },
                        )
                        raise RateLimitError(
                            retry_after=None,
                            attempts=attempt_number,
                            header_value=retry_header,
                        ) from exc

                    computed_wait = (retry_at - self._now()).total_seconds()
                    wait_seconds = computed_wait
                    if wait_seconds <= 0:
                        wait_seconds = 0.0

                    retry_allowed = retries < self.max_retries_429
                    over_cap = computed_wait > self.max_wait_seconds
                    self._logger.warning(
                        "Rate limited on GraphQL request",
                        extra={
                            "endpoint": self._graphql_url,
                            "operationName": operation_name,
                            "attempt": attempt_number,
                            "retry_at": retry_at.isoformat(),
                            "computed_wait_seconds": round(computed_wait, 4),
                            "wait_seconds": round(wait_seconds, 4),
                            "request_id": request_id,
                            "retrying": retry_allowed and not over_cap,
                        },
                    )
                    if over_cap:
                        raise RateLimitError(
                            retry_after=retry_at,
                            attempts=attempt_number,
                            header_value=retry_header,
                            wait_seconds=computed_wait,
                            max_wait_seconds=self.max_wait_seconds,
                        )
                    if not retry_allowed:
                        raise RateLimitError(
                            retry_after=retry_at,
                            attempts=attempt_number,
                            header_value=retry_header,
                            wait_seconds=computed_wait,
                        )
                    if wait_seconds > 0:
                        self._sleeper(wait_seconds)
                    retries += 1
                    continue

                if response.status_code >= 500:
                    raise TransportError(
                        status_code=response.status_code,
                        body_snippet=response.text[:200],
                    )
                if response.status_code >= 400:
                    raise TransportError(
                        status_code=response.status_code,
                        body_snippet=response.text[:200],
                    )

                try:
                    body = response.json()
                except json.JSONDecodeError as exc:
                    raise SerializationError(f"Failed to parse JSON: {exc}") from exc

                data = body.get("data") if isinstance(body, dict) else None
                errors = (
                    parse_error_items(body.get("errors"))
                    if isinstance(body, dict)
                    else None
                )
                extensions = body.get("extensions") if isinstance(body, dict) else None

                if self.strict and errors:
                    raise GraphQLOperationError(errors=errors, partial_data=data)

                return GraphQLResult(data=data, errors=errors, extensions=extensions)
            finally:
                response.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "GraphQLClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
