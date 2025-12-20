package unit

import (
	"context"
	"encoding/base64"
	"net/http"
	"strings"
	"testing"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

func TestBearerAuthHeaderSet(t *testing.T) {
	var authHeader string

	client := graph.Client{
		BaseURL: "http://example",
		Auth: atlassian.BearerAuth{
			TokenGetter: func() (string, error) { return "token123", nil },
		},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			authHeader = req.Header.Get("Authorization")
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if authHeader != "Bearer token123" {
		t.Fatalf("unexpected auth header %q", authHeader)
	}
}

func TestBearerAuthStripsBearerPrefix(t *testing.T) {
	var authHeader string

	client := graph.Client{
		BaseURL: "http://example",
		Auth: atlassian.BearerAuth{
			TokenGetter: func() (string, error) { return "Bearer token123", nil },
		},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			authHeader = req.Header.Get("Authorization")
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if authHeader != "Bearer token123" {
		t.Fatalf("unexpected auth header %q", authHeader)
	}
}

func TestBasicAuthHeader(t *testing.T) {
	var authHeader string

	client := graph.Client{
		BaseURL: "http://example",
		Auth: atlassian.BasicAPITokenAuth{
			Email: "user@example.com",
			Token: "apitoken",
		},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			authHeader = req.Header.Get("Authorization")
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.HasPrefix(authHeader, "Basic ") {
		t.Fatalf("expected basic auth header, got %q", authHeader)
	}
	decoded, _ := base64.StdEncoding.DecodeString(strings.TrimPrefix(authHeader, "Basic "))
	if string(decoded) != "user@example.com:apitoken" {
		t.Fatalf("unexpected basic credentials %q", string(decoded))
	}
}

func TestCookieAuthSetsCookies(t *testing.T) {
	var cookieHeader string

	client := graph.Client{
		BaseURL: "http://example",
		Auth: atlassian.CookieAuth{
			Cookies: []*http.Cookie{
				{Name: "session", Value: "abc"},
				{Name: "xsrf", Value: "123"},
			},
		},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			cookieHeader = req.Header.Get("Cookie")
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(cookieHeader, "session=abc") {
		t.Fatalf("expected session cookie, got %q", cookieHeader)
	}
}
