from __future__ import annotations

from ...canonical_models import JiraBoard
from ..gen import jira_agile_api as api


def map_rest_board(board: api.Board) -> JiraBoard:
    return JiraBoard(
        id=str(board.id) if board.id is not None else "",
        name=board.name or "",
        type=board.board_type or "",
    )
