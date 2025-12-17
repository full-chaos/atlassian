package unit

import (
	"context"
	"net/http"
	"reflect"
	"testing"

	"atlassian-graphql/graphql"
)

func TestExperimentalHeadersRepeated(t *testing.T) {
	var headers []string

	client := graphql.Client{
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
