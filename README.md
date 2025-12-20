Atlassian GraphQL and Rest clients for Python and Go with shared transport OpenAPI spec.

# Experimental Warning

This library is experimental to generate package clients from graphql introspection and swagger rest docs

## Schema introspection + codegen

This repo avoids stale, hand-written assumptions about Atlassian GraphQL Gateway (AGG) by generating a small, query-focused set of API models from **live schema introspection**.

- Fetch schema (writes `graphql/schema.introspection.json` and optionally `graphql/schema.sdl.graphql`):
  - `make graphql-schema`
- Generate Jira project API models from the introspection JSON:
  - `make graphql-gen`

Notes:

- SDL output is best-effort. If the Python optional dependency for GraphQL SDL printing is not installed, only the JSON file is written.
- Generation is intentionally minimal: it only emits the types needed for the Jira project listing query and its connection/edge shapes.

## Jira REST OpenAPI

Jira Cloud publishes a Swagger/OpenAPI spec for REST v3. You can fetch it into this repo:

- `make jira-rest-openapi` (writes `openapi/jira-rest.swagger-v3.json`)
- Generate minimal, analytics-focused REST models from the swagger JSON:
  - `make jira-rest-gen` (writes `python/atlassian/rest/gen/jira_api.py` and `go/atlassian/rest/gen/jira_api.go`)

## Endpoints

- Global: `https://api.atlassian.com/graphql` (OAuth2 bearer token)
- Tenanted gateway: `https://{subdomain}.atlassian.net/gateway/api/graphql` (API token via Basic auth or browser session cookies)
- Custom/non-tenanted: configurable `BaseURL` (may be either the base host like `https://api.atlassian.com` or the full GraphQL URL ending in `/graphql`)
- Jira REST (OAuth2 3LO): `https://api.atlassian.com/ex/jira/{cloudId}/rest/api/3/...`
- Jira REST (tenanted): `https://{subdomain}.atlassian.net/rest/api/3/...`

See the transport spec in `openapi/atlassian.transport.openapi.yaml`.
Canonical analytics schemas live in `openapi/jira-developer-health.canonical.openapi.yaml`.

## Getting an OAuth access token (3LO)

`ATLASSIAN_OAUTH_ACCESS_TOKEN` is an **OAuth 2.0 access token**, not your app’s client secret.

1. Create a 3LO app in the Atlassian Developer Console and configure a redirect URI (e.g. `http://localhost:8080/callback`).
2. Run the helper and follow the prompts:
   - Python: `make oauth-login`
   - Go: `make oauth-login-go`
   - To print cloud IDs (accessible resources): `make oauth-login OAUTH_LOGIN_ARGS="--print-accessible-resources"` (or run `python python/tools/oauth_login.py --print-accessible-resources` directly)
3. Include `offline_access` in your scopes to receive a refresh token, then set:
   - `ATLASSIAN_OAUTH_ACCESS_TOKEN` (short-lived)
   - `ATLASSIAN_OAUTH_REFRESH_TOKEN` + `ATLASSIAN_CLIENT_ID` + `ATLASSIAN_CLIENT_SECRET` (recommended; auto-refresh)

Note: AGG may return a GraphQL error with `required_scopes` values (e.g. `jira:atlassian-external`). When `classification=InsufficientOAuthScopes`, this is an OAuth scope requirement surfaced by AGG; if that scope isn’t obtainable via Atlassian 3LO, you’ll need to run those operations via tenanted gateway auth (Basic API token / cookies).
For Jira project listing, the OAuth scope requirement surfaced by AGG appears to be non-standard for external apps; use Jira REST `GET /rest/api/3/project/search` instead when running under normal 3LO scopes (`read:jira-work`, `read:jira-user`).

## Python usage

```python
from atlassian import (
    GraphQLClient,
    OAuthBearerAuth,
    OAuthRefreshTokenAuth,
    BasicApiTokenAuth,
    JiraRestClient,
    iter_projects_with_opsgenie_linkable_teams,
    list_projects_with_opsgenie_linkable_teams,
    iter_projects_via_rest,
    list_projects_via_rest,
)

# OAuth bearer (api.atlassian.com)
client = GraphQLClient("https://api.atlassian.com", OAuthBearerAuth(lambda: "ACCESS_TOKEN"))
resp = client.execute("query { __typename }")

# OAuth refresh token (auto-refreshes access tokens)
client = GraphQLClient(
    "https://api.atlassian.com",
    OAuthRefreshTokenAuth("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"),
)

# Tenanted Basic API token
client = GraphQLClient(
    "https://yourteam.atlassian.net/gateway/api",
    BasicApiTokenAuth("you@example.com", "API_TOKEN"),
    strict=True,
)

# Experimental APIs
client.execute("query { __typename }", experimental_apis=["jiraexpression", "anotherBeta"])

# Jira projects + linkable Opsgenie teams (canonical output)
projects = list(
    iter_projects_with_opsgenie_linkable_teams(
        client,
        cloud_id="YOUR_CLOUD_ID",
        project_types=["SOFTWARE"],
        page_size=50,
        experimental_apis=["someExperimentalApi"],
    )
)

# Convenience wrapper (builds GraphQLClient from env vars)
projects = list(list_projects_with_opsgenie_linkable_teams("YOUR_CLOUD_ID", ["SOFTWARE"]))

# Jira projects via Jira REST (OAuth-friendly; returns empty opsgenieTeams)
rest = JiraRestClient(f"https://api.atlassian.com/ex/jira/{'YOUR_CLOUD_ID'}", OAuthBearerAuth(lambda: "ACCESS_TOKEN"))
projects = list(iter_projects_via_rest(rest, cloud_id="YOUR_CLOUD_ID", project_types=["SOFTWARE"]))

# Convenience wrapper (builds JiraRestClient from env vars)
projects = list(list_projects_via_rest("YOUR_CLOUD_ID", ["SOFTWARE"]))
```

