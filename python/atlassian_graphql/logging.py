from __future__ import annotations

import logging
from typing import Dict, Mapping


def get_logger(logger: logging.Logger | None = None) -> logging.Logger:
    return logger if logger is not None else logging.getLogger("atlassian_graphql")


def sanitize_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    sensitive = {"authorization", "cookie"}
    sanitized: Dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in sensitive:
            sanitized[key] = "<redacted>"
        else:
            sanitized[key] = value
    return sanitized
