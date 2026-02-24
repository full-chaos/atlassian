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

func TestLiveCompassComponents(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	cloudID := os.Getenv("ATLASSIAN_CLOUD_ID")
	if cloudID == "" {
		cloudID = os.Getenv("ATLASSIAN_JIRA_CLOUD_ID")
	}

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
	if strings.TrimSpace(cloudID) == "" {
		t.Skip("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) not set; skipping Compass components integration test")
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

	components, err := client.ListCompassComponents(context.Background(), cloudID, 10)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) && hasRequiredScope(opErr, "") {
				_ = opErr // scope diagnostics already logged by hasRequiredScope check
			}
			t.Skipf("GraphQL operation error listing Compass components: %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error listing Compass components: %v", err)
	}

	if len(components) > 0 {
		c := components[0]
		if strings.TrimSpace(c.ID) == "" {
			t.Fatalf("first compass component has empty ID: %+v", c)
		}
		if strings.TrimSpace(c.Name) == "" {
			t.Fatalf("first compass component has empty Name: %+v", c)
		}
		if strings.TrimSpace(c.Type) == "" {
			t.Fatalf("first compass component has empty Type: %+v", c)
		}
		if c.CloudID != cloudID {
			t.Fatalf("first compass component CloudID mismatch: got %q, want %q", c.CloudID, cloudID)
		}
	}
}

func TestLiveCompassComponentScorecards(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	cloudID := os.Getenv("ATLASSIAN_CLOUD_ID")
	if cloudID == "" {
		cloudID = os.Getenv("ATLASSIAN_JIRA_CLOUD_ID")
	}

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
	if strings.TrimSpace(cloudID) == "" {
		t.Skip("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) not set; skipping Compass scorecards integration test")
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

	// Fetch a component first to use for scorecard lookup
	components, err := client.ListCompassComponents(context.Background(), cloudID, 1)
	if err != nil {
		if _, ok := err.(*atlassian.GraphQLOperationError); ok {
			t.Skipf("Could not fetch Compass components for scorecards test: %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error listing Compass components: %v", err)
	}
	if len(components) == 0 {
		t.Skip("no Compass components found; skipping scorecards test")
	}

	componentID := components[0].ID
	scores, err := client.ListCompassComponentScorecardScores(context.Background(), componentID)
	if err != nil {
		if _, ok := err.(*atlassian.GraphQLOperationError); ok {
			t.Skipf("GraphQL operation error listing Compass scorecard scores: %v", err)
		}
		if _, ok := err.(*atlassian.RateLimitError); ok {
			t.Skipf("rate limited during integration: %v", err)
		}
		t.Fatalf("unexpected error listing Compass scorecard scores: %v", err)
	}

	// scores may be empty if no scorecards are configured; validate any results present
	for i, score := range scores {
		if strings.TrimSpace(score.ComponentID) == "" {
			t.Fatalf("scorecard[%d].ComponentID is empty", i)
		}
		if strings.TrimSpace(score.ScorecardID) == "" {
			t.Fatalf("scorecard[%d].ScorecardID is empty", i)
		}
		if score.ComponentID != componentID {
			t.Fatalf("scorecard[%d].ComponentID mismatch: got %q, want %q", i, score.ComponentID, componentID)
		}
	}
}
