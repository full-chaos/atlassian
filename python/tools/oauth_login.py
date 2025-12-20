from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()

from atlassian.oauth_3lo import (  # noqa: E402
    build_authorize_url,
    exchange_authorization_code,
    fetch_accessible_resources,
)


def _split_scopes(raw: str) -> List[str]:
    parts: List[str] = []
    for chunk in (raw or "").replace(",", " ").split():
        v = chunk.strip()
        if v:
            parts.append(v)
    return parts


def _extract_code(user_input: str) -> str:
    raw = (user_input or "").strip()
    if not raw:
        raise ValueError("missing code/redirected URL input")
    if "://" not in raw:
        return raw
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code or not code.strip():
        raise ValueError("redirected URL missing ?code=")
    return code.strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Atlassian OAuth 2.0 (3LO) login helper")
    parser.add_argument("--client-id", default=os.getenv("ATLASSIAN_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.getenv("ATLASSIAN_CLIENT_SECRET", ""))
    parser.add_argument(
        "--redirect-uri",
        default=os.getenv("ATLASSIAN_OAUTH_REDIRECT_URI", "http://localhost:8080/callback"),
    )
    parser.add_argument(
        "--scopes",
        default=os.getenv("ATLASSIAN_OAUTH_SCOPES", ""),
        help="Space- or comma-separated scopes (must match your app config)",
    )
    parser.add_argument("--state", default=os.getenv("ATLASSIAN_OAUTH_STATE", "").strip() or None)
    parser.add_argument(
        "--print-accessible-resources",
        action="store_true",
        help="After login, call accessible-resources and print cloud IDs",
    )
    args = parser.parse_args(argv)

    scopes = _split_scopes(args.scopes)
    if not args.client_id or not args.client_secret or not scopes:
        print(
            "Missing required inputs. Provide --client-id, --client-secret, and --scopes "
            "(or set ATLASSIAN_CLIENT_ID, ATLASSIAN_CLIENT_SECRET, ATLASSIAN_OAUTH_SCOPES).",
            file=sys.stderr,
        )
        return 2

    authorize_url = build_authorize_url(
        client_id=args.client_id,
        redirect_uri=args.redirect_uri,
        scopes=scopes,
        state=args.state,
    )
    print("Open this URL in your browser and complete consent:")
    print(authorize_url)
    print("", file=sys.stderr)
    print("Paste the redirected URL (or just the `code` value):", file=sys.stderr)
    try:
        raw = input().strip()
        code = _extract_code(raw)
    except (EOFError, ValueError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    token = exchange_authorization_code(
        client_id=args.client_id,
        client_secret=args.client_secret,
        code=code,
        redirect_uri=args.redirect_uri,
    )

    print("")
    print("# Use these in your shell or .env (do NOT commit secrets):")
    print(f"ATLASSIAN_OAUTH_ACCESS_TOKEN={token.access_token}")
    if token.refresh_token:
        print(f"ATLASSIAN_OAUTH_REFRESH_TOKEN={token.refresh_token}")
    else:
        print("# No refresh_token returned; ensure your app is configured for offline_access.")

    if args.print_accessible_resources:
        try:
            resources = fetch_accessible_resources(access_token=token.access_token)
        except Exception as exc:
            print(f"Failed to fetch accessible resources: {exc}", file=sys.stderr)
            return 0

        print("")
        print("# Accessible resources (cloud IDs):")
        for r in resources:
            rid = r.get("id")
            name = r.get("name")
            url = r.get("url")
            if isinstance(rid, str) and rid and isinstance(name, str) and isinstance(url, str):
                scopes = r.get("scopes")
                scopes_str = ""
                if isinstance(scopes, list):
                    cleaned = [s for s in scopes if isinstance(s, str) and s.strip()]
                    if cleaned:
                        scopes_str = f" scopes={','.join(cleaned)}"
                print(f"- {name}: id={rid} url={url}{scopes_str}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
