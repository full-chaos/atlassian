from __future__ import annotations

from typing import Iterator

from ...canonical_models import JiraVersion
from ...errors import SerializationError
from ..client import JiraRestClient
from ..env import auth_from_env, jira_rest_base_url_from_env
from ..gen import jira_api as api
from ..mappers.jira_versions import map_rest_version


def iter_versions_via_rest(
    client: JiraRestClient,
    project_key_or_id: str,
    page_size: int = 50,
) -> Iterator[JiraVersion]:
    project_clean = (project_key_or_id or "").strip()
    if not project_clean:
        raise ValueError("project_key_or_id is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    start_at = 0
    seen_start_at: set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError(
                "Pagination startAt repeated; aborting to prevent infinite loop"
            )
        seen_start_at.add(start_at)

        payload = client.get_json(
            f"/rest/api/3/project/{project_clean}/version",
            params={"startAt": start_at, "maxResults": page_size},
        )
        page = api.PageBeanVersion.from_dict(payload, "data")
        values = page.values

        for item in values:
            yield map_rest_version(project_key=project_clean, version=item)

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


def list_versions_via_rest(
    project_key_or_id: str,
    page_size: int = 50,
) -> Iterator[JiraVersion]:
    project_clean = (project_key_or_id or "").strip()
    if not project_clean:
        raise ValueError("project_key_or_id is required")

    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    # Using a dummy cloud_id for URL derivation if needed, but usually derived from env
    base_url = jira_rest_base_url_from_env("")
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        yield from iter_versions_via_rest(client, project_clean, page_size)


def create_version_via_rest(
    version: JiraVersion,
) -> JiraVersion:
    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env("")
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        data = {
            "name": version.name,
            "project": version.project_key,
            "released": version.released,
        }
        if version.release_date:
            data["releaseDate"] = version.release_date

        payload = client.post_json("/rest/api/3/version", json_data=data)
        return map_rest_version(
            project_key=version.project_key,
            version=api.Version.from_dict(payload, "data"),
        )


def update_version_via_rest(
    version: JiraVersion,
) -> JiraVersion:
    if not version.id:
        raise ValueError("version.id is required for update")

    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env("")
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        data = {
            "name": version.name,
            "released": version.released,
        }
        if version.release_date:
            data["releaseDate"] = version.release_date

        payload = client.put_json(f"/rest/api/3/version/{version.id}", json_data=data)
        return map_rest_version(
            project_key=version.project_key,
            version=api.Version.from_dict(payload, "data"),
        )


def delete_version_via_rest(
    version_id: str,
) -> None:
    if not version_id:
        raise ValueError("version_id is required for delete")

    auth = auth_from_env()
    if auth is None:
        raise ValueError("Missing credentials.")

    base_url = jira_rest_base_url_from_env("")
    if not base_url:
        raise ValueError("Missing Jira REST base URL.")

    with JiraRestClient(base_url, auth=auth) as client:
        client.delete(f"/rest/api/3/version/{version_id}")
