from __future__ import annotations

import base64
from typing import Callable, Dict, MutableMapping, Optional, Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    def apply(self, headers: MutableMapping[str, str]) -> None:
        ...

    def get_cookies(self) -> Optional[Dict[str, str]]:
        ...


class OAuthBearerAuth:
    def __init__(self, token_getter: Callable[[], str]):
        if token_getter is None:
            raise ValueError("token_getter must be provided")
        self._token_getter = token_getter

    def apply(self, headers: MutableMapping[str, str]) -> None:
        token = self._token_getter()
        if not token:
            raise ValueError("OAuth token getter returned empty token")
        token = token.strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        if not token:
            raise ValueError("OAuth token getter returned empty token")
        headers["Authorization"] = f"Bearer {token}"

    def get_cookies(self) -> Optional[Dict[str, str]]:
        return None


class BasicApiTokenAuth:
    def __init__(self, email: str, api_token: str):
        if not email or not api_token:
            raise ValueError("email and api_token are required for Basic auth")
        self._email = email
        self._api_token = api_token

    def apply(self, headers: MutableMapping[str, str]) -> None:
        raw = f"{self._email}:{self._api_token}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"

    def get_cookies(self) -> Optional[Dict[str, str]]:
        return None


class CookieAuth:
    def __init__(self, cookies: Dict[str, str]):
        if not cookies:
            raise ValueError("cookies are required for CookieAuth")
        self._cookies = dict(cookies)

    def apply(self, headers: MutableMapping[str, str]) -> None:
        return None

    def get_cookies(self) -> Optional[Dict[str, str]]:
        return dict(self._cookies)
