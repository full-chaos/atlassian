package unit

import (
	"context"
	"net/http"
	"strconv"
	"testing"

	"atlassian/atlassian/rest"
)

func TestJiraRESTChangelogPaginationAndMapping(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/issue/A-1/changelog" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			startAt, _ := strconv.Atoi(req.URL.Query().Get("startAt"))
			switch startAt {
			case 0:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 1,
  "total": 2,
  "isLast": false,
  "values": [
    {
      "id": "100",
      "created": "2021-01-02T00:00:00.000+0000",
      "author": { "accountId": "u1", "displayName": "User 1" },
      "items": [
        { "field": "status", "fromString": "To Do", "toString": "In Progress" }
      ]
    }
  ]
}`, nil)
			case 1:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 1,
  "maxResults": 1,
  "total": 2,
  "isLast": true,
  "values": [
    {
      "id": "101",
      "created": "2021-01-03T00:00:00.000+0000",
      "items": [
        { "field": "assignee", "from": "u1", "to": "u2" }
      ]
    }
  ]
}`, nil)
			default:
				t.Fatalf("unexpected startAt=%d", startAt)
				return nil
			}
		}),
	}

	events, err := client.ListIssueChangelogViaREST(context.Background(), "A-1", 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}
	if events[0].IssueKey != "A-1" || events[0].EventID != "100" {
		t.Fatalf("unexpected event 0: %+v", events[0])
	}
	if events[0].Author == nil || events[0].Author.AccountID != "u1" {
		t.Fatalf("unexpected author: %+v", events[0].Author)
	}
	if len(events[0].Items) != 1 || events[0].Items[0].Field != "status" {
		t.Fatalf("unexpected items: %+v", events[0].Items)
	}
	if events[1].Author != nil {
		t.Fatalf("expected nil author for second event")
	}
}
