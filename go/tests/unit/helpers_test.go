package unit

import (
	"io"
	"net/http"
	"strings"
)

type noAuth struct{}

func (noAuth) Apply(req *http.Request) error { return nil }

type roundTripFunc func(*http.Request) *http.Response

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req), nil
}

func newHTTPClient(fn roundTripFunc) *http.Client {
	return &http.Client{Transport: fn}
}

func jsonResponse(req *http.Request, status int, body string, headers http.Header) *http.Response {
	h := headers
	if h == nil {
		h = http.Header{}
	}
	return &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     h,
		Request:    req,
	}
}
