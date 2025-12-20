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

func TestLiveJiraIssuesREST(t *testing.T) {
	loadDotEnvIfPresent(t)

	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}

	cloudID := strings.TrimSpace(os.Getenv("ATLASSIAN_CLOUD_ID"))
	if cloudID == "" {
		cloudID = strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_CLOUD_ID"))
	}
	if cloudID == "" {
		t.Fatal("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira REST integration tests")
	}

	jql := strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_JQL"))
	if jql == "" {
		t.Skip("ATLASSIAN_JIRA_JQL not set")
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
		t.Skip("ATLASSIAN_JIRA_BASE_URL not set and could not derive Jira base URL")
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

	issues, err := client.ListIssuesViaREST(context.Background(), cloudID, jql, 1)
	if err != nil {
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error: %v", err)
	}
	if len(issues) > 0 {
		it := issues[0]
		if it.CloudID != cloudID || strings.TrimSpace(it.Key) == "" || strings.TrimSpace(it.ProjectKey) == "" {
			t.Fatalf("unexpected issue mapping: %+v", it)
		}
	}
}

func TestLiveJiraIssueHistoryREST(t *testing.T) {
	loadDotEnvIfPresent(t)

	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}

	cloudID := strings.TrimSpace(os.Getenv("ATLASSIAN_CLOUD_ID"))
	if cloudID == "" {
		cloudID = strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_CLOUD_ID"))
	}
	if cloudID == "" {
		t.Fatal("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira REST integration tests")
	}

	issueKey := strings.TrimSpace(os.Getenv("ATLASSIAN_JIRA_ISSUE_KEY"))
	if issueKey == "" {
		t.Skip("ATLASSIAN_JIRA_ISSUE_KEY not set")
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
		t.Skip("ATLASSIAN_JIRA_BASE_URL not set and could not derive Jira base URL")
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

	if _, err := client.ListIssueChangelogViaREST(context.Background(), issueKey, 1); err != nil {
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := client.ListIssueWorklogsViaREST(context.Background(), issueKey, 1); err != nil {
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error: %v", err)
	}
}
