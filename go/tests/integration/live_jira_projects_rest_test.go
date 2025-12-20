//go:build integration
// +build integration

package integration

import (
	"bytes"
	"context"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"atlassian/atlassian"
	"atlassian/atlassian/rest"
	"log/slog"
)

func TestLiveJiraProjectsREST(t *testing.T) {
	loadDotEnvIfPresent(t)

	cloudID := strings.TrimSpace(os.Getenv("ATLASSIAN_CLOUD_ID"))
	if cloudID == "" {
		cloudID = strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_CLOUD_ID"))
	}

	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}
	if cloudID == "" {
		t.Fatal("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira REST integration tests")
	}

	baseURL := strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_BASE_URL"))
	if baseURL == "" {
		if isOAuthAuth(auth) {
			baseURL = "https://api.atlassian.com/ex/jira/" + cloudID
		} else if gqlBase := strings.TrimSpace(os.Getenv("ATLASSIAN_GQL_BASE_URL")); gqlBase != "" {
			baseURL = deriveSiteBaseURLFromGQLBase(gqlBase)
		}
	}
	if baseURL == "" {
		t.Skip("ATLASSIAN_JIRA_BASE_URL not set and could not derive Jira base URL (set ATLASSIAN_JIRA_BASE_URL or ATLASSIAN_GQL_BASE_URL for tenanted auth)")
	}

	buf := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(buf, &slog.HandlerOptions{Level: slog.LevelInfo}))

	client := rest.JiraRESTClient{
		BaseURL:       baseURL,
		Auth:          auth,
		MaxRetries429: 1,
		Logger:        logger,
		HTTPClient:    &http.Client{Timeout: 30 * time.Second},
	}

	projects, err := client.ListProjectsViaREST(context.Background(), cloudID, []string{"SOFTWARE"}, 50)
	if err != nil {
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error: %v", err)
	}
	if len(projects) > 0 {
		p := projects[0]
		if p.Project.CloudID != cloudID || strings.TrimSpace(p.Project.Key) == "" || strings.TrimSpace(p.Project.Name) == "" {
			t.Fatalf("unexpected project mapping: %+v", p.Project)
		}
		if p.Project.Type == nil || strings.TrimSpace(*p.Project.Type) != "SOFTWARE" {
			t.Fatalf("unexpected project type: %+v", p.Project)
		}
		if len(p.OpsgenieTeams) != 0 {
			t.Fatalf("expected empty opsgenie teams from REST listing: %+v", p)
		}
	}
}

func deriveSiteBaseURLFromGQLBase(gqlBaseURL string) string {
	candidate := strings.TrimRight(strings.TrimSpace(gqlBaseURL), "/")
	for _, suffix := range []string{"/gateway/api/graphql", "/gateway/api", "/graphql"} {
		if strings.HasSuffix(candidate, suffix) {
			return strings.TrimRight(strings.TrimSuffix(candidate, suffix), "/")
		}
	}
	return ""
}