## Go usage

```go
import (
    "context"
    "atlassian/atlassian"
    "atlassian/atlassian/graph"
    "atlassian/atlassian/rest"
)

client := graph.Client{
    BaseURL: "https://api.atlassian.com",
    Auth: atlassian.BearerAuth{
        TokenGetter: func() (string, error) { return "ACCESS_TOKEN", nil },
    },
    Strict: true,
}

// OAuth refresh token (auto-refreshes access tokens)
client = graph.Client{
    BaseURL: "https://api.atlassian.com",
    Auth: &atlassian.OAuthRefreshTokenAuth{
        ClientID: "CLIENT_ID",
        ClientSecret: "CLIENT_SECRET",
        RefreshToken: "REFRESH_TOKEN",
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

projects, err := client.ListProjectsWithOpsgenieLinkableTeams(
    context.Background(),
    "YOUR_CLOUD_ID",
    []string{"SOFTWARE"},
    50,
)

// Jira projects via Jira REST (OAuth-friendly; returns empty opsgenieTeams)
rest := rest.JiraRESTClient{
    BaseURL: "https://api.atlassian.com/ex/jira/" + "YOUR_CLOUD_ID",
    Auth: atlassian.BearerAuth{
        TokenGetter: func() (string, error) { return "ACCESS_TOKEN", nil },
    },
}
projects, err = rest.ListProjectsViaREST(context.Background(), "YOUR_CLOUD_ID", []string{"SOFTWARE"}, 50)
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

## Canonical vs API models

- API models (`python/atlassian/graph/gen/`, `python/atlassian/rest/gen/`, `go/atlassian/graph/gen/`, `go/atlassian/rest/gen/`) are generated from live schemas and match the API response shape for specific operations/endpoints.
- Canonical models (`python/atlassian/canonical_models.py`, `go/atlassian/canonical_models.go`) are stable, versioned analytics schemas (source-of-truth: `openapi/jira-developer-health.canonical.openapi.yaml`).
- Mappers live in `python/atlassian/graph/mappers/`, `python/atlassian/rest/mappers/`, `go/atlassian/graph/mappers/`, and `go/atlassian/rest/mappers/`.

## Tests

- Python: `cd python && pip install -e . && pytest`
- Go: `cd go && go test ./...`
- Integration (env-gated):
  - `ATLASSIAN_CLOUD_ID` (or `ATLASSIAN_JIRA_CLOUD_ID`) for Jira project listing integration tests
  - One of `ATLASSIAN_OAUTH_ACCESS_TOKEN` _or_ (`ATLASSIAN_EMAIL` + `ATLASSIAN_API_TOKEN`) _or_ `ATLASSIAN_COOKIES_JSON`
  - Optional OAuth auto-refresh: `ATLASSIAN_OAUTH_REFRESH_TOKEN` + `ATLASSIAN_CLIENT_ID` + `ATLASSIAN_CLIENT_SECRET`
  - `ATLASSIAN_GQL_BASE_URL` is required for non-OAuth auth modes; OAuth defaults to `https://api.atlassian.com`
  - Jira REST base URL: set `ATLASSIAN_JIRA_BASE_URL` for tenanted auth; OAuth defaults to `https://api.atlassian.com/ex/jira/{cloudId}`
  - Jira REST issue search integration: `ATLASSIAN_JIRA_JQL`
  - Jira REST history integration: `ATLASSIAN_JIRA_ISSUE_KEY` (for changelog/worklog smoke tests)
  - Optional: `ATLASSIAN_GQL_EXPERIMENTAL_APIS` (comma-separated; sent as repeated `X-ExperimentalApi` headers)
  - Integration tests will load a repo-root `.env` if present (without overriding existing environment variables)
  - Python: `cd python && pytest tests/integration`
  - Go: `cd go && go test -tags=integration ./...`
