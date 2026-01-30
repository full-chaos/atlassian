from typing import Any, List, Optional

from ...canonical_models import (
    CompassComponent,
    CompassRelationship,
    CompassScorecardScore,
)

CompassComponentNode = Any


def _clean_optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def map_compass_component(
    *, cloud_id: str, component: CompassComponentNode
) -> CompassComponent:
    cloud_id_clean = (cloud_id or "").strip()
    if not cloud_id_clean:
        raise ValueError("cloud_id is required")

    component_id = (getattr(component, "id", "") or "").strip()
    if not component_id:
        raise ValueError("component.id is required")

    component_name = (getattr(component, "name", "") or "").strip()
    if not component_name:
        raise ValueError("component.name is required")

    component_type = (getattr(component, "type", "") or "").strip()
    if not component_type:
        raise ValueError("component.type is required")

    description = _clean_optional_str(getattr(component, "description", None))

    owner_team_id = _clean_optional_str(getattr(component, "owner_team_id", None))
    owner_team_name = _clean_optional_str(getattr(component, "owner_team_name", None))
    owner_team = getattr(component, "owner_team", None)
    if owner_team is not None:
        owner_team_id = (
            _clean_optional_str(getattr(owner_team, "id", None)) or owner_team_id
        )
        owner_team_name = (
            _clean_optional_str(getattr(owner_team, "name", None)) or owner_team_name
        )

    labels: List[str] = []
    labels_raw = getattr(component, "labels", None) or []
    for label in labels_raw:
        label_clean = (label or "").strip()
        if label_clean:
            labels.append(label_clean)

    created_at = _clean_optional_str(getattr(component, "created_at", None))
    updated_at = _clean_optional_str(getattr(component, "updated_at", None))

    return CompassComponent(
        id=component_id,
        cloud_id=cloud_id_clean,
        name=component_name,
        type=component_type,
        description=description,
        owner_team_id=owner_team_id,
        owner_team_name=owner_team_name,
        labels=labels,
        created_at=created_at,
        updated_at=updated_at,
    )


def map_compass_relationship(relationship: Any) -> CompassRelationship:
    if relationship is None:
        raise ValueError("relationship is required")

    relationship_id = (getattr(relationship, "id", "") or "").strip()
    if not relationship_id:
        raise ValueError("relationship.id is required")

    relationship_type = (getattr(relationship, "type", "") or "").strip()
    if not relationship_type:
        raise ValueError("relationship.type is required")

    start_component_id = _clean_optional_str(
        getattr(relationship, "start_component_id", None)
    )
    end_component_id = _clean_optional_str(
        getattr(relationship, "end_component_id", None)
    )

    start_node = getattr(relationship, "start_node", None)
    if start_node is not None:
        start_component_id = (
            _clean_optional_str(getattr(start_node, "id", None)) or start_component_id
        )

    end_node = getattr(relationship, "end_node", None)
    if end_node is not None:
        end_component_id = (
            _clean_optional_str(getattr(end_node, "id", None)) or end_component_id
        )

    if not start_component_id:
        raise ValueError("relationship.start_component_id is required")
    if not end_component_id:
        raise ValueError("relationship.end_component_id is required")

    return CompassRelationship(
        id=relationship_id,
        type=relationship_type,
        start_component_id=start_component_id,
        end_component_id=end_component_id,
    )


def map_compass_scorecard_score(
    component_id: str, score_data: Any
) -> CompassScorecardScore:
    component_id_clean = (component_id or "").strip()
    if not component_id_clean:
        raise ValueError("component_id is required")
    if score_data is None:
        raise ValueError("score_data is required")

    score_value = getattr(score_data, "score", None)
    if (
        score_value is None
        or not isinstance(score_value, (int, float))
        or isinstance(score_value, bool)
    ):
        raise ValueError("score_data.score is required")

    scorecard_id = _clean_optional_str(getattr(score_data, "scorecard_id", None))
    scorecard_name = _clean_optional_str(getattr(score_data, "scorecard_name", None))
    scorecard = getattr(score_data, "scorecard", None)
    if scorecard is not None:
        scorecard_id = (
            _clean_optional_str(getattr(scorecard, "id", None)) or scorecard_id
        )
        scorecard_name = (
            _clean_optional_str(getattr(scorecard, "name", None)) or scorecard_name
        )

    if not scorecard_id:
        raise ValueError("score_data.scorecard_id is required")

    max_score = getattr(score_data, "max_score", None)
    if max_score is not None:
        if not isinstance(max_score, (int, float)) or isinstance(max_score, bool):
            raise ValueError("score_data.max_score must be a number")
        max_score = float(max_score)

    evaluated_at = _clean_optional_str(getattr(score_data, "evaluated_at", None))

    return CompassScorecardScore(
        component_id=component_id_clean,
        scorecard_id=scorecard_id,
        scorecard_name=scorecard_name,
        score=float(score_value),
        max_score=max_score,
        evaluated_at=evaluated_at,
    )
