from __future__ import annotations

from typing import Iterable, List

from ...canonical_models import (
    CanonicalProjectWithOpsgenieTeams,
    JiraProject,
    OpsgenieTeamRef,
)
from ..gen.jira_projects_api import JiraProjectNode, OpsgenieTeamNode


def map_project_with_opsgenie_teams(
    *,
    cloud_id: str,
    project: JiraProjectNode,
    opsgenie_teams: Iterable[OpsgenieTeamNode],
) -> CanonicalProjectWithOpsgenieTeams:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")

    project_key = (project.key or "").strip()
    if not project_key:
        raise ValueError("project.key is required")

    project_name = (project.name or "").strip()
    if not project_name:
        raise ValueError("project.name is required")

    seen: set[str] = set()
    teams: List[OpsgenieTeamRef] = []
    for t in opsgenie_teams:
        team_id = (t.id or "").strip()
        if not team_id:
            raise ValueError("opsgenie_team.id is required")
        if team_id in seen:
            continue
        seen.add(team_id)

        team_name = (t.name or "").strip()
        if not team_name:
            raise ValueError("opsgenie_team.name is required")
        teams.append(OpsgenieTeamRef(id=team_id, name=team_name))

    return CanonicalProjectWithOpsgenieTeams(
        project=JiraProject(cloud_id=cloud_id_clean, key=project_key, name=project_name),
        opsgenie_teams=teams,
    )
