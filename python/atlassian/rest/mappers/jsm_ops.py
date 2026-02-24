from __future__ import annotations

from typing import Any, Dict, Optional

from ...canonical_models import (
    AtlassianOpsAlertPolicy,
    AtlassianOpsEscalation,
    AtlassianOpsHeartbeat,
    AtlassianOpsOnCallParticipant,
    AtlassianOpsSchedule,
)


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _bool_value(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "off")
    return default


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def map_schedule(raw: Dict[str, Any]) -> AtlassianOpsSchedule:
    """Map a raw JSM Ops API schedule dict to AtlassianOpsSchedule."""
    if raw is None:
        raise ValueError("raw schedule dict is required")

    schedule_id = _str_or_none(raw.get("id"))
    if not schedule_id:
        raise ValueError("schedule.id is required")

    name = _str_or_none(raw.get("name"))
    if not name:
        raise ValueError("schedule.name is required")

    return AtlassianOpsSchedule(
        id=schedule_id,
        name=name,
        description=_str_or_none(raw.get("description")),
        timezone=_str_or_none(raw.get("timezone")),
        enabled=_bool_value(raw.get("enabled"), default=True),
        team_id=_str_or_none(raw.get("teamId")),
    )


def map_escalation(raw: Dict[str, Any]) -> AtlassianOpsEscalation:
    """Map a raw JSM Ops API escalation dict to AtlassianOpsEscalation."""
    if raw is None:
        raise ValueError("raw escalation dict is required")

    escalation_id = _str_or_none(raw.get("id"))
    if not escalation_id:
        raise ValueError("escalation.id is required")

    name = _str_or_none(raw.get("name"))
    if not name:
        raise ValueError("escalation.name is required")

    return AtlassianOpsEscalation(
        id=escalation_id,
        name=name,
        description=_str_or_none(raw.get("description")),
        team_id=_str_or_none(raw.get("teamId")),
    )


def map_alert_policy(raw: Dict[str, Any]) -> AtlassianOpsAlertPolicy:
    """Map a raw JSM Ops API alert policy dict to AtlassianOpsAlertPolicy."""
    if raw is None:
        raise ValueError("raw alert policy dict is required")

    policy_id = _str_or_none(raw.get("id"))
    if not policy_id:
        raise ValueError("alertPolicy.id is required")

    name = _str_or_none(raw.get("name"))
    if not name:
        raise ValueError("alertPolicy.name is required")

    return AtlassianOpsAlertPolicy(
        id=policy_id,
        name=name,
        enabled=_bool_value(raw.get("enabled"), default=True),
        team_id=_str_or_none(raw.get("teamId")),
        type=_str_or_none(raw.get("type")),
    )


def map_on_call_participant(
    raw: Dict[str, Any], *, schedule_id: str
) -> AtlassianOpsOnCallParticipant:
    """Map a raw JSM Ops API on-call participant dict to AtlassianOpsOnCallParticipant."""
    if raw is None:
        raise ValueError("raw on-call participant dict is required")

    participant_id = _str_or_none(raw.get("id"))
    if not participant_id:
        raise ValueError("onCallParticipant.id is required")

    participant_type = _str_or_none(raw.get("type")) or "user"
    schedule_id_clean = (schedule_id or "").strip()
    if not schedule_id_clean:
        raise ValueError("schedule_id is required")

    return AtlassianOpsOnCallParticipant(
        id=participant_id,
        type=participant_type,
        schedule_id=schedule_id_clean,
    )


def map_heartbeat(raw: Dict[str, Any]) -> AtlassianOpsHeartbeat:
    """Map a raw JSM Ops API heartbeat dict to AtlassianOpsHeartbeat.

    Note: The JSM Ops API uses the heartbeat name as its identifier in some
    endpoints. When a distinct id field is not present we fall back to name.
    """
    if raw is None:
        raise ValueError("raw heartbeat dict is required")

    # The Heartbeat schema in the swagger does not include an explicit 'id' field —
    # the heartbeat is identified by name. We use name as the canonical id.
    name = _str_or_none(raw.get("name"))
    if not name:
        raise ValueError("heartbeat.name is required")

    heartbeat_id = _str_or_none(raw.get("id")) or name

    return AtlassianOpsHeartbeat(
        id=heartbeat_id,
        name=name,
        enabled=_bool_value(raw.get("enabled"), default=True),
        interval=_int_or_none(raw.get("interval")),
        interval_unit=_str_or_none(raw.get("intervalUnit")),
    )
