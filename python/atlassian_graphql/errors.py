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
        first = errors[0].message if errors else "GraphQL operation failed"
        super().__init__(first)
        self.errors = errors
        self.partial_data = partial_data


GraphQLError = GraphQLOperationError


class SerializationError(Exception):
    pass
