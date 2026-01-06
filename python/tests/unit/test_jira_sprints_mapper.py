import pytest

from atlassian.rest.gen.jira_agile_api import Sprint
from atlassian.rest.mappers.jira_sprints import map_sprint


def test_sprint_mapper_trims_fields():
    sprint = Sprint(
        id=100,
        name="  Sprint 1  ",
        state="  active  ",
        start_date="  2021-01-01T00:00:00.000Z  ",
        end_date="  2021-01-15T00:00:00.000Z  ",
        complete_date=None,
        origin_board_id=10,
        goal="  Goal text  ",
    )
    mapped = map_sprint(sprint=sprint)
    assert mapped.id == "100"
    assert mapped.name == "Sprint 1"
    assert mapped.state == "active"
    assert mapped.start_at == "2021-01-01T00:00:00.000Z"
    assert mapped.end_at == "2021-01-15T00:00:00.000Z"
    assert mapped.complete_at is None


def test_sprint_mapper_handles_optional_dates():
    sprint = Sprint(
        id=101,
        name="Sprint 2",
        state="closed",
        start_date=None,
        end_date=None,
        complete_date="2021-01-30T12:00:00.000Z",
        origin_board_id=None,
        goal=None,
    )
    mapped = map_sprint(sprint=sprint)
    assert mapped.id == "101"
    assert mapped.name == "Sprint 2"
    assert mapped.state == "closed"
    assert mapped.start_at is None
    assert mapped.end_at is None
    assert mapped.complete_at == "2021-01-30T12:00:00.000Z"


def test_sprint_mapper_requires_id():
    sprint = Sprint(
        id=None,
        name="Sprint",
        state="active",
        start_date=None,
        end_date=None,
        complete_date=None,
        origin_board_id=None,
        goal=None,
    )
    with pytest.raises(ValueError, match="sprint.id is required"):
        map_sprint(sprint=sprint)


def test_sprint_mapper_requires_name():
    sprint = Sprint(
        id=100,
        name="",
        state="active",
        start_date=None,
        end_date=None,
        complete_date=None,
        origin_board_id=None,
        goal=None,
    )
    with pytest.raises(ValueError, match="sprint.name is required"):
        map_sprint(sprint=sprint)


def test_sprint_mapper_requires_name_not_whitespace():
    sprint = Sprint(
        id=100,
        name="   ",
        state="active",
        start_date=None,
        end_date=None,
        complete_date=None,
        origin_board_id=None,
        goal=None,
    )
    with pytest.raises(ValueError, match="sprint.name is required"):
        map_sprint(sprint=sprint)


def test_sprint_mapper_requires_state():
    sprint = Sprint(
        id=100,
        name="Sprint",
        state="",
        start_date=None,
        end_date=None,
        complete_date=None,
        origin_board_id=None,
        goal=None,
    )
    with pytest.raises(ValueError, match="sprint.state is required"):
        map_sprint(sprint=sprint)


def test_sprint_mapper_requires_sprint():
    with pytest.raises(ValueError, match="sprint is required"):
        map_sprint(sprint=None)  # type: ignore[arg-type]
