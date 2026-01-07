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

func TestGraphIssueByKey(t *testing.T) {
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			var body map[string]any
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			if body["operationName"] != "JiraIssueByKey" {
				t.Fatalf("unexpected operationName: %v", body["operationName"])
			}
			if strings.TrimSpace(body["query"].(string)) != strings.TrimSpace(gen.JiraIssueByKeyQuery) {
				t.Fatalf("unexpected query")
			}
			vars := body["variables"].(map[string]any)
			if vars["cloudId"] != "cloud-123" || vars["key"] != "A-1" {
				t.Fatalf("unexpected variables: %+v", vars)
			}
			return jsonResponse(req, http.StatusOK, `{
  "data": {
    "issueByKey": {
      "key": "A-1",
      "issueType": { "name": "Bug" },
      "status": { "name": "Done" },
      "projectField": { "project": { "key": "A", "cloudId": "cloud-123" } },
      "createdField": { "dateTime": "2021-01-01T00:00:00Z" },
      "updatedField": { "dateTime": "2021-01-02T00:00:00Z" },
      "resolutionDateField": { "dateTime": "2021-01-03T00:00:00Z" },
      "assigneeField": { "user": { "accountId": "u1", "name": "User One" } },
      "reporter": { "accountId": "u2", "name": "User Two" }
    }
  }
}`, nil)
		}),
	}

	issue, err := client.GetIssueByKey(context.Background(), "cloud-123", "A-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if issue.Key != "A-1" || issue.ProjectKey != "A" || issue.IssueType != "Bug" || issue.Status != "Done" {
		t.Fatalf("unexpected issue: %+v", issue)
	}
	if issue.Assignee == nil || issue.Assignee.AccountID != "u1" {
		t.Fatalf("unexpected assignee: %+v", issue.Assignee)
	}
	if issue.Reporter == nil || issue.Reporter.AccountID != "u2" {
		t.Fatalf("unexpected reporter: %+v", issue.Reporter)
	}
	if issue.ResolvedAt == nil {
		t.Fatalf("expected resolvedAt")
	}
}
