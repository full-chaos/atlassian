package atlassian

type JiraUser struct {
	AccountID   string  `json:"accountId"`
	DisplayName string  `json:"displayName"`
	Email       *string `json:"email,omitempty"`
}

type JiraProject struct {
	CloudID string  `json:"cloudId"`
	Key     string  `json:"key"`
	Name    string  `json:"name"`
	Type    *string `json:"type,omitempty"`
}

type JiraSprint struct {
	ID         string  `json:"id"`
	Name       string  `json:"name"`
	State      string  `json:"state"`
	StartAt    *string `json:"startAt,omitempty"`
	EndAt      *string `json:"endAt,omitempty"`
	CompleteAt *string `json:"completeAt,omitempty"`
}

type JiraIssue struct {
	CloudID     string    `json:"cloudId"`
	Key         string    `json:"key"`
	ProjectKey  string    `json:"projectKey"`
	IssueType   string    `json:"issueType"`
	Status      string    `json:"status"`
	CreatedAt   string    `json:"createdAt"`
	UpdatedAt   string    `json:"updatedAt"`
	ResolvedAt  *string   `json:"resolvedAt,omitempty"`
	Assignee    *JiraUser `json:"assignee,omitempty"`
	Reporter    *JiraUser `json:"reporter,omitempty"`
	Labels      []string  `json:"labels"`
	Components  []string  `json:"components"`
	StoryPoints *float64  `json:"storyPoints,omitempty"`
	SprintIDs   []string  `json:"sprintIds"`
}

type JiraChangelogItem struct {
	Field      string  `json:"field"`
	From       *string `json:"from,omitempty"`
	To         *string `json:"to,omitempty"`
	FromString *string `json:"fromString,omitempty"`
	ToString   *string `json:"toString,omitempty"`
}

type JiraChangelogEvent struct {
	IssueKey  string            `json:"issueKey"`
	EventID   string            `json:"eventId"`
	Author    *JiraUser          `json:"author,omitempty"`
	CreatedAt string            `json:"createdAt"`
	Items     []JiraChangelogItem `json:"items"`
}

type JiraWorklog struct {
	IssueKey         string    `json:"issueKey"`
	WorklogID        string    `json:"worklogId"`
	Author           *JiraUser `json:"author,omitempty"`
	StartedAt        string    `json:"startedAt"`
	TimeSpentSeconds int       `json:"timeSpentSeconds"`
	CreatedAt        string    `json:"createdAt"`
	UpdatedAt        string    `json:"updatedAt"`
}

type OpsgenieTeamRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type CanonicalProjectWithOpsgenieTeams struct {
	Project       JiraProject       `json:"project"`
	OpsgenieTeams []OpsgenieTeamRef `json:"opsgenieTeams"`
}
