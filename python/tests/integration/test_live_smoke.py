import json
import logging
import os

import pytest

from atlassian_graphql import (
    BasicApiTokenAuth,
    CookieAuth,
    GraphQLClient,
    OAuthBearerAuth,
    RateLimitError,
)


def _get_auth():
    token = os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
    email = os.getenv("ATLASSIAN_EMAIL")
    api_token = os.getenv("ATLASSIAN_API_TOKEN")
    cookies_json = os.getenv("ATLASSIAN_COOKIES_JSON")

    if token:
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
    return os.getenv("ATLASSIAN_GQL_BASE_URL")


def test_live_smoke(caplog):
    base_url = _base_url()
    auth = _get_auth()
    if not base_url or auth is None:
        pytest.skip("Integration credentials not provided")

    logger = logging.getLogger("atlassian_graphql.integration")
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
