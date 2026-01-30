package mappers

import (
	"errors"
	"strings"

	"atlassian/atlassian"
	"atlassian/atlassian/graph/gen"
)

func CompassComponentFromGraphQL(cloudID string, component *gen.CompassComponentNode) (atlassian.CompassComponent, error) {
	if component == nil {
		return atlassian.CompassComponent{}, errors.New("component is required")
	}

	cloud := strings.TrimSpace(cloudID)
	if cloud == "" {
		return atlassian.CompassComponent{}, errors.New("cloudID is required")
	}

	id := strings.TrimSpace(component.ID)
	if id == "" {
		return atlassian.CompassComponent{}, errors.New("component.id is required")
	}
	name := strings.TrimSpace(component.Name)
	if name == "" {
		return atlassian.CompassComponent{}, errors.New("component.name is required")
	}
	componentType := strings.TrimSpace(string(component.Type))
	if componentType == "" {
		return atlassian.CompassComponent{}, errors.New("component.type is required")
	}

	var description *string
	if component.Description != nil {
		trimmed := strings.TrimSpace(*component.Description)
		if trimmed != "" {
			description = &trimmed
		}
	}

	var ownerTeamID *string
	var ownerTeamName *string
	if component.OwnerTeam != nil {
		teamID := strings.TrimSpace(component.OwnerTeam.ID)
		if teamID == "" {
			return atlassian.CompassComponent{}, errors.New("component.ownerTeam.id is required")
		}
		teamName := strings.TrimSpace(component.OwnerTeam.Name)
		if teamName == "" {
			return atlassian.CompassComponent{}, errors.New("component.ownerTeam.name is required")
		}
		ownerTeamID = &teamID
		ownerTeamName = &teamName
	}

	labels := make([]string, 0, len(component.Labels))
	for _, raw := range component.Labels {
		value := strings.TrimSpace(raw)
		if value == "" {
			continue
		}
		labels = append(labels, value)
	}

	var createdAt *string
	if component.CreatedAt != nil {
		trimmed := strings.TrimSpace(*component.CreatedAt)
		if trimmed != "" {
			createdAt = &trimmed
		}
	}

	var updatedAt *string
	if component.UpdatedAt != nil {
		trimmed := strings.TrimSpace(*component.UpdatedAt)
		if trimmed != "" {
			updatedAt = &trimmed
		}
	}

	return atlassian.CompassComponent{
		ID:            id,
		CloudID:       cloud,
		Name:          name,
		Type:          componentType,
		Description:   description,
		OwnerTeamID:   ownerTeamID,
		OwnerTeamName: ownerTeamName,
		Labels:        labels,
		CreatedAt:     createdAt,
		UpdatedAt:     updatedAt,
	}, nil
}

func CompassRelationshipFromGraphQL(rel *gen.CompassRelationshipNode) (atlassian.CompassRelationship, error) {
	if rel == nil {
		return atlassian.CompassRelationship{}, errors.New("relationship is required")
	}

	id := strings.TrimSpace(rel.ID)
	if id == "" {
		return atlassian.CompassRelationship{}, errors.New("relationship.id is required")
	}
	relationshipType := strings.TrimSpace(rel.Type)
	if relationshipType == "" {
		return atlassian.CompassRelationship{}, errors.New("relationship.type is required")
	}
	if rel.StartNode == nil {
		return atlassian.CompassRelationship{}, errors.New("relationship.startNode is required")
	}
	startID := strings.TrimSpace(rel.StartNode.ID)
	if startID == "" {
		return atlassian.CompassRelationship{}, errors.New("relationship.startNode.id is required")
	}
	if rel.EndNode == nil {
		return atlassian.CompassRelationship{}, errors.New("relationship.endNode is required")
	}
	endID := strings.TrimSpace(rel.EndNode.ID)
	if endID == "" {
		return atlassian.CompassRelationship{}, errors.New("relationship.endNode.id is required")
	}

	return atlassian.CompassRelationship{
		ID:               id,
		Type:             relationshipType,
		StartComponentID: startID,
		EndComponentID:   endID,
	}, nil
}

func CompassScorecardScoreFromGraphQL(componentID string, score *gen.CompassScorecardNode) (atlassian.CompassScorecardScore, error) {
	component := strings.TrimSpace(componentID)
	if component == "" {
		return atlassian.CompassScorecardScore{}, errors.New("componentID is required")
	}
	if score == nil {
		return atlassian.CompassScorecardScore{}, errors.New("score is required")
	}
	if score.Scorecard == nil {
		return atlassian.CompassScorecardScore{}, errors.New("score.scorecard is required")
	}
	scorecardID := strings.TrimSpace(score.Scorecard.ID)
	if scorecardID == "" {
		return atlassian.CompassScorecardScore{}, errors.New("score.scorecard.id is required")
	}

	var scorecardName *string
	if trimmed := strings.TrimSpace(score.Scorecard.Name); trimmed != "" {
		scorecardName = &trimmed
	}

	scoreValue := score.Score

	var maxScore *float64
	if score.MaxScore != nil {
		maxScore = score.MaxScore
	}

	var evaluatedAt *string
	if score.EvaluatedAt != nil {
		trimmed := strings.TrimSpace(*score.EvaluatedAt)
		if trimmed != "" {
			evaluatedAt = &trimmed
		}
	}

	return atlassian.CompassScorecardScore{
		ComponentID:   component,
		ScorecardID:   scorecardID,
		ScorecardName: scorecardName,
		Score:         scoreValue,
		MaxScore:      maxScore,
		EvaluatedAt:   evaluatedAt,
	}, nil
}
