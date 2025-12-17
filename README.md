Atlassian GraphQL clients for Python and Go with shared transport OpenAPI spec.

## Endpoints
- Global: `https://api.atlassian.com/graphql` (OAuth2 bearer token)
- Tenanted gateway: `https://{subdomain}.atlassian.net/gateway/api/graphql` (API token via Basic auth or browser session cookies)
- Custom/non-tenanted: configurable `BaseURL`, append `/graphql`

See the transport spec in `openapi/atlassian-graphql.transport.openapi.yaml`.

## Python usage
```python
from atlassian_graphql import GraphQLClient, OAuthBearerAuth, BasicApiTokenAuth

# OAuth bearer (api.atlassian.com)
client = GraphQLClient("https://api.atlassian.com", OAuthBearerAuth(lambda: "ACCESS_TOKEN"))
resp = client.execute("query { __typename }")

# Tenanted Basic API token
client = GraphQLClient(
    "https://yourteam.atlassian.net/gateway/api",
    BasicApiTokenAuth("you@example.com", "API_TOKEN"),
    strict=True,
)

# Experimental APIs
client.execute("query { __typename }", experimental_apis=["jiraexpression", "anotherBeta"])
```

## Go usage
```go
import (
    "context"
    "atlassian-graphql/graphql"
)

client := graphql.Client{
    BaseURL: "https://api.atlassian.com",
    Auth: graphql.BearerAuth{
        TokenGetter: func() (string, error) { return "ACCESS_TOKEN", nil },
    },
    Strict: true,
}
result, err := client.Execute(
    context.Background(),
    "query { __typename }",
    nil,
    "",
    []string{"jiraexpression"},
    1, // estimated cost (optional)
)
if err != nil {
    // handle error
}
```

- Strict mode raises/returns GraphQL operation errors when `errors[]` is present.
- Non-strict mode preserves partial `data` alongside `errors`.
- Rate limiting: Atlassian GraphQL Gateway enforces cost-based, per-user budgets (default 10,000 points per currency per minute). When exceeded it returns HTTP 429 with a `Retry-After` timestamp header (e.g., `2021-05-10T11:00Z`); the 429 applies to the HTTP request, not as a GraphQL error. Clients retry only on 429, honoring the timestamp and `max_wait_seconds`, and surface `RateLimitError` details (including unparseable headers). No retries occur on HTTP 5xx.
- Optional local throttling (best-effort, off by default): clients can enable a token bucket approximating 10,000 points/minute using a per-call `estimated_cost` (default 1). If insufficient local budget, the client blocks until budget refills or `max_wait_seconds` is exceeded, then raises a local throttling error. This does not replace server enforcement.

## Rate limiting requirements
- AGG uses cost-based, per-user limits (default budget 10,000 points per currency per minute). Overages return HTTP 429 with `Retry-After: {timestamp}` (e.g., `2021-05-10T11:00Z`); 429 is an HTTP-level response, not a GraphQL error. Do not retry on HTTP ≥ 500.
- Retry only on 429. Parse `Retry-After` as a timestamp (support ISO-8601/RFC3339 and HTTP-date variants); if parsing fails, return a `RateLimitError` that includes the raw header. Compute `wait = retry_at - now`; if `wait <= 0`, retry immediately (counts toward attempts). If `wait` exceeds `max_wait_seconds`, surface a `RateLimitError` with the computed wait and cap. Retry up to `max_retries_429`, otherwise return a `RateLimitError` with the attempts count and last header/reset time.
- Optional local, best-effort token bucket (off by default): bucket size 10,000 points and refill rate `10000/60` per second. Each `execute` takes an `estimated_cost` (default 1); if tokens are insufficient, block until budget refills or `max_wait_seconds` expires, then raise a local throttling error. This only complements server enforcement.
- Logging: on 429 emit a warning with attempt number, parsed reset time, computed wait, endpoint, `operationName` (if provided), and `request_id` from response extensions when available. Emit debug logs describing whether `Retry-After` parsing succeeded and which parser/format was used. Never log Authorization headers, tokens, or cookies.
- Tests: unit coverage includes 429 retry with timestamp header, unparseable `Retry-After`, past reset time (immediate retry), and no retries on 500/502/503. Integration tests must skip gracefully and, if a natural 429 occurs, confirm a single retry path and logging without intentionally exhausting rate limits.

## Tests
- Python: `cd python && pip install -e .[dev] && pytest`
- Go: `cd go && go test ./...`
- Integration (env-gated):
  - `ATLASSIAN_GQL_BASE_URL`
  - One of `ATLASSIAN_OAUTH_ACCESS_TOKEN` _or_ (`ATLASSIAN_EMAIL` + `ATLASSIAN_API_TOKEN`) _or_ `ATLASSIAN_COOKIES_JSON`
  - Python: `cd python && pytest tests/integration`
  - Go: `cd go && go test -tags=integration ./...`
