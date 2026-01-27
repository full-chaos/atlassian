from __future__ import annotations

from typing import Iterator, List, Sequence

from ...canonical_models import CanonicalProjectWithOpsgenieTeams, JiraProject
from ...errors import SerializationError
from ..client import JiraRestClient
from ..env import auth_from_env, jira_rest_base_url_from_env
from ..gen import jira_api as api
from ..mappers.jira_projects import map_rest_project


def _normalize_project_types(project_types: Sequence[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in project_types:
        if not isinstance(raw, str):
            raise ValueError("project_types must be strings")
        value = raw.strip().upper()
        if not value:
            continue
        cleaned.append(value)
    if not cleaned:
        raise ValueError("project_types must be non-empty")
    return cleaned


def iter_projects_via_rest(
    client: JiraRestClient,
    cloud_id: str,
    project_types: Sequence[str],
    page_size: int = 50,
) -> Iterator[CanonicalProjectWithOpsgenieTeams]:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    normalized_types = set(_normalize_project_types(project_types))
    start_at = 0
    seen_start_at: set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError(
                "Pagination startAt repeated; aborting to prevent infinite loop"
            )
        seen_start_at.add(start_at)

        payload = client.get_json(
            "/rest/api/3/project/search",
            params={"startAt": start_at, "maxResults": page_size},
        )
        page = api.PageBeanProject.from_dict(payload, "data")
        values = page.values

        for item in values:
            project: JiraProject = map_rest_project(
                cloud_id=cloud_id_clean, project=item
            )
            if project.type is None:
                continue
            if project.type not in normalized_types:
                continue
            yield CanonicalProjectWithOpsgenieTeams(project=project, opsgenie_teams=[])

        has_is_last = isinstance(page.is_last, bool)
        if has_is_last and page.is_last:
            break

        has_total = isinstance(page.total, int) and page.total >= 0
        if has_total:
            if start_at + len(values) >= page.total:
                break
        else:
            if len(values) < page_size:
                break

        if len(values) == 0:
            if has_is_last and not page.is_last:
                raise SerializationError(
                    "Received empty page with isLast=false; cannot continue pagination"
                )
            break
        start_at += len(values)


def list_projects_via_rest(
    cloud_id: str,
    project_types: List[str],
    page_size: int = 50,
) -> Iterator[CanonicalProjectWithOpsgenieTeams]:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")

    auth = auth_from_env()
    if auth is None:
        raise ValueError(
            "Missing credentials. Set ATLASSIAN_OAUTH_ACCESS_TOKEN, or "
            "ATLASSIAN_OAUTH_REFRESH_TOKEN + (ATLASSIAN_CLIENT_ID + ATLASSIAN_CLIENT_SECRET), "
            "or (ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN), or ATLASSIAN_COOKIES_JSON."
        )

    base_url = jira_rest_base_url_from_env(cloud_id_clean)
    if not base_url:
        raise ValueError(
            "Missing Jira REST base URL. Set ATLASSIAN_JIRA_BASE_URL, or "
            "provide ATLASSIAN_CLOUD_ID with OAuth tokens (defaults to "
            "https://api.atlassian.com/ex/jira/{cloudId}), or provide "
            "ATLASSIAN_GQL_BASE_URL for tenanted auth so it can be derived."
        )

    with JiraRestClient(
        base_url, auth=auth, timeout_seconds=30.0, max_retries_429=1
    ) as client:
        yield from iter_projects_via_rest(
            client, cloud_id_clean, project_types, page_size
        )


def create_project_via_rest(
    cloud_id: str,
    project: JiraProject,
) -> JiraProject:
    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env(cloud_id)
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        data = {
            "key": project.key,
            "name": project.name,
            "projectTypeKey": project.type or "software",
            "leadAccountId": "...",  # Need more info or handle via terraform?
        }
        # In practice, and for Terraform automation, leadAccountId is often required.
        # But maybe we just post what we have for now.
        payload = client.post_json("/rest/api/3/project", json_data=data)
        return map_rest_project(
            cloud_id=cloud_id, project=api.Project.from_dict(payload, "data")
        )


def delete_project_via_rest(
    cloud_id: str,
    project_key_or_id: str,
) -> None:
    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env(cloud_id)
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        client.delete(f"/rest/api/3/project/{project_key_or_id}")
