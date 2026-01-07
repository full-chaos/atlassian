from __future__ import annotations

import os
from typing import Iterator, List, Optional, Sequence

from ...canonical_models import JiraIssue
from ...errors import SerializationError
from ..client import JiraRestClient
from ..env import auth_from_env, jira_rest_base_url_from_env
from ..gen import jira_api as api
from ..mappers.jira_issues import map_issue


_DEFAULT_SEARCH_FIELDS = (
    "project",
    "issuetype",
    "status",
    "created",
    "updated",
    "resolutiondate",
    "assignee",
    "reporter",
    "labels",
    "components",
)


def _build_field_list(
    fields: Optional[Sequence[str]],
    story_points_field: Optional[str],
    sprint_ids_field: Optional[str],
) -> List[str]:
    field_list = [f.strip() for f in (fields or _DEFAULT_SEARCH_FIELDS) if f and f.strip()]
    if not field_list:
        raise ValueError("fields must be non-empty")
    for raw in (story_points_field, sprint_ids_field):
        if raw is None:
            continue
        extra = raw.strip()
        if not extra:
            raise ValueError("custom field names must be non-empty when provided")
        if extra not in field_list:
            field_list.append(extra)
    return field_list


def _env_custom_field(env_name: str) -> Optional[str]:
    raw = os.getenv(env_name)
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def iter_issues_via_rest(
    client: JiraRestClient,
    cloud_id: str,
    jql: str,
    page_size: int = 50,
    *,
    fields: Optional[Sequence[str]] = None,
    story_points_field: Optional[str] = None,
    sprint_ids_field: Optional[str] = None,
) -> Iterator[JiraIssue]:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")
    jql_clean = (jql or "").strip()
    if not jql_clean:
        raise ValueError("jql is required")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")

    if story_points_field is None:
        story_points_field = _env_custom_field("ATLASSIAN_JIRA_STORY_POINTS_FIELD")
    if sprint_ids_field is None:
        sprint_ids_field = _env_custom_field("ATLASSIAN_JIRA_SPRINT_IDS_FIELD")

    field_list = _build_field_list(fields, story_points_field, sprint_ids_field)
    fields_param = ",".join(field_list)

    start_at = 0
    seen_start_at: set[int] = set()

    while True:
        if start_at in seen_start_at:
            raise SerializationError("Pagination startAt repeated; aborting to prevent infinite loop")
        seen_start_at.add(start_at)

        payload = client.get_json(
            "/rest/api/3/search",
            params={
                "jql": jql_clean,
                "startAt": start_at,
                "maxResults": page_size,
                "fields": fields_param,
            },
        )
        page = api.SearchResults.from_dict(payload, "data")
        issues = page.issues

        for issue in issues:
            yield map_issue(
                cloud_id=cloud_id_clean,
                issue=issue,
                story_points_field=story_points_field,
                sprint_ids_field=sprint_ids_field,
            )

        has_total = isinstance(page.total, int) and page.total >= 0
        if has_total:
            if start_at + len(issues) >= page.total:
                break
        else:
            if len(issues) < page_size:
                break

        if len(issues) == 0:
            break
        start_at += len(issues)


def list_issues_via_rest(
    cloud_id: str,
    jql: str,
    page_size: int = 50,
    *,
    fields: Optional[Sequence[str]] = None,
    story_points_field: Optional[str] = None,
    sprint_ids_field: Optional[str] = None,
) -> Iterator[JiraIssue]:
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
            "provide ATLASSIAN_CLOUD_ID with OAuth tokens (defaults to https://api.atlassian.com/ex/jira/{cloudId}), "
            "or provide ATLASSIAN_GQL_BASE_URL for tenanted auth so it can be derived."
        )

    if story_points_field is None:
        story_points_field = _env_custom_field("ATLASSIAN_JIRA_STORY_POINTS_FIELD")
    if sprint_ids_field is None:
        sprint_ids_field = _env_custom_field("ATLASSIAN_JIRA_SPRINT_IDS_FIELD")

    with JiraRestClient(base_url, auth=auth, timeout_seconds=30.0, max_retries_429=1) as client:
        yield from iter_issues_via_rest(
            client,
            cloud_id=cloud_id_clean,
            jql=jql,
            page_size=page_size,
            fields=fields,
            story_points_field=story_points_field,
            sprint_ids_field=sprint_ids_field,
        )
