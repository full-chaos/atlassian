package unit

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"atlassian/atlassian/graph"
)

func TestSchemaFetcherWritesIntrospectionJSON(t *testing.T) {
	var capturedBeta []string

	outDir := t.TempDir()
	res, err := graph.FetchSchemaIntrospection(
		context.Background(),
		"http://example",
		noAuth{},
		graph.SchemaFetchOptions{
			OutputDir:        outDir,
			ExperimentalAPIs: []string{"featureA", "featureB"},
			Timeout:          2 * time.Second,
			HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
				capturedBeta = req.Header.Values("X-ExperimentalApi")
				var payload map[string]any
				if err := json.NewDecoder(req.Body).Decode(&payload); err != nil {
					t.Fatalf("decode request: %v", err)
				}
				query, _ := payload["query"].(string)
				if !strings.Contains(query, "__schema") {
					t.Fatalf("expected introspection query, got %q", query)
				}
				return jsonResponse(
					req,
					http.StatusOK,
					`{"data":{"__schema":{"queryType":{"name":"Query"},"types":[],"directives":[]}}}`,
					nil,
				)
			}),
		},
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res == nil || res.IntrospectionJSONPath == "" {
		t.Fatalf("missing result path: %+v", res)
	}
	if strings.Join(capturedBeta, ",") != "featureA,featureB" {
		t.Fatalf("unexpected experimental headers: %v", capturedBeta)
	}
	contents, err := os.ReadFile(res.IntrospectionJSONPath)
	if err != nil {
		t.Fatalf("read output: %v", err)
	}
	var envelope map[string]any
	if err := json.Unmarshal(contents, &envelope); err != nil {
		t.Fatalf("parse output: %v", err)
	}
	data, ok := envelope["data"].(map[string]any)
	if !ok {
		t.Fatalf("missing data: %v", envelope)
	}
	if _, ok := data["__schema"]; !ok {
		t.Fatalf("missing __schema in data: %v", data)
	}
}
