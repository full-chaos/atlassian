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
	"atlassian/atlassian/graph"
	"log/slog"
)

func TestLiveTeamworkTeamActiveProjects(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	teamID := os.Getenv("ATLASSIAN_TEST_TEAM_ID")

	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	if baseURL == "" {
		t.Skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")
	}
	if strings.TrimSpace(teamID) == "" {
		t.Skip("ATLASSIAN_TEST_TEAM_ID not set; skipping teamwork active projects integration test")
	}

	buf := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(buf, &slog.HandlerOptions{Level: slog.LevelInfo}))

	client := graph.Client{
		BaseURL:          baseURL,
		Auth:             auth,
		Strict:           false,
		MaxRetries429:    1,
		ExperimentalAPIs: parseExperimentalAPIs(),
		Logger:           logger,
		HTTPClient:       &http.Client{Timeout: 30 * time.Second},
	}

	projects, err := client.IterTeamActiveProjects(context.Background(), teamID, 10)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) {
				_ = opErr
			}
			t.Skipf("GraphQL operation error fetching team active projects (Teamwork Graph is EAP): %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error fetching team active projects: %v", err)
	}

	// projects may be empty if the team has no active projects; validate any present
	for i, p := range projects {
		if strings.TrimSpace(p.TeamID) == "" {
			t.Fatalf("project[%d].TeamID is empty", i)
		}
		if strings.TrimSpace(p.ProjectID) == "" {
			t.Fatalf("project[%d].ProjectID is empty", i)
		}
	}
}

func TestLiveTeamworkUserTeams(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	userID := os.Getenv("ATLASSIAN_TEST_USER_ID")

	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	if baseURL == "" {
		t.Skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")
	}
	if strings.TrimSpace(userID) == "" {
		t.Skip("ATLASSIAN_TEST_USER_ID not set; skipping teamwork user teams integration test")
	}

	buf := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(buf, &slog.HandlerOptions{Level: slog.LevelInfo}))

	client := graph.Client{
		BaseURL:          baseURL,
		Auth:             auth,
		Strict:           false,
		MaxRetries429:    1,
		ExperimentalAPIs: parseExperimentalAPIs(),
		Logger:           logger,
		HTTPClient:       &http.Client{Timeout: 30 * time.Second},
	}

	relations, err := client.IterUserTeams(context.Background(), userID, 10)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) {
				_ = opErr
			}
			t.Skipf("GraphQL operation error fetching user teams (Teamwork Graph is EAP): %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error fetching user teams: %v", err)
	}

	if len(relations) > 0 {
		rel := relations[0]
		if strings.TrimSpace(rel.SubjectUserID) == "" {
			t.Fatalf("first relation has empty SubjectUserID: %+v", rel)
		}
		if strings.TrimSpace(rel.RelationType) == "" {
			t.Fatalf("first relation has empty RelationType: %+v", rel)
		}
	}
}
