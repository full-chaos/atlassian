from __future__ import annotations

from ...canonical_models import JiraVersion
from ..gen import jira_api as api


def map_rest_version(project_key: str, version: api.Version) -> JiraVersion:
    return JiraVersion(
        id=version.id or "",
        name=version.name or "",
        project_key=project_key,
        released=version.released or False,
        release_date=version.release_date,
    )
