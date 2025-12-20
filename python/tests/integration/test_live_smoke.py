import json
import logging
import os
from pathlib import Path

import pytest

from atlassian import (
    BasicApiTokenAuth,
    CookieAuth,
    GraphQLClient,
    OAuthBearerAuth,
    OAuthRefreshTokenAuth,
    RateLimitError,
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


def test_live_smoke(caplog):
    _load_dotenv_if_present()
    base_url = _base_url()
    auth = _get_auth()
    if not base_url or auth is None:
        pytest.skip("Integration credentials not provided")

    logger = logging.getLogger("atlassian.integration")
    client = GraphQLClient(
        base_url,
        auth=auth,
        timeout_seconds=30.0,
        max_retries_429=1,
        logger=logger,
    )

    with caplog.at_level(logging.DEBUG):
        try:
            result = client.execute("query { __schema { queryType { name } } }")
        except RateLimitError:
            warnings = [
                rec
                for rec in caplog.records
                if rec.levelno >= logging.WARNING
                and "Rate limited" in rec.message
            ]
            assert warnings, "rate limit encountered without warning log"
            assert len(warnings) <= 2
            client.close()
            pytest.skip("Rate limited during integration; warning log captured")
    assert result.data is not None
    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno >= logging.WARNING and "Rate limited" in rec.message
    ]
    assert len(warnings) <= 2
    client.close()
