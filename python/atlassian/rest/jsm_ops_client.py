from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterator, List, Optional, Union

import httpx

from ..auth import AuthProvider
from ..canonical_models import (
    AtlassianOpsAlertPolicy,
    AtlassianOpsEscalation,
    AtlassianOpsHeartbeat,
    AtlassianOpsOnCallParticipant,
    AtlassianOpsSchedule,
)
from ..errors import RateLimitError, SerializationError, TransportError
from ..logging import get_logger, sanitize_headers
from ..retry import parse_retry_after
from .mappers.jsm_ops import (
    map_alert_policy,
    map_escalation,
    map_heartbeat,
    map_on_call_participant,
    map_schedule,
)

import json


class JsmOpsClient:
    """REST client for the Atlassian JSM Operations API.

    Base URL: https://api.atlassian.com/jsm/ops/api/{cloud_id}
    OAuth scope required: read:ops-config:jira-service-management
    """

    def __init__(
        self,
        cloud_id: str,
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
        if not cloud_id or not cloud_id.strip():
            raise ValueError("cloud_id is required")
        if auth is None:
            raise ValueError("auth is required")
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.cloud_id = cloud_id.strip()
        self.base_url = f"https://api.atlassian.com/jsm/ops/api/{self.cloud_id}"
        self.auth = auth
        self.max_retries_429 = max(0, max_retries_429)
        self.max_wait_seconds = max(0, max_wait_seconds)
        self._logger = get_logger(logger)
        self._owns_client = http_client is None
        self._client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=timeout_seconds)
        )
        self._sleeper = sleeper if sleeper is not None else time.sleep
        self._now = (
            time_provider
            if time_provider is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._user_agent = user_agent or "atlassian-jsm-ops-rest-python/0.1.0"
        self._base_headers: list[tuple[str, str]] = [
            ("Accept", "application/json"),
            ("User-Agent", self._user_agent),
        ]

    def _build_headers(self) -> httpx.Headers:
        headers = httpx.Headers(list(self._base_headers))
        self.auth.apply(headers)
        return headers

    def _parse_retry_after(self, header_value: Optional[str]):
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
            cookies = (
                self.auth.get_cookies() if hasattr(self.auth, "get_cookies") else None
            )
            start = time.perf_counter()
            try:
                response = self._client.get(
                    url, headers=headers, params=params, cookies=cookies
                )
            except httpx.RequestError as exc:
                self._logger.error("HTTP request failed", exc_info=exc)
                raise TransportError(status_code=0, body_snippet=str(exc)) from exc

            try:
                duration = time.perf_counter() - start
                self._logger.debug(
                    "JSM Ops REST request completed",
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
                        "Rate limited on JSM Ops REST request",
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

    def iter_schedules(
        self, *, offset: int = 0, size: int = 50
    ) -> Iterator[AtlassianOpsSchedule]:
        """Iterate over all on-call schedules using offset/size pagination."""
        if size <= 0:
            raise ValueError("size must be > 0")
        current_offset = offset
        seen_offsets: set[int] = set()

        while True:
            if current_offset in seen_offsets:
                raise SerializationError(
                    "Pagination offset repeated; aborting to prevent infinite loop"
                )
            seen_offsets.add(current_offset)

            body = self.get_json(
                "/v1/schedules",
                params={"offset": current_offset, "size": size},
            )
            values = body.get("values") or []
            for item in values:
                yield map_schedule(item)

            links = body.get("links") or {}
            if not links.get("next"):
                break
            if len(values) < size:
                break
            if not values:
                break
            current_offset += len(values)

    def get_schedule(self, schedule_id: str) -> AtlassianOpsSchedule:
        """Fetch a single schedule by ID."""
        schedule_id = (schedule_id or "").strip()
        if not schedule_id:
            raise ValueError("schedule_id is required")
        body = self.get_json(f"/v1/schedules/{schedule_id}")
        return map_schedule(body)

    def iter_escalations(self, team_id: str) -> Iterator[AtlassianOpsEscalation]:
        """Iterate over escalations for a team using offset/size pagination."""
        team_id = (team_id or "").strip()
        if not team_id:
            raise ValueError("team_id is required")

        current_offset = 0
        size = 50
        seen_offsets: set[int] = set()

        while True:
            if current_offset in seen_offsets:
                raise SerializationError(
                    "Pagination offset repeated; aborting to prevent infinite loop"
                )
            seen_offsets.add(current_offset)

            body = self.get_json(
                f"/v1/teams/{team_id}/escalations",
                params={"offset": current_offset, "size": size},
            )
            values = body.get("values") or []
            for item in values:
                yield map_escalation(item)

            links = body.get("links") or {}
            if not links.get("next"):
                break
            if len(values) < size:
                break
            if not values:
                break
            current_offset += len(values)

    def iter_alert_policies(
        self, *, offset: int = 0, size: int = 50
    ) -> Iterator[AtlassianOpsAlertPolicy]:
        """Iterate over global alert policies using offset/size pagination."""
        if size <= 0:
            raise ValueError("size must be > 0")
        current_offset = offset
        seen_offsets: set[int] = set()

        while True:
            if current_offset in seen_offsets:
                raise SerializationError(
                    "Pagination offset repeated; aborting to prevent infinite loop"
                )
            seen_offsets.add(current_offset)

            body = self.get_json(
                "/v1/alerts/policies",
                params={"offset": current_offset, "size": size},
            )
            values = body.get("values") or []
            for item in values:
                yield map_alert_policy(item)

            links = body.get("links") or {}
            if not links.get("next"):
                break
            if len(values) < size:
                break
            if not values:
                break
            current_offset += len(values)

    def get_on_call(self, schedule_id: str) -> List[AtlassianOpsOnCallParticipant]:
        """Fetch the current on-call participants for a schedule."""
        schedule_id = (schedule_id or "").strip()
        if not schedule_id:
            raise ValueError("schedule_id is required")
        body = self.get_json(f"/v1/schedules/{schedule_id}/on-calls")
        participants_raw = body.get("onCallParticipants") or []
        return [map_on_call_participant(p, schedule_id=schedule_id) for p in participants_raw]

    def iter_heartbeats(
        self, team_id: str, *, offset: int = 0, size: int = 50
    ) -> Iterator[AtlassianOpsHeartbeat]:
        """Iterate over heartbeats for a team using offset/size pagination."""
        team_id = (team_id or "").strip()
        if not team_id:
            raise ValueError("team_id is required")
        if size <= 0:
            raise ValueError("size must be > 0")

        current_offset = offset
        seen_offsets: set[int] = set()

        while True:
            if current_offset in seen_offsets:
                raise SerializationError(
                    "Pagination offset repeated; aborting to prevent infinite loop"
                )
            seen_offsets.add(current_offset)

            body = self.get_json(
                f"/v1/teams/{team_id}/heartbeats",
                params={"offset": current_offset, "size": size},
            )
            values = body.get("values") or []
            for item in values:
                yield map_heartbeat(item)

            links = body.get("links") or {}
            if not links.get("next"):
                break
            if len(values) < size:
                break
            if not values:
                break
            current_offset += len(values)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "JsmOpsClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
