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

func TestGraphSprintByID(t *testing.T) {
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			var body map[string]any
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			if body["operationName"] != "JiraSprintById" {
				t.Fatalf("unexpected operationName: %v", body["operationName"])
			}
			if strings.TrimSpace(body["query"].(string)) != strings.TrimSpace(gen.JiraSprintByIdQuery) {
				t.Fatalf("unexpected query")
			}
			vars := body["variables"].(map[string]any)
			if vars["id"] != "sprint-1" {
				t.Fatalf("unexpected variables: %+v", vars)
			}
			return jsonResponse(req, http.StatusOK, `{
  "data": {
    "sprintById": {
      "sprintId": "42",
      "name": "Sprint 42",
      "state": "ACTIVE",
      "startDate": "2021-01-01T00:00:00Z",
      "endDate": "2021-01-14T00:00:00Z",
      "completionDate": "2021-01-15T00:00:00Z"
    }
  }
}`, nil)
		}),
	}

	sprint, err := client.GetSprintByID(context.Background(), "sprint-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sprint.ID != "42" || sprint.Name != "Sprint 42" || sprint.State != "ACTIVE" {
		t.Fatalf("unexpected sprint: %+v", sprint)
	}
	if sprint.StartAt == nil || *sprint.StartAt != "2021-01-01T00:00:00Z" {
		t.Fatalf("unexpected startAt: %+v", sprint.StartAt)
	}
}
