from __future__ import annotations

from typing import Optional

from ...canonical_models import JiraProject
from ..gen.jira_api import Project as RestProject


def _normalize_project_type(value: str) -> str:
    return value.strip().upper().replace("-", "_").replace(" ", "_")


def map_rest_project(*, cloud_id: str, project: RestProject) -> JiraProject:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if project is None:
        raise ValueError("project is required")

    key = (project.key or "").strip()
    if not key:
        raise ValueError("project.key is required")

    name = (project.name or "").strip()
    if not name:
        raise ValueError("project.name is required")

    project_type: Optional[str] = None
    raw_type = (project.project_type_key or "").strip()
    if raw_type:
        project_type = _normalize_project_type(raw_type)

    return JiraProject(
        cloud_id=cloud_id_clean,
        key=key,
        name=name,
        type=project_type,
    )
