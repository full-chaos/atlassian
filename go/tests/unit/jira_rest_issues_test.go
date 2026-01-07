package unit

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"testing"

	"atlassian/atlassian/rest"
)

func TestJiraRESTIssuesPaginationAndMapping(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/search" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			if req.URL.Query().Get("jql") == "" {
				t.Fatalf("expected jql param")
			}
			if req.URL.Query().Get("fields") == "" {
				t.Fatalf("expected fields param")
			}

			startAt, _ := strconv.Atoi(req.URL.Query().Get("startAt"))
			switch startAt {
			case 0:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 2,
  "total": 3,
  "issues": [
    {
      "id": "1",
      "key": "A-1",
      "fields": {
        "project": { "key": "A" },
        "issuetype": { "name": "Bug" },
        "status": { "name": "Done" },
        "created": "2021-01-01T00:00:00.000+0000",
        "updated": "2021-01-02T00:00:00.000+0000",
        "labels": ["l1"],
        "components": [{ "name": "Comp1" }]
      }
    },
    {
      "id": "2",
      "key": "A-2",
      "fields": {
        "project": { "key": "A" },
        "issuetype": { "name": "Task" },
        "status": { "name": "To Do" },
        "created": "2021-01-03T00:00:00.000+0000",
        "updated": "2021-01-04T00:00:00.000+0000",
        "assignee": { "accountId": "u1", "displayName": "User 1" },
        "reporter": { "accountId": "u2", "displayName": "User 2" }
      }
    }
  ]
}`, nil)
			case 2:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 2,
  "maxResults": 2,
  "total": 3,
  "issues": [
    {
      "id": "3",
      "key": "A-3",
      "fields": {
        "project": { "key": "A" },
        "issuetype": { "name": "Story" },
        "status": { "name": "In Progress" },
        "created": "2021-01-05T00:00:00.000+0000",
        "updated": "2021-01-06T00:00:00.000+0000",
        "resolutiondate": "2021-01-07T00:00:00.000+0000"
      }
    }
  ]
}`, nil)
			default:
				t.Fatalf("unexpected startAt=%d", startAt)
				return nil
			}
		}),
	}

	issues, err := client.ListIssuesViaREST(context.Background(), "cloud-123", "project = A ORDER BY created DESC", 2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(issues) != 3 {
		t.Fatalf("expected 3 issues, got %d", len(issues))
	}
	if issues[0].CloudID != "cloud-123" || issues[0].Key != "A-1" || issues[0].ProjectKey != "A" {
		t.Fatalf("unexpected issue 1: %+v", issues[0])
	}
	if len(issues[0].Labels) != 1 || issues[0].Labels[0] != "l1" {
		t.Fatalf("unexpected labels: %+v", issues[0].Labels)
	}
	if len(issues[0].Components) != 1 || issues[0].Components[0] != "Comp1" {
		t.Fatalf("unexpected components: %+v", issues[0].Components)
	}
	if issues[1].Assignee == nil || issues[1].Assignee.AccountID != "u1" {
		t.Fatalf("unexpected assignee: %+v", issues[1].Assignee)
	}
	if issues[2].ResolvedAt == nil {
		t.Fatalf("expected resolvedAt for issue 3")
	}
}

func TestJiraRESTIssuesCustomFields(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/search" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			fields := req.URL.Query().Get("fields")
			if fields == "" {
				t.Fatalf("expected fields param")
			}
			if !strings.Contains(fields, "customfield_10016") {
				t.Fatalf("missing story points field in query")
			}
			if !strings.Contains(fields, "customfield_10020") {
				t.Fatalf("missing sprint ids field in query")
			}
			return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 50,
  "total": 1,
  "issues": [
    {
      "id": "1",
      "key": "A-1",
      "fields": {
        "project": { "key": "A" },
        "issuetype": { "name": "Bug" },
        "status": { "name": "Done" },
        "created": "2021-01-01T00:00:00.000+0000",
        "updated": "2021-01-02T00:00:00.000+0000",
        "customfield_10016": 8,
        "customfield_10020": [{"id": 101}, {"id": "102"}]
      }
    }
  ]
}`, nil)
		}),
	}

	issues, err := client.ListIssuesViaRESTWithFields(
		context.Background(),
		"cloud-123",
		"project = A",
		50,
		"customfield_10016",
		"customfield_10020",
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(issues) != 1 {
		t.Fatalf("expected 1 issue, got %d", len(issues))
	}
	if issues[0].StoryPoints == nil || *issues[0].StoryPoints != 8 {
		t.Fatalf("unexpected story points: %+v", issues[0].StoryPoints)
	}
	if len(issues[0].SprintIDs) != 2 || issues[0].SprintIDs[0] != "101" || issues[0].SprintIDs[1] != "102" {
		t.Fatalf("unexpected sprint ids: %+v", issues[0].SprintIDs)
	}
}

func TestJiraRESTIssuesEnvFields(t *testing.T) {
	t.Setenv("ATLASSIAN_JIRA_STORY_POINTS_FIELD", "customfield_10016")
	t.Setenv("ATLASSIAN_JIRA_SPRINT_IDS_FIELD", "customfield_10020")

	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/search" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			fields := req.URL.Query().Get("fields")
			if fields == "" {
				t.Fatalf("expected fields param")
			}
			if !strings.Contains(fields, "customfield_10016") {
				t.Fatalf("missing story points field in query")
			}
			if !strings.Contains(fields, "customfield_10020") {
				t.Fatalf("missing sprint ids field in query")
			}
			return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 1,
  "total": 1,
  "issues": [
    {
      "id": "1",
      "key": "A-1",
      "fields": {
        "project": { "key": "A" },
        "issuetype": { "name": "Bug" },
        "status": { "name": "Done" },
        "created": "2021-01-01T00:00:00.000+0000",
        "updated": "2021-01-02T00:00:00.000+0000",
        "customfield_10016": "5",
        "customfield_10020": [101, 102]
      }
    }
  ]
}`, nil)
		}),
	}

	issues, err := client.ListIssuesViaREST(context.Background(), "cloud-123", "project = A", 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(issues) != 1 {
		t.Fatalf("expected 1 issue, got %d", len(issues))
	}
	if issues[0].StoryPoints == nil || *issues[0].StoryPoints != 5 {
		t.Fatalf("unexpected story points: %+v", issues[0].StoryPoints)
	}
	if len(issues[0].SprintIDs) != 2 {
		t.Fatalf("unexpected sprint ids: %+v", issues[0].SprintIDs)
	}
}
