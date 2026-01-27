from __future__ import annotations

import os
from typing import Iterator, Optional

from ...canonical_models import (
    AtlassianOpsAlert,
    AtlassianOpsIncident,
    AtlassianOpsSchedule,
)
from ..client import GraphQLClient


def iter_issue_incidents_via_graphql(
    client: GraphQLClient,
    *,
    cloud_id: str,
    issue_key: str,
) -> Iterator[AtlassianOpsIncident]:
    # Placeholder for now until we have the generated query
    # In a real scenario, we'd use api.JIRA_ISSUE_INCIDENTS_QUERY
    yield from []


def iter_project_alerts_via_graphql(
    client: GraphQLClient,
    *,
    cloud_id: str,
    project_key: str,
) -> Iterator[AtlassianOpsAlert]:
    yield from []


def iter_project_schedules_via_graphql(
    client: GraphQLClient,
    *,
    cloud_id: str,
    project_key: str,
) -> Iterator[AtlassianOpsSchedule]:
    yield from []
