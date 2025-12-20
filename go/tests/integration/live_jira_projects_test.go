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

func TestLiveJiraProjects(t *testing.T) {
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
		t.Fatal("ATLASSIAN_CLOUD_ID (or ATLASSIAN_JIRA_CLOUD_ID) is required when running Jira projects integration tests")
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

	projects, err := client.ListProjectsWithOpsgenieLinkableTeams(
		context.Background(),
		cloudID,
		[]string{"SOFTWARE"},
		50,
	)
	if err != nil {
		if opErr, ok := err.(*atlassian.GraphQLOperationError); ok {
			if isOAuthAuth(auth) && hasRequiredScope(opErr, "jira:atlassian-external") {
				t.Skip("AGG returned required_scopes=['jira:atlassian-external'] for jira.allJiraProjects. This appears to be a non-standard OAuth scope; if you can't obtain it via Atlassian 3LO, run this integration test with tenanted gateway auth (ATLASSIAN_GQL_BASE_URL=https://<site>.atlassian.net/gateway/api + ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN or ATLASSIAN_COOKIES_JSON).")
			}
		}
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
	}
}

func isOAuthAuth(auth atlassian.AuthProvider) bool {
	switch auth.(type) {
	case atlassian.BearerAuth, *atlassian.OAuthRefreshTokenAuth:
		return true
	default:
		return false
	}
}

func hasRequiredScope(err *atlassian.GraphQLOperationError, scope string) bool {
	needle := strings.TrimSpace(scope)
	if needle == "" {
		return false
	}
	for _, ge := range err.Errors {
		if ge.Extensions == nil {
			continue
		}
		for _, key := range []string{"requiredScopes", "required_scopes", "required_scopes_any", "required_scopes_all"} {
			val, ok := ge.Extensions[key]
			if !ok || val == nil {
				continue
			}
			switch v := val.(type) {
			case string:
				if strings.TrimSpace(v) == needle {
					return true
				}
			case []any:
				for _, item := range v {
					if s, ok := item.(string); ok && strings.TrimSpace(s) == needle {
						return true
					}
				}
			case []string:
				for _, s := range v {
					if strings.TrimSpace(s) == needle {
						return true
					}
				}
			}
		}
	}
	return false
}

func parseExperimentalAPIs() []string {
	raw := os.Getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS")
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	var out []string
	for _, p := range parts {
		if s := strings.TrimSpace(p); s != "" {
			out = append(out, s)
		}
	}
	return out
}
