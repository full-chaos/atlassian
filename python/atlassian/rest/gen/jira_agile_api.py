# Jira Agile REST API models for Sprint data.
# Note: The Jira Agile API is separate from the core Jira REST API.
# These models are manually maintained to match the Jira Software Cloud REST API.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from atlassian.errors import SerializationError


def _expect_dict(obj: Any, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise SerializationError(f"Expected object at {path}")
    return obj


def _expect_list(obj: Any, path: str) -> List[Any]:
    if not isinstance(obj, list):
        raise SerializationError(f"Expected list at {path}")
    return obj


def _expect_str(obj: Any, path: str) -> str:
    if not isinstance(obj, str):
        raise SerializationError(f"Expected string at {path}")
    return obj


def _expect_bool(obj: Any, path: str) -> bool:
    if not isinstance(obj, bool):
        raise SerializationError(f"Expected boolean at {path}")
    return obj


def _expect_int(obj: Any, path: str) -> int:
    if isinstance(obj, bool) or not isinstance(obj, int):
        raise SerializationError(f"Expected integer at {path}")
    return obj


@dataclass(frozen=True)
class Sprint:
    """Sprint model from Jira Agile REST API.

    Ref: GET /rest/agile/1.0/board/{boardId}/sprint
    Ref: GET /rest/agile/1.0/sprint/{sprintId}
    """

    id: Optional[int]
    name: Optional[str]
    state: Optional[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    complete_date: Optional[str] = None
    origin_board_id: Optional[int] = None
    goal: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "Sprint":
        raw = _expect_dict(obj, path)
        sprint_id: Optional[int] = None
        if raw.get("id") is not None:
            sprint_id = _expect_int(raw.get("id"), f"{path}.id")
        name: Optional[str] = None
        if raw.get("name") is not None:
            name = _expect_str(raw.get("name"), f"{path}.name")
        state: Optional[str] = None
        if raw.get("state") is not None:
            state = _expect_str(raw.get("state"), f"{path}.state")
        start_date: Optional[str] = None
        if raw.get("startDate") is not None:
            start_date = _expect_str(raw.get("startDate"), f"{path}.startDate")
        end_date: Optional[str] = None
        if raw.get("endDate") is not None:
            end_date = _expect_str(raw.get("endDate"), f"{path}.endDate")
        complete_date: Optional[str] = None
        if raw.get("completeDate") is not None:
            complete_date = _expect_str(raw.get("completeDate"), f"{path}.completeDate")
        origin_board_id: Optional[int] = None
        if raw.get("originBoardId") is not None:
            origin_board_id = _expect_int(raw.get("originBoardId"), f"{path}.originBoardId")
        goal: Optional[str] = None
        if raw.get("goal") is not None:
            goal = _expect_str(raw.get("goal"), f"{path}.goal")
        return Sprint(
            id=sprint_id,
            name=name,
            state=state,
            start_date=start_date,
            end_date=end_date,
            complete_date=complete_date,
            origin_board_id=origin_board_id,
            goal=goal,
        )


@dataclass(frozen=True)
class SprintPage:
    """Paginated list of sprints from Jira Agile REST API.

    Ref: GET /rest/agile/1.0/board/{boardId}/sprint
    """

    start_at: Optional[int]
    max_results: Optional[int]
    is_last: Optional[bool]
    values: List[Sprint]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "SprintPage":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{path}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{path}.maxResults")
        is_last: Optional[bool] = None
        if raw.get("isLast") is not None:
            is_last = _expect_bool(raw.get("isLast"), f"{path}.isLast")
        values_raw = raw.get("values")
        values_list = _expect_list(values_raw, f"{path}.values") if values_raw is not None else []
        values = [
            Sprint.from_dict(item, f"{path}.values[{idx}]")
            for idx, item in enumerate(values_list)
        ]
        return SprintPage(
            start_at=start_at,
            max_results=max_results,
            is_last=is_last,
            values=values,
        )


@dataclass(frozen=True)
class Board:
    """Board model from Jira Agile REST API.

    Ref: GET /rest/agile/1.0/board
    Ref: GET /rest/agile/1.0/board/{boardId}
    """

    id: Optional[int]
    name: Optional[str]
    board_type: Optional[str] = None

    @staticmethod
    def from_dict(obj: Any, path: str) -> "Board":
        raw = _expect_dict(obj, path)
        board_id: Optional[int] = None
        if raw.get("id") is not None:
            board_id = _expect_int(raw.get("id"), f"{path}.id")
        name: Optional[str] = None
        if raw.get("name") is not None:
            name = _expect_str(raw.get("name"), f"{path}.name")
        board_type: Optional[str] = None
        if raw.get("type") is not None:
            board_type = _expect_str(raw.get("type"), f"{path}.type")
        return Board(
            id=board_id,
            name=name,
            board_type=board_type,
        )


@dataclass(frozen=True)
class BoardPage:
    """Paginated list of boards from Jira Agile REST API.

    Ref: GET /rest/agile/1.0/board
    """

    start_at: Optional[int]
    max_results: Optional[int]
    is_last: Optional[bool]
    values: List[Board]

    @staticmethod
    def from_dict(obj: Any, path: str) -> "BoardPage":
        raw = _expect_dict(obj, path)
        start_at: Optional[int] = None
        if raw.get("startAt") is not None:
            start_at = _expect_int(raw.get("startAt"), f"{path}.startAt")
        max_results: Optional[int] = None
        if raw.get("maxResults") is not None:
            max_results = _expect_int(raw.get("maxResults"), f"{path}.maxResults")
        is_last: Optional[bool] = None
        if raw.get("isLast") is not None:
            is_last = _expect_bool(raw.get("isLast"), f"{path}.isLast")
        values_raw = raw.get("values")
        values_list = _expect_list(values_raw, f"{path}.values") if values_raw is not None else []
        values = [
            Board.from_dict(item, f"{path}.values[{idx}]")
            for idx, item in enumerate(values_list)
        ]
        return BoardPage(
            start_at=start_at,
            max_results=max_results,
            is_last=is_last,
            values=values,
        )
