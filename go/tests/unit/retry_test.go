package unit

import (
	"context"
	"net/http"
	"testing"
	"time"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

func TestRetryOn429TimestampHeader(t *testing.T) {
	now := time.Date(2021, 5, 10, 10, 59, 58, 0, time.UTC)
	attempts := 0
	var slept []time.Duration

	client := graph.Client{
		BaseURL:       "http://example",
		Auth:          noAuth{},
		MaxRetries429: 1,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			attempts++
			if attempts == 1 {
				headers := http.Header{}
				headers.Set("Retry-After", "2021-05-10T11:00Z")
				return jsonResponse(req, http.StatusTooManyRequests, `{"extensions":{"requestId":"abc-123"}}`, headers)
			}
			return jsonResponse(req, http.StatusOK, `{"data":{"ok":true}}`, nil)
		}),
		Now: func() time.Time {
			return now
		},
		Sleep: func(d time.Duration) {
			slept = append(slept, d)
			now = now.Add(d)
		},
	}

	result, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result == nil || result.Data["ok"] != true {
		t.Fatalf("unexpected result %+v", result)
	}
	if len(slept) != 1 || slept[0] != 2*time.Second {
		t.Fatalf("expected single 2s sleep, got %v", slept)
	}
}

func TestInvalidRetryAfterReturnsError(t *testing.T) {
	client := graph.Client{
		BaseURL:       "http://example",
		Auth:          noAuth{},
		MaxRetries429: 0,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			headers := http.Header{}
			headers.Set("Retry-After", "not-a-time")
			return jsonResponse(req, http.StatusTooManyRequests, "", headers)
		}),
	}
	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err == nil {
		t.Fatal("expected error")
	}
	rlErr, ok := err.(*atlassian.RateLimitError)
	if !ok {
		t.Fatalf("expected RateLimitError, got %T", err)
	}
	if rlErr.HeaderValue != "not-a-time" {
		t.Fatalf("unexpected header value %q", rlErr.HeaderValue)
	}
	if rlErr.Attempts != 1 {
		t.Fatalf("expected attempts=1, got %d", rlErr.Attempts)
	}
}

func TestRetryAfterInPastRetriesImmediately(t *testing.T) {
	now := time.Date(2021, 5, 10, 11, 0, 1, 0, time.UTC)
	attempts := 0
	var slept []time.Duration

	client := graph.Client{
		BaseURL:       "http://example",
		Auth:          noAuth{},
		MaxRetries429: 1,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			attempts++
			if attempts == 1 {
				headers := http.Header{}
				headers.Set("Retry-After", "2021-05-10T11:00Z")
				return jsonResponse(req, http.StatusTooManyRequests, "", headers)
			}
			return jsonResponse(req, http.StatusOK, `{"data":{"ok":true}}`, nil)
		}),
		Now: func() time.Time { return now },
		Sleep: func(d time.Duration) {
			slept = append(slept, d)
			now = now.Add(d)
		},
	}

	result, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result == nil || result.Data["ok"] != true {
		t.Fatalf("unexpected result %+v", result)
	}
	if len(slept) != 0 {
		t.Fatalf("expected immediate retry without sleep, got %v", slept)
	}
}

func TestDoesNotRetryOn5xx(t *testing.T) {
	statuses := []int{http.StatusInternalServerError, http.StatusBadGateway, http.StatusServiceUnavailable}
	for _, status := range statuses {
		t.Run(http.StatusText(status), func(t *testing.T) {
			attempts := 0
			client := graph.Client{
				BaseURL:       "http://example",
				Auth:          noAuth{},
				MaxRetries429: 2,
				HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
					attempts++
					return jsonResponse(req, status, "", nil)
				}),
			}
			_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 1)
			if err == nil {
				t.Fatalf("expected error for status %d", status)
			}
			if attempts != 1 {
				t.Fatalf("expected one attempt, got %d", attempts)
			}
		})
	}
}

func TestLocalThrottlingFailsWhenWaitExceedsCap(t *testing.T) {
	now := time.Date(2021, 5, 10, 10, 0, 0, 0, time.UTC)
	var slept []time.Duration
	attempts := 0

	client := graph.Client{
		BaseURL:               "http://example",
		Auth:                  noAuth{},
		EnableLocalThrottling: true,
		MaxWait:               5 * time.Second,
		HTTPClient: newHTTPClient(func(req *http.Request) *http.Response {
			attempts++
			return jsonResponse(req, http.StatusOK, `{"data":{"ok":true}}`, nil)
		}),
		Now: func() time.Time { return now },
		Sleep: func(d time.Duration) {
			slept = append(slept, d)
			now = now.Add(d)
		},
	}

	_, err := client.Execute(context.Background(), "query { ok }", nil, "", nil, 20000)
	if err == nil {
		t.Fatal("expected local rate limit error")
	}
	if _, ok := err.(*atlassian.LocalRateLimitError); !ok {
		t.Fatalf("expected LocalRateLimitError, got %T", err)
	}
	if attempts != 0 {
		t.Fatalf("expected no HTTP attempts, got %d", attempts)
	}
	if len(slept) == 0 {
		t.Fatalf("expected to wait locally before failing")
	}
}
