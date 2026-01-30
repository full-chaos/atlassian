package gen

// Placeholder types until Compass schema generation is available.
type CompassComponentNode struct {
	ID          string           `json:"id"`
	Name        string           `json:"name"`
	Type        string           `json:"type"`
	Description *string          `json:"description,omitempty"`
	OwnerTeam   *CompassTeamNode `json:"ownerTeam,omitempty"`
	Labels      []string         `json:"labels"`
	CreatedAt   *string          `json:"createdAt,omitempty"`
	UpdatedAt   *string          `json:"updatedAt,omitempty"`
}

type CompassTeamNode struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type CompassComponentRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type CompassRelationshipNode struct {
	ID        string               `json:"id"`
	Type      string               `json:"type"`
	StartNode *CompassComponentRef `json:"startNode,omitempty"`
	EndNode   *CompassComponentRef `json:"endNode,omitempty"`
}

type CompassScorecardRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type CompassScorecardNode struct {
	Scorecard   *CompassScorecardRef `json:"scorecard,omitempty"`
	Score       float64              `json:"score"`
	MaxScore    *float64             `json:"maxScore,omitempty"`
	EvaluatedAt *string              `json:"evaluatedAt,omitempty"`
}
