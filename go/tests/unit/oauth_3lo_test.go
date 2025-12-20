package unit

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

func TestOAuthRefreshTokenAuthAppliesAndCachesToken(t *testing.T) {
	var tokenCalls int
	var graphqlCalls int
	var authHeaders []string

	httpClient := newHTTPClient(func(req *http.Request) *http.Response {
		switch req.URL.Path {
		case "/oauth/token":
			tokenCalls++
			var payload map[string]string
			_ = json.NewDecoder(req.Body).Decode(&payload)
			if payload["grant_type"] != "refresh_token" {
				t.Fatalf("unexpected grant_type %q", payload["grant_type"])
			}
			if payload["client_id"] != "client-id" || payload["client_secret"] != "client-secret" || payload["refresh_token"] != "refresh-token" {
				t.Fatalf("unexpected token payload: %+v", payload)
			}
			return jsonResponse(req, http.StatusOK, `{"access_token":"access-1","token_type":"Bearer","expires_in":3600}`, nil)
		case "/graphql":
			graphqlCalls++
			authHeaders = append(authHeaders, req.Header.Get("Authorization"))
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		default:
			return jsonResponse(req, http.StatusNotFound, `{"error":"not found"}`, nil)
		}
	})

	auth := &atlassian.OAuthRefreshTokenAuth{
		ClientID:     "client-id",
		ClientSecret: "client-secret",
		RefreshToken: "refresh-token",
		TokenURL:     "http://example/oauth/token",
		HTTPClient:   httpClient,
	}

	client := graph.Client{
		BaseURL:    "http://example",
		Auth:       auth,
		HTTPClient: httpClient,
	}

	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	_, err = client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if tokenCalls != 1 {
		t.Fatalf("expected 1 token call, got %d", tokenCalls)
	}
	if graphqlCalls != 2 {
		t.Fatalf("expected 2 graphql calls, got %d", graphqlCalls)
	}
	if len(authHeaders) != 2 || authHeaders[0] != "Bearer access-1" || authHeaders[1] != "Bearer access-1" {
		t.Fatalf("unexpected auth headers: %#v", authHeaders)
	}
}
