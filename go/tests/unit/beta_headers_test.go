package unit

import (
	"context"
	"net/http"
	"reflect"
	"testing"

	"atlassian/atlassian/graph"
)

func TestExperimentalHeadersRepeated(t *testing.T) {
	var headers []string

	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			headers = req.Header.Values("X-ExperimentalApi")
			return jsonResponse(req, http.StatusOK, `{"data":{}}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", []string{"a", "b"}, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !reflect.DeepEqual(headers, []string{"a", "b"}) {
		t.Fatalf("unexpected experimental headers %v", headers)
	}
}

func TestExperimentalHeadersAppliedToJiraProjects(t *testing.T) {
	var all [][]string

	client := graph.Client{
		BaseURL:          "http://example",
		Auth:             noAuth{},
		ExperimentalAPIs: []string{"a", "b"},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			all = append(all, req.Header.Values("X-ExperimentalApi"))
			return jsonResponse(req, http.StatusOK, `{
  "data": {
    "jira": {
      "projects": { "pageInfo": { "hasNextPage": false, "endCursor": null }, "edges": [] }
    }
  }
}`, nil)
		}),
	}

	_, err := client.ListProjectsWithOpsgenieLinkableTeams(context.Background(), "cloud-123", []string{"SOFTWARE"}, 50)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(all) != 1 {
		t.Fatalf("expected one request, got %d", len(all))
	}
	if !reflect.DeepEqual(all[0], []string{"a", "b"}) {
		t.Fatalf("unexpected experimental headers %v", all[0])
	}
}
