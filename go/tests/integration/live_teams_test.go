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

func TestLiveTeamSearchV2(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	orgID := os.Getenv("ATLASSIAN_ORGANIZATION_ID")
	siteID := os.Getenv("ATLASSIAN_SITE_ID")

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
	if strings.TrimSpace(orgID) == "" {
		t.Skip("ATLASSIAN_ORGANIZATION_ID not set; skipping team search integration test")
	}
	if strings.TrimSpace(siteID) == "" {
		t.Skip("ATLASSIAN_SITE_ID not set; skipping team search integration test")
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

	teams, err := client.SearchTeams(context.Background(), orgID, siteID, "", 10)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) {
				_ = opErr
			}
			t.Skipf("GraphQL operation error searching teams: %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error searching teams: %v", err)
	}

	if len(teams) > 0 {
		team := teams[0]
		if strings.TrimSpace(team.ID) == "" {
			t.Fatalf("first team has empty ID: %+v", team)
		}
		if !strings.Contains(team.ID, "ari:") {
			t.Fatalf("first team ID does not appear to be an ARI: %q", team.ID)
		}
		if strings.TrimSpace(team.DisplayName) == "" {
			t.Fatalf("first team has empty DisplayName: %+v", team)
		}
		if strings.TrimSpace(team.State) == "" {
			t.Fatalf("first team has empty State: %+v", team)
		}
	}
}

func TestLiveTeamByID(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	teamID := os.Getenv("ATLASSIAN_TEST_TEAM_ID")
	siteID := os.Getenv("ATLASSIAN_SITE_ID")

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
		t.Skip("ATLASSIAN_TEST_TEAM_ID not set; skipping get team by ID integration test")
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

	team, err := client.GetTeamByID(context.Background(), teamID, siteID)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) {
				_ = opErr
			}
			t.Skipf("GraphQL operation error getting team by ID: %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error getting team by ID: %v", err)
	}
	if team == nil {
		t.Fatalf("GetTeamByID returned nil for team ID %q", teamID)
	}

	if team.ID != strings.TrimSpace(teamID) {
		t.Fatalf("team.ID mismatch: got %q, want %q", team.ID, strings.TrimSpace(teamID))
	}
	if strings.TrimSpace(team.DisplayName) == "" {
		t.Fatalf("team has empty DisplayName: %+v", team)
	}
	if strings.TrimSpace(team.State) == "" {
		t.Fatalf("team has empty State: %+v", team)
	}
}
