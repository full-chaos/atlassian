package unit

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"atlassian/atlassian/graph"
)

func TestJiraProjectsRetriesOn429RetryAfterTimestamp(t *testing.T) {
	now := time.Date(2021, 5, 10, 10, 59, 58, 0, time.UTC)
	var slept []time.Duration
	attempts := 0

	client := graph.Client{
		BaseURL:       "http://example",
		Auth:          noAuth{},
		MaxRetries429: 1,
		Now:           func() time.Time { return now },
		Sleep: func(d time.Duration) {
			slept = append(slept, d)
			now = now.Add(d)
		},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			attempts++
			var payload map[string]any
			if err := json.NewDecoder(req.Body).Decode(&payload); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			if attempts == 1 {
				headers := http.Header{}
				headers.Set("Retry-After", "2021-05-10T11:00Z")
				return jsonResponse(req, http.StatusTooManyRequests, `{"extensions":{"requestId":"abc-123"}}`, headers)
			}
			return jsonResponse(req, http.StatusOK, `{
  "data": {
    "jira": {
      "projects": { "pageInfo": { "hasNextPage": false, "endCursor": null }, "edges": [] }
    }
  }
}`, nil)
		}),
	}

	projects, err := client.ListProjectsWithOpsgenieLinkableTeams(context.Background(), "cloud-123", []string{"SOFTWARE"}, 50)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(projects) != 0 {
		t.Fatalf("expected empty projects, got %d", len(projects))
	}
	if attempts != 2 {
		t.Fatalf("expected 2 attempts, got %d", attempts)
	}
	if len(slept) != 1 || slept[0] != 2*time.Second {
		t.Fatalf("expected single 2s sleep, got %v", slept)
	}
}
