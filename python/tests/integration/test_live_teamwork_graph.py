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
    SerializationError,
)
from atlassian.graph.api.teamwork_graph import iter_team_active_projects, iter_user_teams


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


def _experimental_apis():
    raw = os.getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def test_live_teamwork_team_active_projects_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    base_url = _base_url()
    if not base_url:
        pytest.skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")

    team_id = os.getenv("ATLASSIAN_TEST_TEAM_ID")
    if not team_id:
        pytest.skip("ATLASSIAN_TEST_TEAM_ID not set; skipping teamwork active projects integration test")

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)

    it = iter_team_active_projects(
        client,
        team_id=team_id,
        first=10,
    )
    try:
        first = next(it, None)
    except SerializationError as exc:
        pytest.skip(f"Teamwork Graph API returned no data (EAP API may not be available): {exc}")
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
        if is_oauth and required_scopes:
            pytest.skip(
                f"AGG returned required_scopes={sorted(required_scopes)} for TeamworkGraph_teamActiveProjects. "
                f"Your token provided scopes={sorted(provided_scopes) if provided_scopes else 'unknown'}. "
                "Teamwork Graph APIs are EAP and may not be available for OAuth-authenticated requests."
            )
        raise
    finally:
        it.close()

    # first may be None if the team has no active projects; that is acceptable
    if first is not None:
        assert first.team_id, "project.team_id should be non-empty"
        assert first.project_id, "project.project_id should be non-empty"

    client.close()


def test_live_teamwork_user_teams_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    base_url = _base_url()
    if not base_url:
        pytest.skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")

    user_id = os.getenv("ATLASSIAN_TEST_USER_ID")
    if not user_id:
        pytest.skip("ATLASSIAN_TEST_USER_ID not set; skipping teamwork user teams integration test")

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)

    it = iter_user_teams(
        client,
        user_id=user_id,
        first=10,
    )
    try:
        first = next(it, None)
    except SerializationError as exc:
        pytest.skip(f"Teamwork Graph API returned no data (EAP API may not be available): {exc}")
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
        if is_oauth and required_scopes:
            pytest.skip(
                f"AGG returned required_scopes={sorted(required_scopes)} for TeamworkGraph_userTeams. "
                f"Your token provided scopes={sorted(provided_scopes) if provided_scopes else 'unknown'}. "
                "Teamwork Graph APIs are EAP and may not be available for OAuth-authenticated requests."
            )
        raise
    finally:
        it.close()

    if first is not None:
        assert first.subject_user_id, "relation.subject_user_id should be non-empty"
        assert first.relation_type, "relation.relation_type should be non-empty"

    client.close()
