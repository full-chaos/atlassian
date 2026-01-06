from __future__ import annotations

import argparse
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from http.server import BaseHTTPRequestHandler, HTTPServer


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()

from atlassian.oauth_3lo import (  # noqa: E402
    build_authorize_url,
    exchange_authorization_code,
    fetch_accessible_resources,
)


@dataclass(frozen=True)
class _RedirectTarget:
    host: str
    port: int
    path: str


def _split_scopes(raw: str) -> List[str]:
    parts: List[str] = []
    for chunk in (raw or "").replace(",", " ").split():
        v = chunk.strip()
        if v:
            parts.append(v)
    return parts


def _parse_redirect_uri(raw: str) -> _RedirectTarget:
    if not raw or not raw.strip():
        raise ValueError("redirect_uri is required")
    parsed = urlparse(raw.strip())
    if parsed.scheme != "http":
        raise ValueError("redirect_uri must use http:// for the local callback server")
    if not parsed.hostname:
        raise ValueError("redirect_uri must include a hostname")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("redirect_uri host must be localhost/127.0.0.1/::1")
    port = parsed.port or 80
    path = parsed.path or "/callback"
    return _RedirectTarget(host=parsed.hostname, port=port, path=path)


def _write_tokens(path: Path, token_lines: List[str]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(token_lines))
        handle.write("\n")
    os.chmod(str(path), 0o600)


def _make_handler(
    *,
    expected_path: str,
    expected_state: Optional[str],
    result: Dict[str, Optional[str]],
    done: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found.")
                return
            params = parse_qs(parsed.query)
            code = (params.get("code", [None])[0] or "").strip()
            state = (params.get("state", [None])[0] or "").strip()
            if expected_state and state != expected_state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. Check the OAuth flow and try again.")
                return
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code parameter.")
                return
            result["code"] = code
            result["state"] = state or None
            done.set()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OAuth code received. You can close this tab.")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return CallbackHandler


def _wait_for_code(
    target: _RedirectTarget, expected_state: Optional[str], timeout_seconds: float
) -> str:
    result: Dict[str, Optional[str]] = {"code": None, "state": None}
    done = threading.Event()
    handler = _make_handler(
        expected_path=target.path,
        expected_state=expected_state,
        result=result,
        done=done,
    )
    server = HTTPServer((target.host, target.port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not done.wait(timeout=timeout_seconds):
            raise TimeoutError("timed out waiting for OAuth redirect")
        code = result.get("code")
        if not code:
            raise ValueError("missing OAuth code")
        return code
    finally:
        server.shutdown()
        server.server_close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atlassian OAuth 2.0 (3LO) login helper with local callback server"
    )
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
        "--output",
        default=os.getenv("ATLASSIAN_OAUTH_TOKEN_FILE", "oauth_tokens.txt"),
        help="File to write tokens to (0600 perms)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help="How long to wait for the OAuth redirect",
    )
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
    if args.timeout_seconds <= 0:
        print("timeout-seconds must be > 0", file=sys.stderr)
        return 2

    try:
        target = _parse_redirect_uri(args.redirect_uri)
    except ValueError as exc:
        print(f"Invalid redirect URI: {exc}", file=sys.stderr)
        return 2

    authorize_url = build_authorize_url(
        client_id=args.client_id,
        redirect_uri=args.redirect_uri,
        scopes=scopes,
        state=args.state,
    )
    print("Open this URL in your browser and complete consent:")
    print(authorize_url)
    print("")
    print(f"Waiting for OAuth redirect on {args.redirect_uri} ...")

    try:
        code = _wait_for_code(target, args.state, args.timeout_seconds)
    except Exception as exc:
        print(f"OAuth callback failed: {exc}", file=sys.stderr)
        return 2

    token = exchange_authorization_code(
        client_id=args.client_id,
        client_secret=args.client_secret,
        code=code,
        redirect_uri=args.redirect_uri,
    )

    output_path = Path(args.output).expanduser()
    lines = [
        "# OAuth tokens (do NOT commit secrets)",
        f"ATLASSIAN_OAUTH_ACCESS_TOKEN={token.access_token}",
    ]
    if token.refresh_token:
        lines.append(f"ATLASSIAN_OAUTH_REFRESH_TOKEN={token.refresh_token}")
    else:
        lines.append("# No refresh_token returned; ensure your app includes offline_access.")
    lines.append(f"ATLASSIAN_OAUTH_TOKEN_TYPE={token.token_type}")
    lines.append(f"ATLASSIAN_OAUTH_EXPIRES_IN={token.expires_in}")
    if token.scope:
        lines.append(f"ATLASSIAN_OAUTH_SCOPE={token.scope}")

    _write_tokens(output_path, lines)
    print(f"Wrote tokens to {output_path}")

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
