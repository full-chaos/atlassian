from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from .models import GraphQLErrorItem


class TransportError(Exception):
    def __init__(self, status_code: int, body_snippet: str):
        super().__init__(f"Unexpected HTTP status {status_code}")
        self.status_code = status_code
        self.body_snippet = body_snippet


class RateLimitError(Exception):
    def __init__(
        self,
        retry_after: Optional[datetime],
        attempts: int,
        header_value: Optional[str],
        wait_seconds: Optional[float] = None,
        max_wait_seconds: Optional[float] = None,
    ):
        message = "Rate limited"
        if retry_after:
            message = f"{message}; retry_at={retry_after.isoformat()}"
        if header_value:
            message = f"{message}; Retry-After={header_value}"
        if wait_seconds is not None and max_wait_seconds is not None:
            message = (
                f"{message}; wait_seconds={round(wait_seconds, 3)}"
                f"; max_wait_seconds={max_wait_seconds}"
            )
        super().__init__(message)
        self.retry_after = retry_after
        self.attempts = attempts
        self.header_value = header_value
        self.wait_seconds = wait_seconds
        self.max_wait_seconds = max_wait_seconds


class LocalRateLimitError(Exception):
    def __init__(
        self,
        estimated_cost: float,
        wait_seconds: float,
        max_wait_seconds: float,
    ):
        super().__init__(
            f"local rate limit exceeded; estimated_cost={estimated_cost}; "
            f"wait_seconds={round(wait_seconds, 3)} exceeds "
            f"max_wait_seconds={max_wait_seconds}"
        )
        self.estimated_cost = estimated_cost
        self.wait_seconds = wait_seconds
        self.max_wait_seconds = max_wait_seconds


class GraphQLOperationError(Exception):
    def __init__(
        self,
        errors: List[GraphQLErrorItem],
        partial_data: Optional[Any] = None,
    ):
        message = "GraphQL operation failed"
        if errors:
            first = errors[0]
            message = first.message
            if first.path:
                message = f"{message}; path={first.path}"
            if isinstance(first.extensions, dict):
                required_scopes = (
                    first.extensions.get("requiredScopes")
                    or first.extensions.get("required_scopes")
                    or first.extensions.get("required_scopes_any")
                    or first.extensions.get("required_scopes_all")
                )
                if required_scopes:
                    message = f"{message}; required_scopes={required_scopes}"
        super().__init__(message)
        self.errors = errors
        self.partial_data = partial_data


GraphQLError = GraphQLOperationError


class SerializationError(Exception):
    pass
