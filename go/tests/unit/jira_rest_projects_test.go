package unit

import (
	"context"
	"net/http"
	"strconv"
	"testing"
	"time"

	"atlassian/atlassian/rest"
)

func TestJiraRESTProjectsPaginationAndFiltering(t *testing.T) {
	var calls []int

	client := rest.JiraRESTClient{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			if req.URL.Path != "/rest/api/3/project/search" {
				t.Fatalf("unexpected path %s", req.URL.Path)
			}
			maxResults := req.URL.Query().Get("maxResults")
			if maxResults != "2" {
				t.Fatalf("unexpected maxResults=%s", maxResults)
			}
			startAtStr := req.URL.Query().Get("startAt")
			startAt, _ := strconv.Atoi(startAtStr)
			calls = append(calls, startAt)

			switch startAt {
			case 0:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 0,
  "maxResults": 2,
  "total": 3,
  "isLast": false,
  "values": [
    { "key": "A", "name": "Project A", "projectTypeKey": "software" },
    { "key": "B", "name": "Project B", "projectTypeKey": "business" }
  ]
}`, nil)
			case 2:
				return jsonResponse(req, http.StatusOK, `{
  "startAt": 2,
  "maxResults": 2,
  "total": 3,
  "isLast": true,
  "values": [
    { "key": "C", "name": "Project C", "projectTypeKey": "software" }
  ]
}`, nil)
			default:
				t.Fatalf("unexpected startAt=%d", startAt)
				return nil
			}
		}),
	}

	results, err := client.ListProjectsViaREST(context.Background(), "cloud-123", []string{"SOFTWARE"}, 2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
	if results[0].Project.CloudID != "cloud-123" || results[0].Project.Key != "A" || results[0].Project.Name != "Project A" {
		t.Fatalf("unexpected project A: %+v", results[0].Project)
	}
	if len(results[0].OpsgenieTeams) != 0 {
		t.Fatalf("expected empty opsgenie teams, got %d", len(results[0].OpsgenieTeams))
	}
	if results[1].Project.Key != "C" {
		t.Fatalf("unexpected project C: %+v", results[1].Project)
	}
	if len(calls) != 2 || calls[0] != 0 || calls[1] != 2 {
		t.Fatalf("unexpected pagination calls: %v", calls)
	}
}

func TestJiraRESTClientRetriesOn429RetryAfterSeconds(t *testing.T) {
	current := time.Date(2021, 5, 10, 10, 59, 58, 0, time.UTC)
	nowFn := func() time.Time { return current }
	var slept []time.Duration
	sleepFn := func(d time.Duration) {
		slept = append(slept, d)
		current = current.Add(d)
	}

	call := 0
	client := rest.JiraRESTClient{
		BaseURL:       "http://example",
		Auth:          noAuth{},
		MaxRetries429: 1,
		Now:           nowFn,
		Sleep:         sleepFn,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			call++
			if call == 1 {
				h := http.Header{}
				h.Set("Retry-After", "2")
				return jsonResponse(req, http.StatusTooManyRequests, `{}`, h)
			}
			if call == 2 {
				return jsonResponse(req, http.StatusOK, `{"ok": true}`, nil)
			}
			t.Fatalf("unexpected call=%d", call)
			return nil
		}),
	}

	payload, err := client.GetJSON(context.Background(), "/rest/api/3/project/search", map[string]string{"startAt": "0", "maxResults": "1"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ok, _ := payload["ok"].(bool); !ok {
		t.Fatalf("expected ok=true payload, got %v", payload)
	}
	if len(slept) != 1 || slept[0] != 2*time.Second {
		t.Fatalf("unexpected slept=%v", slept)
	}
}
