import json
import logging
import os
from pathlib import Path

import pytest

from atlassian import (
    BasicApiTokenAuth,
    CookieAuth,
    JiraRestClient,
    OAuthBearerAuth,
    OAuthRefreshTokenAuth,
    RateLimitError,
)
from atlassian.rest.api.jira_changelog import iter_issue_changelog_via_rest
from atlassian.rest.api.jira_issues import iter_issues_via_rest
from atlassian.rest.api.jira_worklogs import iter_issue_worklogs_via_rest


def _load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def _get_auth():
    token = os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
    refresh_token = os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
    client_id = os.getenv("ATLASSIAN_CLIENT_ID")
    client_secret = os.getenv("ATLASSIAN_CLIENT_SECRET")
    email = os.getenv("ATLASSIAN_EMAIL")
    api_token = os.getenv("ATLASSIAN_API_TOKEN")
    cookies_json = os.getenv("ATLASSIAN_COOKIES_JSON")

    if refresh_token and client_id and client_secret:
        return OAuthRefreshTokenAuth(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
    if token:
        if client_secret and token.strip() == client_secret.strip():
            pytest.fail(
                "ATLASSIAN_OAUTH_ACCESS_TOKEN appears to be set to ATLASSIAN_CLIENT_SECRET; "
                "set an actual OAuth access token (not the client secret)."
            )
        return OAuthBearerAuth(lambda: token)
    if email and api_token:
        return BasicApiTokenAuth(email, api_token)
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
            if isinstance(cookies, dict):
                return CookieAuth(cookies)
        except json.JSONDecodeError:
            pass
    return None


def _derive_site_base_url_from_gql_base(gql_base_url: str):
    candidate = (gql_base_url or "").strip().rstrip("/")
    if not candidate:
        return None
    for suffix in ("/gateway/api/graphql", "/gateway/api", "/graphql"):
        if candidate.endswith(suffix):
            return candidate[: -len(suffix)].rstrip("/")
    return None


def _jira_base_url(auth, cloud_id: str):
    explicit = os.getenv("ATLASSIAN_JIRA_BASE_URL")
    if explicit:
        return explicit.strip().rstrip("/")

    if isinstance(auth, (OAuthBearerAuth, OAuthRefreshTokenAuth)):
        return f"https://api.atlassian.com/ex/jira/{cloud_id}"

    gql_base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
    if gql_base_url:
        return _derive_site_base_url_from_gql_base(gql_base_url)
    return None


def _cloud_id():
    return os.getenv("ATLASSIAN_CLOUD_ID") or os.getenv("ATLASSIAN_JIRA_CLOUD_ID")


def _jql():
    return os.getenv("ATLASSIAN_JIRA_JQL")


def _issue_key():
    return os.getenv("ATLASSIAN_JIRA_ISSUE_KEY")


def test_live_jira_issues_rest_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    cloud_id = _cloud_id()
    if not cloud_id:
        pytest.fail(
            "ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira REST integration tests"
        )

    jql = _jql()
    if not jql:
        pytest.skip("ATLASSIAN_JIRA_JQL not set")

    base_url = _jira_base_url(auth, cloud_id)
    if not base_url:
        pytest.skip(
            "ATLASSIAN_JIRA_BASE_URL not set and could not derive Jira base URL "
            "(set ATLASSIAN_JIRA_BASE_URL or ATLASSIAN_GQL_BASE_URL for tenanted auth)"
        )

    logger = logging.getLogger("atlassian.integration")
    client = JiraRestClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)
    try:
        it = iter_issues_via_rest(client, cloud_id=cloud_id, jql=jql, page_size=1)
        try:
            first = next(it, None)
        except RateLimitError as exc:
            pytest.skip(f"Rate limited during integration; {exc}")
        if first is not None:
            assert first.cloud_id == cloud_id
            assert first.key
            assert first.project_key
            assert first.issue_type
            assert first.status
            assert first.created_at
            assert first.updated_at
    finally:
        client.close()


def test_live_jira_issue_history_rest_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    cloud_id = _cloud_id()
    if not cloud_id:
        pytest.fail(
            "ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira REST integration tests"
        )

    issue_key = _issue_key()
    if not issue_key:
        pytest.skip("ATLASSIAN_JIRA_ISSUE_KEY not set")

    base_url = _jira_base_url(auth, cloud_id)
    if not base_url:
        pytest.skip(
            "ATLASSIAN_JIRA_BASE_URL not set and could not derive Jira base URL "
            "(set ATLASSIAN_JIRA_BASE_URL or ATLASSIAN_GQL_BASE_URL for tenanted auth)"
        )

    logger = logging.getLogger("atlassian.integration")
    client = JiraRestClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)
    try:
        try:
            next(iter_issue_changelog_via_rest(client, issue_key=issue_key, page_size=1), None)
            next(iter_issue_worklogs_via_rest(client, issue_key=issue_key, page_size=1), None)
        except RateLimitError as exc:
            pytest.skip(f"Rate limited during integration; {exc}")
    finally:
        client.close()
