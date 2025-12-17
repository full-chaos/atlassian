from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Tuple


def parse_retry_after(header_value: str) -> Tuple[datetime, str]:
    if header_value is None:
        raise ValueError("Retry-After header is missing")
    candidate = header_value.strip()
    if not candidate:
        raise ValueError("Retry-After header is empty")

    cleaned = candidate
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc), "rfc3339"
    except Exception:
        pass

    try:
        parsed = parsedate_to_datetime(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc), "http-date"
    except Exception as exc:  # pragma: no cover - already handled as error
        raise ValueError(f"Unable to parse Retry-After header: {candidate}") from exc
