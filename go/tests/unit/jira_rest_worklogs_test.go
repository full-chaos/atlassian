package unit

import (
	"context"
	"net/http"
	"strconv"
	"testing"

	"atlassian/atlassian/rest"
)

func TestJiraRESTWorklogsPaginationAndMapping(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/issue/A-1/worklog" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			startAt, _ := strconv.Atoi(req.URL.Query().Get("startAt"))
			switch startAt {
			case 0:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 1,
  "total": 2,
  "worklogs": [
    {
      "id": "200",
      "author": { "accountId": "u1", "displayName": "User 1" },
      "started": "2021-01-02T00:00:00.000+0000",
      "timeSpentSeconds": 60,
      "created": "2021-01-02T00:00:00.000+0000",
      "updated": "2021-01-02T00:00:00.000+0000"
    }
  ]
}`, nil)
			case 1:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 1,
  "maxResults": 1,
  "total": 2,
  "worklogs": [
    {
      "id": "201",
      "started": "2021-01-03T00:00:00.000+0000",
      "timeSpentSeconds": 120,
      "created": "2021-01-03T00:00:00.000+0000",
      "updated": "2021-01-03T00:00:00.000+0000"
    }
  ]
}`, nil)
			default:
				t.Fatalf("unexpected startAt=%d", startAt)
				return nil
			}
		}),
	}

	worklogs, err := client.ListIssueWorklogsViaREST(context.Background(), "A-1", 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(worklogs) != 2 {
		t.Fatalf("expected 2 worklogs, got %d", len(worklogs))
	}
	if worklogs[0].IssueKey != "A-1" || worklogs[0].WorklogID != "200" || worklogs[0].TimeSpentSeconds != 60 {
		t.Fatalf("unexpected worklog 0: %+v", worklogs[0])
	}
	if worklogs[0].Author == nil || worklogs[0].Author.AccountID != "u1" {
		t.Fatalf("unexpected author: %+v", worklogs[0].Author)
	}
	if worklogs[1].Author != nil {
		t.Fatalf("expected nil author for second worklog")
	}
}
