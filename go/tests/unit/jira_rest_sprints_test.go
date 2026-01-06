package unit

import (
	"context"
	"net/http"
	"strconv"
	"testing"

	"atlassian/atlassian/rest"
)

func TestJiraRESTSprintsPaginationAndMapping(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/agile/1.0/board/10/sprint" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			startAt, _ := strconv.Atoi(req.URL.Query().Get("startAt"))
			switch startAt {
			case 0:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 1,
  "isLast": false,
  "values": [
    {
      "id": 100,
      "name": "Sprint 1",
      "state": "active",
      "startDate": "2021-01-01T00:00:00.000Z",
      "endDate": "2021-01-15T00:00:00.000Z"
    }
  ]
}`, nil)
			case 1:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 1,
  "maxResults": 1,
  "isLast": true,
  "values": [
    {
      "id": 101,
      "name": "Sprint 2",
      "state": "closed",
      "startDate": "2021-01-16T00:00:00.000Z",
      "endDate": "2021-01-30T00:00:00.000Z",
      "completeDate": "2021-01-30T12:00:00.000Z"
    }
  ]
}`, nil)
			default:
				t.Fatalf("unexpected startAt=%d", startAt)
				return nil
			}
		}),
	}

	sprints, err := client.ListBoardSprintsViaREST(context.Background(), 10, "", 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sprints) != 2 {
		t.Fatalf("expected 2 sprints, got %d", len(sprints))
	}
	if sprints[0].ID != "100" || sprints[0].Name != "Sprint 1" || sprints[0].State != "active" {
		t.Fatalf("unexpected sprint 0: %+v", sprints[0])
	}
	if sprints[0].StartAt == nil || *sprints[0].StartAt != "2021-01-01T00:00:00.000Z" {
		t.Fatalf("unexpected start date for sprint 0: %v", sprints[0].StartAt)
	}
	if sprints[0].CompleteAt != nil {
		t.Fatalf("expected nil complete date for sprint 0")
	}

	if sprints[1].ID != "101" || sprints[1].Name != "Sprint 2" || sprints[1].State != "closed" {
		t.Fatalf("unexpected sprint 1: %+v", sprints[1])
	}
	if sprints[1].CompleteAt == nil || *sprints[1].CompleteAt != "2021-01-30T12:00:00.000Z" {
		t.Fatalf("unexpected complete date for sprint 1: %v", sprints[1].CompleteAt)
	}
}

func TestListBoardSprintsRequiresPositiveBoardID(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			return jsonResponse(req, http.StatusOK, `{}`, nil)
		}),
	}

	_, err := client.ListBoardSprintsViaREST(context.Background(), 0, "", 50)
	if err == nil {
		t.Fatalf("expected error for boardID=0")
	}
	if err.Error() != "boardID must be a positive integer" {
		t.Fatalf("unexpected error: %v", err)
	}

	_, err = client.ListBoardSprintsViaREST(context.Background(), -1, "", 50)
	if err == nil {
		t.Fatalf("expected error for boardID=-1")
	}
}

func TestListBoardSprintsValidatesStateFilter(t *testing.T) {
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			return jsonResponse(req, http.StatusOK, `{}`, nil)
		}),
	}

	_, err := client.ListBoardSprintsViaREST(context.Background(), 10, "invalid", 50)
	if err == nil {
		t.Fatalf("expected error for invalid state")
	}
	if err.Error() != "state must be one of: future, active, closed" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestListBoardSprintsWithStateFilter(t *testing.T) {
	called := false
	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			called = true
			state := req.URL.Query().Get("state")
			if state != "active" {
				t.Fatalf("expected state=active, got %s", state)
			}
			return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 50,
  "isLast": true,
  "values": [
    {
      "id": 100,
      "name": "Sprint 1",
      "state": "active"
    }
  ]
}`, nil)
		}),
	}

	sprints, err := client.ListBoardSprintsViaREST(context.Background(), 10, "active", 50)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !called {
		t.Fatalf("expected HTTP call")
	}
	if len(sprints) != 1 {
		t.Fatalf("expected 1 sprint, got %d", len(sprints))
	}
	if sprints[0].State != "active" {
		t.Fatalf("expected state=active, got %s", sprints[0].State)
	}
}
