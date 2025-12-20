import json
import logging
import os
from pathlib import Path

import pytest

from atlassian import (
    BasicApiTokenAuth,
    CookieAuth,
    GraphQLOperationError,
    GraphQLClient,
    OAuthBearerAuth,
    OAuthRefreshTokenAuth,
)
from atlassian.graph.api.jira_projects import iter_projects_with_opsgenie_linkable_teams


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


def _base_url():
    base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
    if base_url:
        return base_url
    if os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN") or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN"):
        return "https://api.atlassian.com"
    return None


def _cloud_id():
    return os.getenv("ATLASSIAN_CLOUD_ID") or os.getenv("ATLASSIAN_JIRA_CLOUD_ID")


def _experimental_apis():
    raw = os.getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def test_live_jira_projects_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    base_url = _base_url()
    if not base_url:
        pytest.skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")

    cloud_id = _cloud_id()
    if not cloud_id:
        pytest.fail(
            "ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira projects integration tests"
        )

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)

    it = iter_projects_with_opsgenie_linkable_teams(
        client,
        cloud_id=cloud_id,
        project_types=["SOFTWARE"],
        page_size=50,
        experimental_apis=_experimental_apis() or None,
    )
    try:
        first = next(it, None)
    except GraphQLOperationError as exc:
        provided_scopes: set[str] = set()
        required_scopes: set[str] = set()
        for err in exc.errors or []:
            if isinstance(getattr(err, "extensions", None), dict):
                provided = err.extensions.get("providedScopes")
                if isinstance(provided, list):
                    for item in provided:
                        if isinstance(item, str) and item:
                            provided_scopes.add(item)

                raw = (
                    err.extensions.get("requiredScopes")
                    or err.extensions.get("required_scopes")
                    or err.extensions.get("required_scopes_any")
                    or err.extensions.get("required_scopes_all")
                )
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, str) and item:
                            required_scopes.add(item)
                elif isinstance(raw, str) and raw:
                    required_scopes.add(raw)

        is_oauth = isinstance(auth, (OAuthBearerAuth, OAuthRefreshTokenAuth))
        if is_oauth and "jira:atlassian-external" in required_scopes:
            pytest.skip(
                "AGG returned required_scopes=['jira:atlassian-external'] for jira.allJiraProjects. "
                f"Your token provided scopes={sorted(provided_scopes) if provided_scopes else 'unknown'}. "
                "This appears to be a non-standard OAuth scope; if you can't obtain it via Atlassian 3LO, "
                "run this integration test with tenanted gateway auth (ATLASSIAN_GQL_BASE_URL=https://<site>.atlassian.net/gateway/api + "
                "ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN or ATLASSIAN_COOKIES_JSON)."
            )
        raise
    finally:
        it.close()
    if first is not None:
        assert first.project.cloud_id == cloud_id
        assert first.project.key
        assert first.project.name
    client.close()
