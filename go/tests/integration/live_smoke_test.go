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

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
	"log/slog"
)

func TestLiveSmoke(t *testing.T) {
	loadDotEnvIfPresent(t)

	baseURL := os.Getenv("ATLASSIAN_GQL_BASE_URL")
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")) != "" {
		baseURL = "https://api.atlassian.com"
	}
	auth := buildAuth(t)
	if auth == nil {
		t.Skip("no credentials available")
	}
	if baseURL == "" {
		t.Skip("ATLASSIAN_GQL_BASE_URL not set (required for non-OAuth auth modes)")
	}

	buf := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(buf, &slog.HandlerOptions{Level: slog.LevelDebug}))

	client := graph.Client{
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
		if rlErr, ok := err.(*atlassian.RateLimitError); ok {
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

func buildAuth(t *testing.T) atlassian.AuthProvider {
	token := os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")
	refreshToken := os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")
	clientID := os.Getenv("ATLASSIAN_CLIENT_ID")
	email := os.Getenv("ATLASSIAN_EMAIL")
	apiToken := os.Getenv("ATLASSIAN_API_TOKEN")
	cookiesJSON := os.Getenv("ATLASSIAN_COOKIES_JSON")
	clientSecret := os.Getenv("ATLASSIAN_CLIENT_SECRET")

	if strings.TrimSpace(refreshToken) != "" && strings.TrimSpace(clientID) != "" && strings.TrimSpace(clientSecret) != "" {
		return &atlassian.OAuthRefreshTokenAuth{
			ClientID:     clientID,
			ClientSecret: clientSecret,
			RefreshToken: refreshToken,
			Timeout:      30 * time.Second,
		}
	}
	if token != "" {
		if clientSecret != "" && strings.TrimSpace(token) == strings.TrimSpace(clientSecret) {
			t.Fatal("ATLASSIAN_OAUTH_ACCESS_TOKEN appears to be set to ATLASSIAN_CLIENT_SECRET; set an OAuth access token (not the client secret)")
		}
		return atlassian.BearerAuth{
			TokenGetter: func() (string, error) { return token, nil },
		}
	}
	if email != "" && apiToken != "" {
		return atlassian.BasicAPITokenAuth{
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
			return atlassian.CookieAuth{Cookies: httpCookies}
		}
	}

	return nil
}
