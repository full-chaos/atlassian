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
from atlassian.graph.api.compass_components import (
    iter_compass_components,
    iter_compass_component_scorecard_scores,
)


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


def test_live_compass_search_components_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    base_url = _base_url()
    if not base_url:
        pytest.skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")

    cloud_id = _cloud_id()
    if not cloud_id:
        pytest.skip("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) not set; skipping Compass components integration test")

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)

    it = iter_compass_components(
        client,
        cloud_id=cloud_id,
        page_size=10,
        experimental_apis=_experimental_apis() or None,
    )
    try:
        first = next(it, None)
    except SerializationError as exc:
        pytest.skip(f"Compass API returned no data (API may not be enabled on this cloud): {exc}")
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
                f"AGG returned required_scopes={sorted(required_scopes)} for compass.searchComponents. "
                f"Your token provided scopes={sorted(provided_scopes) if provided_scopes else 'unknown'}. "
                "This may require additional OAuth scopes or tenanted gateway auth."
            )
        raise
    finally:
        it.close()

    if first is not None:
        assert first.id, "component.id should be non-empty"
        assert first.name, "component.name should be non-empty"
        assert first.type, "component.type should be non-empty"
        assert first.cloud_id == cloud_id, f"component.cloud_id should match; got {first.cloud_id!r}"

    client.close()


def test_live_compass_scorecards_smoke():
    _load_dotenv_if_present()
    auth = _get_auth()
    if auth is None:
        pytest.skip("Integration credentials not provided")

    base_url = _base_url()
    if not base_url:
        pytest.skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")

    cloud_id = _cloud_id()
    if not cloud_id:
        pytest.skip("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) not set; skipping Compass scorecards integration test")

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(base_url, auth=auth, timeout_seconds=30.0, logger=logger, max_retries_429=1)

    # First, get a component to use for scorecard lookup
    components_it = iter_compass_components(
        client,
        cloud_id=cloud_id,
        page_size=1,
        experimental_apis=_experimental_apis() or None,
    )
    try:
        component = next(components_it, None)
    except (GraphQLOperationError, SerializationError):
        components_it.close()
        client.close()
        pytest.skip("Could not fetch Compass components; skipping scorecards test")
    finally:
        components_it.close()

    if component is None:
        client.close()
        pytest.skip("No Compass components found; skipping scorecards test")

    scores_it = iter_compass_component_scorecard_scores(
        client,
        component_id=component.id,
        experimental_apis=_experimental_apis() or None,
    )
    try:
        scores = list(scores_it)
    except SerializationError as exc:
        pytest.skip(f"Compass scorecard API returned no data: {exc}")
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
                f"AGG returned required_scopes={sorted(required_scopes)} for compass.component.appliedScorecards. "
                f"Your token provided scopes={sorted(provided_scopes) if provided_scopes else 'unknown'}."
            )
        raise
    finally:
        scores_it.close()

    # scores may be empty if no scorecards are configured; that is acceptable
    assert isinstance(scores, list), "scorecard scores result should be a list"
    for score in scores:
        assert score.component_id == component.id
        assert score.scorecard_id

    client.close()
