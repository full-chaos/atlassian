from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Sequence
from urllib.parse import urlencode

import httpx

from .errors import SerializationError, TransportError


ATLASSIAN_AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_ACCESSIBLE_RESOURCES_URL = (
    "https://api.atlassian.com/oauth/token/accessible-resources"
)
ATLASSIAN_DEFAULT_AUDIENCE = "api.atlassian.com"


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    token_type: str
    expires_in: int
    scope: Optional[str] = None
    refresh_token: Optional[str] = None


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: Optional[str] = None,
    audience: str = ATLASSIAN_DEFAULT_AUDIENCE,
    prompt: str = "consent",
) -> str:
    if not client_id or not client_id.strip():
        raise ValueError("client_id is required")
    if not redirect_uri or not redirect_uri.strip():
        raise ValueError("redirect_uri is required")
    cleaned_scopes = [s.strip() for s in scopes if isinstance(s, str) and s.strip()]
    if not cleaned_scopes:
        raise ValueError("scopes must be non-empty")
    if state is not None and not state.strip():
        raise ValueError("state must be non-empty when provided")
    if not audience or not audience.strip():
        raise ValueError("audience is required")
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")

    params = {
        "audience": audience.strip(),
        "client_id": client_id.strip(),
        "scope": " ".join(cleaned_scopes),
        "redirect_uri": redirect_uri.strip(),
        "response_type": "code",
        "prompt": prompt.strip(),
    }
    if state is not None:
        params["state"] = state.strip()

    return f"{ATLASSIAN_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    token_url: str = ATLASSIAN_TOKEN_URL,
    timeout_seconds: float = 30.0,
    http_client: httpx.Client | None = None,
) -> OAuthToken:
    if not client_id or not client_id.strip():
        raise ValueError("client_id is required")
    if not client_secret or not client_secret.strip():
        raise ValueError("client_secret is required")
    if not code or not code.strip():
        raise ValueError("code is required")
    if not redirect_uri or not redirect_uri.strip():
        raise ValueError("redirect_uri is required")
    if not token_url or not token_url.strip():
        raise ValueError("token_url is required")
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "code": code.strip(),
        "redirect_uri": redirect_uri.strip(),
    }
    body = _post_json(
        token_url.strip(),
        payload,
        timeout_seconds=timeout_seconds,
        http_client=http_client,
    )
    return _parse_oauth_token(body)


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_url: str = ATLASSIAN_TOKEN_URL,
    timeout_seconds: float = 30.0,
    http_client: httpx.Client | None = None,
) -> OAuthToken:
    if not client_id or not client_id.strip():
        raise ValueError("client_id is required")
    if not client_secret or not client_secret.strip():
        raise ValueError("client_secret is required")
    if not refresh_token or not refresh_token.strip():
        raise ValueError("refresh_token is required")
    if not token_url or not token_url.strip():
        raise ValueError("token_url is required")
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "refresh_token": refresh_token.strip(),
    }
    body = _post_json(
        token_url.strip(),
        payload,
        timeout_seconds=timeout_seconds,
        http_client=http_client,
    )
    return _parse_oauth_token(body)


def fetch_accessible_resources(
    *,
    access_token: str,
    timeout_seconds: float = 30.0,
    http_client: httpx.Client | None = None,
) -> List[Dict[str, Any]]:
    token = (access_token or "").strip()
    if not token:
        raise ValueError("access_token is required")
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    owns = http_client is None
    client = http_client if http_client is not None else httpx.Client(timeout=timeout_seconds)
    try:
        resp = client.get(
            ATLASSIAN_ACCESSIBLE_RESOURCES_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
    finally:
        if owns:
            client.close()

    if resp.status_code != 200:
        raise TransportError(status_code=resp.status_code, body_snippet=resp.text[:200])
    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise SerializationError(f"Failed to parse JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise SerializationError("accessible-resources response must be a JSON array")
    out: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            out.append(item)
    return out


class OAuthRefreshTokenAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        token_url: str = ATLASSIAN_TOKEN_URL,
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
        refresh_margin_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
    ):
        if not client_id or not client_id.strip():
            raise ValueError("client_id is required")
        if not client_secret or not client_secret.strip():
            raise ValueError("client_secret is required")
        if not refresh_token or not refresh_token.strip():
            raise ValueError("refresh_token is required")
        if not token_url or not token_url.strip():
            raise ValueError("token_url is required")
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if refresh_margin_seconds < 0:
            raise ValueError("refresh_margin_seconds must be >= 0")

        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._token_url = token_url.strip()
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._refresh_margin = timedelta(seconds=refresh_margin_seconds)
        self._now = now if now is not None else lambda: datetime.now(timezone.utc)

        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._refresh_token = refresh_token.strip()

    @property
    def refresh_token(self) -> str:
        with self._lock:
            return self._refresh_token

    def apply(self, headers: MutableMapping[str, str]) -> None:
        token = self._get_access_token()
        headers["Authorization"] = f"Bearer {token}"

    def get_cookies(self) -> Optional[Dict[str, str]]:
        return None

    def _get_access_token(self) -> str:
        with self._lock:
            now = self._now()
            if self._access_token and self._expires_at:
                if now + self._refresh_margin < self._expires_at:
                    return self._access_token

            token = refresh_access_token(
                client_id=self._client_id,
                client_secret=self._client_secret,
                refresh_token=self._refresh_token,
                token_url=self._token_url,
                timeout_seconds=self._timeout_seconds,
                http_client=self._http_client,
            )
            self._access_token = token.access_token
            expires_in = int(token.expires_in) if token.expires_in is not None else 0
            if expires_in < 0:
                expires_in = 0
            self._expires_at = now + timedelta(seconds=expires_in)
            if token.refresh_token:
                self._refresh_token = token.refresh_token.strip()
            return self._access_token


def _post_json(
    url: str,
    payload: Dict[str, str],
    *,
    timeout_seconds: float,
    http_client: httpx.Client | None,
) -> Any:
    owns = http_client is None
    client = http_client if http_client is not None else httpx.Client(timeout=timeout_seconds)
    try:
        resp = client.post(
            url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
    finally:
        if owns:
            client.close()

    if resp.status_code != 200:
        raise TransportError(status_code=resp.status_code, body_snippet=resp.text[:200])

    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise SerializationError(f"Failed to parse JSON: {exc}") from exc


def _parse_oauth_token(payload: Any) -> OAuthToken:
    if not isinstance(payload, dict):
        raise SerializationError("OAuth token response must be a JSON object")

    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")
    refresh_token = payload.get("refresh_token")

    if not isinstance(access_token, str) or not access_token.strip():
        raise SerializationError("OAuth token response missing access_token")
    if not isinstance(token_type, str) or not token_type.strip():
        raise SerializationError("OAuth token response missing token_type")
    if not isinstance(expires_in, int):
        raise SerializationError("OAuth token response missing expires_in")
    if scope is not None and not isinstance(scope, str):
        scope = None
    if refresh_token is not None and not isinstance(refresh_token, str):
        refresh_token = None

    return OAuthToken(
        access_token=access_token.strip(),
        token_type=token_type.strip(),
        expires_in=expires_in,
        scope=scope.strip() if isinstance(scope, str) else None,
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) else None,
    )
