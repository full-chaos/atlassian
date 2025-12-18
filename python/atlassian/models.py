from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GraphQLErrorItem:
    message: str
    path: Optional[List[Any]] = None
    extensions: Optional[Dict[str, Any]] = None
    locations: Optional[List[Dict[str, Any]]] = None


@dataclass
class GraphQLResult:
    data: Optional[Dict[str, Any]]
    errors: Optional[List[GraphQLErrorItem]]
    extensions: Optional[Dict[str, Any]]


def parse_error_items(raw_errors: Any) -> Optional[List[GraphQLErrorItem]]:
    if raw_errors is None:
        return None
    items: List[GraphQLErrorItem] = []
    if not isinstance(raw_errors, list):
        return None
    for err in raw_errors:
        if not isinstance(err, dict):
            continue
        message = err.get("message")
        if not isinstance(message, str):
            continue
        items.append(
            GraphQLErrorItem(
                message=message,
                path=err.get("path"),
                extensions=err.get("extensions"),
                locations=err.get("locations"),
            )
        )
    return items
