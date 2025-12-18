from __future__ import annotations

from typing import List, Optional

from ...canonical_models import JiraChangelogEvent, JiraChangelogItem, JiraUser
from ..gen.jira_api import Changelog, ChangeDetails, UserDetails


def _require_non_empty(value: Optional[str], path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value.strip()


def _map_user(user: Optional[UserDetails], path: str) -> Optional[JiraUser]:
    if user is None:
        return None
    account_id = user.account_id
    display_name = user.display_name
    email = user.email_address
    return JiraUser(
        account_id=_require_non_empty(account_id, f"{path}.accountId"),
        display_name=_require_non_empty(display_name, f"{path}.displayName"),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
    )


def _map_item(item: ChangeDetails, path: str) -> JiraChangelogItem:
    field = _require_non_empty(item.field, f"{path}.field")
    from_value = item.from_value.strip() if isinstance(item.from_value, str) and item.from_value.strip() else None
    to_value = item.to_value.strip() if isinstance(item.to_value, str) and item.to_value.strip() else None
    from_string = item.from_string.strip() if isinstance(item.from_string, str) and item.from_string.strip() else None
    to_string = item.to_string.strip() if isinstance(item.to_string, str) and item.to_string.strip() else None
    return JiraChangelogItem(
        field=field,
        from_value=from_value,
        to_value=to_value,
        from_string=from_string,
        to_string=to_string,
    )


def map_changelog_event(*, issue_key: str, changelog: Changelog) -> JiraChangelogEvent:
    issue_key_clean = (issue_key or "").strip()
    if not issue_key_clean:
        raise ValueError("issue_key is required")
    if changelog is None:
        raise ValueError("changelog is required")

    event_id = _require_non_empty(changelog.id, "changelog.id")
    created_at = _require_non_empty(changelog.created, "changelog.created")

    items: List[JiraChangelogItem] = [
        _map_item(item, f"changelog.items[{idx}]")
        for idx, item in enumerate(changelog.items)
    ]
    if not items:
        raise ValueError("changelog.items is required")

    return JiraChangelogEvent(
        issue_key=issue_key_clean,
        event_id=event_id,
        created_at=created_at,
        items=items,
        author=_map_user(changelog.author, "changelog.author"),
    )
