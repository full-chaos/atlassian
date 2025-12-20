Below is a **plaintext `AGENTS.md`** suitable for committing at the repo root. It is written as an operating contract for humans and AI agents (Codex, Copilot, Claude, etc.) working on this codebase.

---

# AGENTS.md

## Purpose

This repository implements a **production-grade Atlassian GraphQL Gateway (AGG) client and analytics pipeline** (Python + Go) used to collect Jira (and related Atlassian product) data and compute **developer health metrics**.

This file defines **non-negotiable rules, architecture boundaries, and operating principles** for any human or AI agent modifying this repository.

If you violate these rules, your changes are incorrect even if the code “works”.

---

## Core Principles (Read First)

1. **Schema-driven, not guess-driven**

   * Atlassian GraphQL schemas evolve.
   * API models MUST be generated from **live schema introspection**, not handwritten guesses.
   * Canonical analytics models MUST be stable and owned by this repo.

2. **Separation of concerns is mandatory**

   * API models ≠ analytics models.
   * Transport ≠ business logic.
   * Fetching ≠ mapping ≠ metric computation.

3. **Defensive by default**

   * Expect partial data, missing fields, pagination edge cases, and rate limiting.
   * Fail loudly and explicitly when required data is missing.
   * Never silently drop errors.

4. **Production realism**

   * Rate limits are real.
   * Schemas change.
   * Tenants differ.
   * Permissions vary.
   * Code must degrade gracefully.

---

## Repository Architecture (Authoritative)

### 1. API Layer (Fast-moving, Generated)

**Purpose:**
Represent the Atlassian GraphQL Gateway schema as it exists *today*.

**Characteristics:**

* Generated from GraphQL introspection
* Allowed to change frequently
* Mirrors AGG types (connections, edges, nodes, pageInfo)
* NOT used directly for analytics

**Locations:**

* `python/atlassian/graph/gen/`
* `python/atlassian/rest/gen/`
* `go/atlassian/graph/gen/`
* `go/atlassian/rest/gen/`
* Source schema: `graphql/schema.introspection.json`

**Rules:**

* Never hand-edit generated files
* Regeneration must be deterministic
* Missing schema fields MUST cause generator failure

---

### 2. Transport & Client Layer (Stable, Defensive)

**Purpose:**
Safely execute GraphQL operations against AGG.

**Responsibilities:**

* Authentication
* Rate limiting
* Retries (429 only)
* Logging
* Strict vs non-strict GraphQL error handling
* Beta headers (`X-ExperimentalApi`)

**Locations:**

* `python/atlassian/graph/client.py`
* `python/atlassian/rest/client.py`
* `go/atlassian/graph/client.go`
* `go/atlassian/rest/client.go`

**Hard Rules:**

* Retry ONLY on HTTP 429
* Parse `Retry-After` as a TIMESTAMP
* NEVER retry HTTP >= 500
* Do NOT log secrets
* Timeouts are mandatory

---

### 3. Canonical Analytics Layer (Slow-moving, Stable)

**Purpose:**
Define the data model used for **developer health metrics**.

**Characteristics:**

* API-agnostic
* Versioned by this repo
* Backward-compatible whenever possible
* Designed for analytics, not transport convenience

**Source of Truth:**

* `openapi/jira-developer-health.canonical.openapi.yaml`

**Examples:**

* JiraUser
* JiraProject
* JiraIssue
* JiraChangelogEvent
* JiraWorklog
* CanonicalProjectWithOpsgenieTeams

**Rules:**

* Canonical schemas must NOT leak API-specific shapes (edges, nodes, cursors)
* IDs are strings
* Timestamps are RFC3339
* Optional fields are preferred over brittle requirements

---

### 4. Mapping Layer (Explicit, Validated)

**Purpose:**
Convert API models → canonical analytics models.

**Locations:**

* `python/atlassian/graph/mappers/`
* `python/atlassian/rest/mappers/`
* `go/atlassian/graph/mappers/`
* `go/atlassian/rest/mappers/`

**Rules:**

* Required canonical fields MUST be validated
* Missing required data → explicit error
* No implicit defaults for semantic fields
* Positive conditionals preferred
* No business logic here — mapping only

---

## Pagination Rules (Non-Negotiable)

* Assume **every connection paginates**
* Support:

  * `pageInfo.hasNextPage`
  * `pageInfo.endCursor` if present
* Nested pagination MUST be handled (e.g. projects → opsgenie teams)
* Never assume a single page
* Never hardcode page sizes

---

## Rate Limiting Rules (AGG-Specific)

* Atlassian AGG uses **cost-based rate limiting**
* Default budget: 10,000 points per minute
* Enforcement mechanism:

  * HTTP 429
  * `Retry-After` header contains a **timestamp**, not seconds

**Behavior:**

* Retry ONLY on 429
* Compute wait = retry_after_timestamp - now
* Cap wait using MaxWait
* After MaxRetries429 → fail with RateLimitError
* Do NOT retry 4xx (except 429)
* Do NOT retry >= 500

Violating this will get your code reverted.

---

## Authentication Rules

Supported auth modes:

1. OAuth Bearer token (`Authorization: Bearer`)
2. Basic auth (email + API token) for tenant gateway
3. Cookie-based auth (explicit, opt-in)

Rules:

* Auth MUST be injectable
* Never hardcode tokens
* Never log auth headers or cookies
* Tests MUST mock auth

---

## Testing Contract

### Unit Tests

* MUST mock HTTP
* MUST cover:

  * Pagination
  * Rate limiting (429)
  * Beta headers
  * Mapping validation
  * Error paths

### Integration Tests

* MUST be env-gated
* MUST skip cleanly if env vars missing
* MUST NOT attempt to intentionally trigger rate limits
* MUST assert shape, not volume

### Required Env Vars (integration)

* `ATLASSIAN_GQL_BASE_URL`
* One of:

  * `ATLASSIAN_OAUTH_ACCESS_TOKEN`
  * `ATLASSIAN_EMAIL` + `ATLASSIAN_API_TOKEN`
  * `ATLASSIAN_COOKIES_JSON`

---

## AI Agent Rules (Critical)

If you are an AI agent (Codex, Copilot, Claude, etc.):

* DO NOT invent GraphQL fields
* DO NOT assume schema stability
* DO NOT collapse API models into analytics models
* DO NOT remove rate-limiting safeguards
* DO NOT weaken error handling to “make tests pass”
* DO NOT introduce silent fallbacks

If schema details are unclear:

1. Fetch introspection
2. Inspect schema
3. Generate models
4. Map explicitly

Guessing is a failure.

---

## What This Repo Is NOT

* Not a thin demo client
* Not a static schema wrapper
* Not a Jira-only system
* Not tolerant of silent data corruption

---

## Final Authority

If there is a conflict between:

* Code comments
* README
* AGENTS.md

**AGENTS.md wins.**

If you are unsure how to proceed:

* Preserve correctness
* Preserve explicitness
* Preserve future schema evolution

That is the bar.
