from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class JiraUser:
    account_id: str
    display_name: str
    email: Optional[str] = None


@dataclass(frozen=True)
class JiraProject:
    cloud_id: str
    key: str
    name: str
    type: Optional[str] = None


@dataclass(frozen=True)
class JiraSprint:
    id: str
    name: str
    state: str
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    complete_at: Optional[str] = None


@dataclass(frozen=True)
class JiraIssue:
    cloud_id: str
    key: str
    project_key: str
    issue_type: str
    status: str
    created_at: str
    updated_at: str
    resolved_at: Optional[str] = None
    assignee: Optional[JiraUser] = None
    reporter: Optional[JiraUser] = None
    labels: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    story_points: Optional[float] = None
    sprint_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class JiraChangelogItem:
    field: str
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    from_string: Optional[str] = None
    to_string: Optional[str] = None


@dataclass(frozen=True)
class JiraChangelogEvent:
    issue_key: str
    event_id: str
    created_at: str
    items: List[JiraChangelogItem]
    author: Optional[JiraUser] = None


@dataclass(frozen=True)
class JiraWorklog:
    issue_key: str
    worklog_id: str
    started_at: str
    time_spent_seconds: int
    created_at: str
    updated_at: str
    author: Optional[JiraUser] = None


@dataclass(frozen=True)
class OpsgenieTeamRef:
    id: str
    name: str


@dataclass(frozen=True)
class CanonicalProjectWithOpsgenieTeams:
    project: JiraProject
    opsgenie_teams: List[OpsgenieTeamRef] = field(default_factory=list)


@dataclass(frozen=True)
class JiraBoard:
    id: str
    name: str
    type: str  # scrum, kanban


@dataclass(frozen=True)
class JiraVersion:
    id: str
    name: str
    project_key: str
    released: bool
    release_date: Optional[str] = None


@dataclass(frozen=True)
class AtlassianOpsIncident:
    id: str
    url: Optional[str]
    summary: str
    description: Optional[str]
    status: str
    severity: str
    created_at: str
    provider_id: Optional[str] = None


@dataclass(frozen=True)
class AtlassianOpsAlert:
    id: str
    status: str
    priority: str
    created_at: str
    acknowledged_at: Optional[str] = None
    snoozed_at: Optional[str] = None
    closed_at: Optional[str] = None


@dataclass(frozen=True)
class AtlassianOpsSchedule:
    id: str
    name: str
    timezone: Optional[str] = None


@dataclass(frozen=True)
class CompassComponent:
    id: str
    cloud_id: str
    name: str
    type: str  # SERVICE, LIBRARY, etc.
    description: Optional[str] = None
    owner_team_id: Optional[str] = None
    owner_team_name: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class CompassRelationship:
    id: str
    type: str  # DEPENDS_ON, OWNED_BY, etc.
    start_component_id: str
    end_component_id: str


@dataclass(frozen=True)
class CompassScorecardScore:
    component_id: str
    scorecard_id: str
    score: float
    scorecard_name: Optional[str] = None
    max_score: Optional[float] = None
    evaluated_at: Optional[str] = None


@dataclass(frozen=True)
class AtlassianTeam:
    id: str  # ARI format: ari:cloud:identity::team/{uuid}
    display_name: str
    state: str  # ACTIVE, ARCHIVED
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    member_count: Optional[int] = None


@dataclass(frozen=True)
class AtlassianTeamMember:
    team_id: str
    account_id: str
    display_name: Optional[str] = None
    role: Optional[str] = None  # REGULAR, ADMIN


@dataclass(frozen=True)
class TeamworkProject:
    team_id: str
    project_id: str
    project_key: Optional[str] = None
    project_name: Optional[str] = None


@dataclass(frozen=True)
class TeamworkUserRelation:
    subject_user_id: str
    relation_type: str  # TEAM_MEMBER, REPORTS_TO, MANAGES
    team_id: Optional[str] = None
    related_user_id: Optional[str] = None
