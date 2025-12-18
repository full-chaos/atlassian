from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple, Union

import httpx

from ..auth import AuthProvider
from ..errors import RateLimitError, SerializationError, TransportError
from ..logging import get_logger, sanitize_headers
from ..retry import parse_retry_after


class JiraRestClient:
    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        *,
        timeout_seconds: float = 15.0,
        logger=None,
        user_agent: Optional[str] = None,
        max_retries_429: int = 2,
        max_wait_seconds: int = 60,
        sleeper: Callable[[float], None] | None = None,
        time_provider: Callable[[], datetime] | None = None,
        http_client: httpx.Client | None = None,
    ):
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required")
        if auth is None:
            raise ValueError("auth is required")
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.max_retries_429 = max(0, max_retries_429)
        self.max_wait_seconds = max(0, max_wait_seconds)
        self._logger = get_logger(logger)
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client(timeout=timeout_seconds)
        self._sleeper = sleeper if sleeper is not None else time.sleep
        self._now = (
            time_provider
            if time_provider is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._user_agent = user_agent or "atlassian-jira-rest-python/0.1.0"
        self._base_headers: list[tuple[str, str]] = [
            ("Accept", "application/json"),
            ("User-Agent", self._user_agent),
        ]

    def _build_headers(self) -> httpx.Headers:
        headers = httpx.Headers(list(self._base_headers))
        self.auth.apply(headers)
        return headers

    def _parse_retry_after(
        self, header_value: Optional[str]
    ) -> Tuple[datetime, str]:
        if header_value is None:
            raise ValueError("Retry-After header is missing")
        candidate = header_value.strip()
        if not candidate:
            raise ValueError("Retry-After header is empty")
        if candidate.isdigit():
            seconds = int(candidate)
            return self._now() + timedelta(seconds=seconds), "delta-seconds"
        parsed, label = parse_retry_after(candidate)
        return parsed, label

    def get_json(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Union[str, int]]] = None,
    ) -> Dict:
        if not path or not isinstance(path, str) or not path.strip():
            raise ValueError("path is required")
        cleaned_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{cleaned_path}"

        retries = 0
        while True:
            attempt_number = retries + 1
            headers = self._build_headers()
            cookies = self.auth.get_cookies() if hasattr(self.auth, "get_cookies") else None
            start = time.perf_counter()
            try:
                response = self._client.get(url, headers=headers, params=params, cookies=cookies)
            except httpx.RequestError as exc:
                self._logger.error("HTTP request failed", exc_info=exc)
                raise TransportError(status_code=0, body_snippet=str(exc)) from exc

            try:
                duration = time.perf_counter() - start
                self._logger.debug(
                    "Jira REST request completed",
                    extra={
                        "method": "GET",
                        "path": cleaned_path,
                        "attempt": attempt_number,
                        "status_code": response.status_code,
                        "duration_sec": round(duration, 4),
                        "headers": sanitize_headers(headers),
                    },
                )

                if response.status_code == 429:
                    retry_header = response.headers.get("Retry-After")
                    try:
                        retry_at, parser_used = self._parse_retry_after(retry_header)
                        self._logger.debug(
                            "Parsed Retry-After header",
                            extra={
                                "retry_after": retry_header,
                                "parser": parser_used,
                                "retry_at": retry_at.isoformat(),
                                "path": cleaned_path,
                            },
                        )
                    except ValueError as exc:
                        self._logger.debug(
                            "Retry-After parsing failed",
                            extra={
                                "retry_after": retry_header,
                                "parser": None,
                                "path": cleaned_path,
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
                        "Rate limited on Jira REST request",
                        extra={
                            "path": cleaned_path,
                            "attempt": attempt_number,
                            "retry_at": retry_at.isoformat(),
                            "computed_wait_seconds": round(computed_wait, 4),
                            "wait_seconds": round(wait_seconds, 4),
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

                if not isinstance(body, dict):
                    raise SerializationError("Expected object JSON response")
                return body
            finally:
                response.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "JiraRestClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
