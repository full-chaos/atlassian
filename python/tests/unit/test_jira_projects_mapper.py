import pytest

from atlassian.graph.gen.jira_projects_api import JiraProjectNode, OpsgenieTeamNode
from atlassian.graph.mappers.jira_projects import map_project_with_opsgenie_teams


def test_project_mapper_trims_and_dedups_teams():
    project = JiraProjectNode(id="projA", key="  KEY  ", name="  Name  ", opsgenie_teams=None)  # type: ignore[arg-type]
    teams = [
        OpsgenieTeamNode(id="  t1 ", name=" Team 1 "),
        OpsgenieTeamNode(id="t1", name="Team 1 duplicate"),
        OpsgenieTeamNode(id="t2", name="Team 2"),
    ]
    mapped = map_project_with_opsgenie_teams(
        cloud_id=" cloud ",
        project=project,
        opsgenie_teams=teams,
    )
    assert mapped.project.cloud_id == "cloud"
    assert mapped.project.key == "KEY"
    assert mapped.project.name == "Name"
    assert [t.id for t in mapped.opsgenie_teams] == ["t1", "t2"]
    assert mapped.opsgenie_teams[0].name == "Team 1"


def test_project_mapper_requires_fields():
    project = JiraProjectNode(id="p", key="", name="n", opsgenie_teams=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="project.key"):
        map_project_with_opsgenie_teams(cloud_id="c", project=project, opsgenie_teams=[])
