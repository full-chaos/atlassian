//go:build integration
// +build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"atlassian-graphql/graphql"
	"log/slog"
)

func TestLiveSmoke(t *testing.T) {
	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	if baseURL == "" {
		t.Skip("ATLASSIAN_GQL_BASE_URL not set")
	}
	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}

	buf := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(buf, &slog.HandlerOptions{Level: slog.LevelDebug}))

	client := graphql.Client{
		BaseURL:       baseURL,
		Auth:          auth,
		Strict:        false,
		MaxRetries429: 1,
		Logger:        logger,
		HTTPClient:    &http.Client{Timeout: 30 * time.Second},
	}

	result, err := client.Execute(
		context.Background(),
		"query { __schema { queryType { name } } }",
		nil,
		"",
		nil,
		1,
	)
	if err != nil {
		if rlErr, ok := err.(*graphql.RateLimitError); ok {
			if !strings.Contains(buf.String(), "rate limited") {
				t.Fatalf("rate limit encountered without warning log: %v", rlErr)
			}
			t.Skipf("rate limited during integration; retry-after=%s", rlErr.HeaderValue)
		}
		t.Fatalf("unexpected error: %v", err)
	}
	if result == nil || result.Data == nil {
		t.Fatalf("missing data in response: %+v", result)
	}
	if strings.Contains(buf.String(), "rate limited") {
		if strings.Count(buf.String(), "rate limited") > 2 {
			t.Fatalf("expected at most one retry for natural 429, logs=%s", buf.String())
		}
	}
}

func buildAuth(t *testing.T) graphql.AuthProvider {
	token := os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
	email := os.Getenv("ATLASSIAN_EMAIL")
	apiToken := os.Getenv("ATLASSIAN_API_TOKEN")
	cookiesJSON := os.Getenv("ATLASSIAN_COOKIES_JSON")

	if token != "" {
		return graphql.BearerAuth{
			TokenGetter: func() (string, error) { return token, nil },
		}
	}
	if email != "" && apiToken != "" {
		return graphql.BasicAPITokenAuth{
			Email: email,
			Token: apiToken,
		}
	}
	if cookiesJSON != "" {
		var cookies map[string]string
		if err := json.Unmarshal([]byte(cookiesJSON), &cookies); err == nil && len(cookies) > 0 {
			var httpCookies []*http.Cookie
			for k, v := range cookies {
				httpCookies = append(httpCookies, &http.Cookie{Name: k, Value: v})
			}
			return graphql.CookieAuth{Cookies: httpCookies}
		}
	}

	return nil
}
