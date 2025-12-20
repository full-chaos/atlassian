package unit

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"

	"atlassian/atlassian/graph"
	"atlassian/atlassian/graph/gen"
)

func TestJiraProjectsPaginationOuterAndNested(t *testing.T) {
	var calls []string

	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			var payload map[string]any
			if err := json.NewDecoder(req.Body).Decode(&payload); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			op, _ := payload["operationName"].(string)
			calls = append(calls, op)

			vars, _ := payload["variables"].(map[string]any)
			switch op {
			case "JiraProjectsPage":
				after, _ := vars["after"].(string)
				if after == "" {
					after = ""
				}
				if vars["after"] == nil || after == "" {
					return jsonResponse(req, http.StatusOK, `{
  "data": {
    "jira": {
      "projects": {
        "pageInfo": { "hasNextPage": true, "endCursor": "P1" },
        "edges": [
          {
            "cursor": "pc1",
            "node": {
              "id": "projA",
              "key": "A",
              "name": "Project A",
              "opsgenieTeams": {
                "pageInfo": { "hasNextPage": true, "endCursor": "TA1" },
                "edges": [
                  { "cursor": "tc1", "node": { "id": "t1", "name": "Team 1" } },
                  { "cursor": "tc2", "node": { "id": "t2", "name": "Team 2" } }
                ]
              }
            }
          },
          {
            "cursor": "pc2",
            "node": {
              "id": "projB",
              "key": "B",
              "name": "Project B",
              "opsgenieTeams": {
                "pageInfo": { "hasNextPage": false, "endCursor": null },
                "edges": []
              }
            }
          }
        ]
      }
    }
  }
}`, nil)
				}
				if after == "P1" {
					return jsonResponse(req, http.StatusOK, `{
  "data": {
    "jira": {
      "projects": {
        "pageInfo": { "hasNextPage": false, "endCursor": null },
        "edges": [
          {
            "cursor": "pc3",
            "node": {
              "id": "projC",
              "key": "C",
              "name": "Project C",
              "opsgenieTeams": {
                "pageInfo": { "hasNextPage": false, "endCursor": null },
                "edges": [
                  { "cursor": "tc4", "node": { "id": "t4", "name": "Team 4" } }
                ]
              }
            }
          }
        ]
      }
    }
  }
}`, nil)
				}
				t.Fatalf("unexpected JiraProjectsPage after=%v", vars["after"])

			case "JiraProjectOpsgenieTeamsPage":
				if vars["after"] != "TA1" {
					t.Fatalf("unexpected opsgenie after=%v", vars["after"])
				}
				if gen.RefetchStrategy == "node" {
					if vars["projectId"] != "projA" {
						t.Fatalf("unexpected projectId=%v", vars["projectId"])
					}
					return jsonResponse(req, http.StatusOK, `{
  "data": {
    "project": {
      "opsgenieTeams": {
        "pageInfo": { "hasNextPage": false, "endCursor": null },
        "edges": [
          { "cursor": "tc3", "node": { "id": "t3", "name": "Team 3" } }
        ]
      }
    }
  }
}`, nil)
				}
				if vars["cloudId"] != "cloud-123" || vars["projectKey"] != "A" {
					t.Fatalf("unexpected vars for jira strategy: %v", vars)
				}
				return jsonResponse(req, http.StatusOK, `{
  "data": {
    "jira": {
      "project": {
        "opsgenieTeams": {
          "pageInfo": { "hasNextPage": false, "endCursor": null },
          "edges": [
            { "cursor": "tc3", "node": { "id": "t3", "name": "Team 3" } }
          ]
        }
      }
    }
  }
}`, nil)
			default:
				t.Fatalf("unexpected operationName %q", op)
			}
			return nil
		}),
	}

	results, err := client.ListProjectsWithOpsgenieLinkableTeams(context.Background(), "cloud-123", []string{"software"}, 2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 3 {
		t.Fatalf("expected 3 results, got %d", len(results))
	}
	if results[0].Project.CloudID != "cloud-123" || results[0].Project.Key != "A" || results[0].Project.Name != "Project A" {
		t.Fatalf("unexpected project A: %+v", results[0].Project)
	}
	if len(results[0].OpsgenieTeams) != 3 {
		t.Fatalf("expected 3 opsgenie teams for A, got %d", len(results[0].OpsgenieTeams))
	}
	if results[1].Project.Key != "B" || len(results[1].OpsgenieTeams) != 0 {
		t.Fatalf("unexpected project B: %+v", results[1])
	}
	if results[2].Project.Key != "C" || len(results[2].OpsgenieTeams) != 1 || results[2].OpsgenieTeams[0].ID != "t4" {
		t.Fatalf("unexpected project C: %+v", results[2])
	}

	expected := []string{"JiraProjectsPage", "JiraProjectOpsgenieTeamsPage", "JiraProjectsPage"}
	if len(calls) != len(expected) {
		t.Fatalf("unexpected call count %v", calls)
	}
	for i := range expected {
		if calls[i] != expected[i] {
			t.Fatalf("unexpected call order %v", calls)
		}
	}
}
