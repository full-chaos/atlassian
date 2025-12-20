package unit

import (
	"context"
	"net/http"
	"testing"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

func TestExecuteReturnsData(t *testing.T) {
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			return jsonResponse(req, http.StatusOK, `{"data":{"ok":true}}`, nil)
		}),
	}
	result, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if result == nil || result.Data["ok"] != true {
		t.Fatalf("unexpected result %+v", result)
	}
}

func TestStrictModeReturnsError(t *testing.T) {
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		Strict:  true,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			return jsonResponse(req, http.StatusOK, `{"data":{"ok":false},"errors":[{"message":"bad"}]}`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err == nil {
		t.Fatal("expected error")
	}
	if _, ok := err.(*atlassian.GraphQLOperationError); !ok {
		t.Fatalf("expected GraphQLOperationError, got %T", err)
	}
}

func TestInvalidJSONReturnsError(t *testing.T) {
	client := graph.Client{
		BaseURL: "http://example",
		Auth:    noAuth{},
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			return jsonResponse(req, http.StatusOK, `not-json`, nil)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err == nil {
		t.Fatal("expected error")
	}
	if _, ok := err.(*atlassian.JSONError); !ok {
		t.Fatalf("expected JSONError, got %T", err)
	}
}
