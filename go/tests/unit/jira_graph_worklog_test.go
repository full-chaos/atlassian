package unit

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"

	"atlassian/atlassian/graph"
	"atlassian/atlassian/graph/gen"
)

func TestGraphWorklogsPagination(t *testing.T) {
	call := 0
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			call++
			var body map[string]any
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			if body["operationName"] != "JiraIssueWorklogsPage" {
				t.Fatalf("unexpected operationName: %v", body["operationName"])
			}
			if strings.TrimSpace(body["query"].(string)) != strings.TrimSpace(gen.JiraIssueWorklogsPageQuery) {
				t.Fatalf("unexpected query")
			}
			vars := body["variables"].(map[string]any)
			after := vars["after"]
			if call == 1 && after != nil {
				t.Fatalf("unexpected after for first page: %v", after)
			}
			if call == 2 && after != "c1" {
				t.Fatalf("unexpected after for second page: %v", after)
			}
			if call == 1 {
				return jsonResponse(req, http.StatusOK, `{
  "data": {
    "issue": {
      "worklogs": {
        "pageInfo": { "hasNextPage": true, "endCursor": "c1" },
        "edges": [
          {
            "cursor": "e1",
            "node": {
              "worklogId": "w1",
              "author": { "accountId": "u1", "name": "User One" },
              "timeSpent": { "timeInSeconds": 60 },
              "created": "2021-01-01T00:00:00Z",
              "updated": "2021-01-01T01:00:00Z",
              "startDate": "2021-01-01T00:00:00Z"
            }
          }
        ]
      }
    }
  }
}`, nil)
			}
			return jsonResponse(req, http.StatusOK, `{
  "data": {
    "issue": {
      "worklogs": {
        "pageInfo": { "hasNextPage": false, "endCursor": null },
        "edges": [
          {
            "cursor": "e2",
            "node": {
              "worklogId": "w2",
              "author": { "accountId": "u2", "name": "User Two" },
              "timeSpent": { "timeInSeconds": 120 },
              "created": "2021-01-02T00:00:00Z",
              "updated": "2021-01-02T01:00:00Z",
              "startDate": "2021-01-02T00:00:00Z"
            }
          }
        ]
      }
    }
  }
}`, nil)
		}),
	}

	worklogs, err := client.ListIssueWorklogs(context.Background(), "cloud-123", "A-1", 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(worklogs) != 2 {
		t.Fatalf("expected 2 worklogs, got %d", len(worklogs))
	}
	if worklogs[0].WorklogID != "w1" || worklogs[1].WorklogID != "w2" {
		t.Fatalf("unexpected worklog ids: %+v", worklogs)
	}
	if worklogs[1].TimeSpentSeconds != 120 {
		t.Fatalf("unexpected time spent: %+v", worklogs[1].TimeSpentSeconds)
	}
}
