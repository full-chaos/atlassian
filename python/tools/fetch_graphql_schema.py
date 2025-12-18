from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()

from atlassian.auth import (  # noqa: E402
    BasicApiTokenAuth,
    CookieAuth,
    OAuthBearerAuth,
)
from atlassian.oauth_3lo import OAuthRefreshTokenAuth  # noqa: E402
from atlassian.graph.schema_fetcher import fetch_schema_introspection  # noqa: E402


def _auth_from_env():
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
            raise ValueError(
                "ATLASSIAN_OAUTH_ACCESS_TOKEN appears to be set to ATLASSIAN_CLIENT_SECRET; "
                "set an OAuth access token (not the client secret)."
            )
        return OAuthBearerAuth(lambda: token)
    if email and api_token:
        return BasicApiTokenAuth(email, api_token)
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
        except json.JSONDecodeError:
            return None
        if isinstance(cookies, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()
        ):
            return CookieAuth(cookies)
    return None


def _experimental_apis():
    raw = os.getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "graphql"

    base_url = os.getenv("ATLASSIAN_GQL_BASE_URL")
    if not base_url and (
        os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
        or os.getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
    ):
        base_url = "https://api.atlassian.com"
    try:
        auth = _auth_from_env()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not base_url or auth is None:
        print(
            "Missing credentials. Set ATLASSIAN_GQL_BASE_URL and one of: "
            "ATLASSIAN_OAUTH_ACCESS_TOKEN, or ATLASSIAN_OAUTH_REFRESH_TOKEN + (ATLASSIAN_CLIENT_ID + ATLASSIAN_CLIENT_SECRET), "
            "or (ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN), or ATLASSIAN_COOKIES_JSON.",
            file=sys.stderr,
        )
        return 2

    result = fetch_schema_introspection(
        base_url,
        auth,
        output_dir=out_dir,
        experimental_apis=_experimental_apis() or None,
        timeout_seconds=30.0,
    )
    print(f"Wrote {result.introspection_json_path}")
    if result.sdl_path:
        print(f"Wrote {result.sdl_path}")
    else:
        print("SDL not generated (optional dependency missing).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
