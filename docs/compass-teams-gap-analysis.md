# Compass & Teams GraphQL Coverage Gap Analysis

> **Task:** `dev-health-ops-9lv` | **GitHub:** [full-chaos/atlassian#8](https://github.com/full-chaos/atlassian/issues/8)
> **Date:** 2026-01-30
> **Status:** ✅ **IMPLEMENTED** (PR #31)

## Executive Summary

The Atlassian GraphQL Gateway (AGG) schema contains **21,920 types**. Our implementation now covers **Jira** (issues, projects, sprints, worklogs), **OpsGenie Teams** integration, **Compass** (component catalog), and **Teams** (organizational structure).

| Product | Schema Types | Implementation Status | Priority |
|---------|--------------|----------------------|----------|
| **Compass** | 1,187 types | ✅ IMPLEMENTED | High |
| **Teams** | 555 types | ✅ IMPLEMENTED | Medium |

Both products provide critical data for developer health metrics: Compass for service catalog health and Teams for organizational structure and collaboration patterns.

### Implementation Summary

**Delivered in PR #31:**
- OpenAPI canonical schemas for Compass and Teams
- Python/Go canonical dataclasses/structs
- Python/Go GraphQL mappers with null handling
- Schema-driven generators for Compass, Teams, and Teamwork Graph
- Unit tests for all mappers

---

## 1. Current Implementation

### What's Covered

| Entity | GraphQL Query | Canonical Model | Generator |
|--------|---------------|-----------------|-----------|
| JiraIssue | `issueByKey(key, cloudId)` | `JiraIssue` | `generate_jira_issue_models.py` |
| JiraProject | `jira.allJiraProjects(cloudId, ...)` | `JiraProject` | `generate_jira_project_models.py` |
| JiraSprint | `sprintById(id)` | `JiraSprint` | `generate_jira_sprint_models.py` |
| JiraWorklog | `issueByKey(...).worklogs(...)` | `JiraWorklog` | `generate_jira_worklog_models.py` |
| OpsgenieTeam | via `opsgenieTeamsAvailableToLinkWith` | `OpsgenieTeamRef` | (in project generator) |

### Architecture Pattern

```
schema.introspection.json
         ↓
    Generator (python/tools/generate_*.py)
         ↓
    API Models (python/atlassian/graph/gen/*_api.py)
         ↓
    Mapper (python/atlassian/graph/mappers/*.py)
         ↓
    Canonical Model (openapi/jira-developer-health.canonical.openapi.yaml)
```

---

## 2. Compass Gap Analysis

### 2.1 Schema Coverage

**Root Entry Point:** `compass` → `CompassCatalogQueryApi`

**Available Types (1,187 total):**

| Category | Key Types | Purpose |
|----------|-----------|---------|
| Components | `CompassComponent`, `CompassComponentType` | Service catalog entries |
| Scorecards | `CompassScorecard`, `CompassScorecardCriteria` | Health/readiness scoring |
| Relationships | `CompassRelationship` | Service dependencies |
| Events | `CompassBuildEvent`, `CompassDeploymentEvent`, `CompassIncidentEvent` | CI/CD and incident tracking |
| Labels | `CompassComponentLabel`, `CompassTeamLabel` | Categorization |
| Metrics | `CompassMetricDefinition` | Custom health metrics |

### 2.2 Key Queries Needed

```graphql
# Get Cloud ID (required first)
query getCloudId($hostName: String!) {
  tenantContexts(hostNames: [$hostName]) {
    cloudId
  }
}

# Search components
query searchComponents($cloudId: ID!, $query: CompassSearchComponentInput!) {
  compass {
    searchComponents(cloudId: $cloudId, query: $query) {
      ... on CompassSearchComponentConnection {
        nodes {
          component { id name typeId description ownerTeam { id displayName } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}

# Get component with relationships
query getComponent($componentId: ID!) {
  compass {
    component(id: $componentId) {
      ... on CompassComponent {
        id name typeId description
        labels { name }
        relationships {
          edges {
            node { type startNode { id name } endNode { id name } }
          }
        }
      }
    }
  }
}

# Get scorecards
query getScorecards($cloudId: ID!) {
  compass {
    scorecards(cloudId: $cloudId) {
      ... on CompassScorecardConnection {
        nodes { id name description criteria { id name weight } }
      }
    }
  }
}
```

### 2.3 Component Types (Enum)

| Type | Description |
|------|-------------|
| `SERVICE` | Backend services |
| `LIBRARY` | Shared libraries |
| `APPLICATION` | Full applications |
| `CAPABILITY` | Business capabilities |
| `CLOUD_RESOURCE` | Cloud infrastructure |
| `DATA_PIPELINE` | Data processing pipelines |
| `MACHINE_LEARNING_MODEL` | ML models |
| `UI_ELEMENT` | Frontend components |
| `WEBSITE` | Web properties |
| `OTHER` | Catch-all type |

### 2.4 Developer Health Use Cases

| Use Case | Compass Data | Metric |
|----------|--------------|--------|
| Service catalog completeness | Components without owners/descriptions | Catalog health score |
| Dependency risk | Relationships with `DEPENDS_ON` type | Bus factor for services |
| Production readiness | Scorecard scores | Readiness percentage |
| Incident correlation | `CompassIncidentEvent` | MTTR by service |
| Deployment frequency | `CompassDeploymentEvent` | DORA deployment frequency |

### 2.5 Proposed Canonical Models

```yaml
# openapi/compass-developer-health.canonical.openapi.yaml
CompassComponent:
  type: object
  required: [id, name, type, cloudId]
  properties:
    id: { type: string }
    cloudId: { type: string }
    name: { type: string }
    type: { type: string, enum: [SERVICE, LIBRARY, APPLICATION, ...] }
    description: { type: string, nullable: true }
    ownerTeamId: { type: string, nullable: true }
    ownerTeamName: { type: string, nullable: true }
    labels: { type: array, items: { type: string } }
    createdAt: { type: string, format: date-time }
    updatedAt: { type: string, format: date-time }

CompassRelationship:
  type: object
  required: [id, type, startComponentId, endComponentId]
  properties:
    id: { type: string }
    type: { type: string }  # DEPENDS_ON, OWNED_BY, etc.
    startComponentId: { type: string }
    endComponentId: { type: string }

CompassScorecardScore:
  type: object
  required: [componentId, scorecardId, score]
  properties:
    componentId: { type: string }
    scorecardId: { type: string }
    scorecardName: { type: string }
    score: { type: number, minimum: 0, maximum: 100 }
    maxScore: { type: number }
    evaluatedAt: { type: string, format: date-time }
```

---

## 3. Teams Gap Analysis

### 3.1 Schema Coverage

**Root Entry Points:**
- `team` → `TeamQuery` (single team lookup)
- `teamSearchV2` → Search teams (requires `@optIn`)
- `teamworkGraph_*` → 17 queries for team relationships

**Available Types (555 total):**

| Category | Key Types | Purpose |
|----------|-----------|---------|
| Core | `Team`, `TeamMember`, `TeamState` | Team structure |
| Search | `TeamSearchV2`, `TeamSort` | Team discovery |
| Teamwork Graph | `teamworkGraph_*` queries | Cross-product relationships |

### 3.2 Critical Limitation: Read-Only GraphQL

**GraphQL API is READ-ONLY for Teams.** Mutations require REST API.

| Operation | GraphQL | REST |
|-----------|---------|------|
| Get team | ✅ | ✅ |
| Search teams | ✅ (beta) | ✅ |
| Get members | ✅ (beta) | ✅ |
| Create team | ❌ | ✅ |
| Update team | ❌ | ✅ |
| Manage members | ❌ | ✅ |

### 3.3 Key Queries Needed

```graphql
# Get team by ID
query getTeam($teamId: ID!) {
  team(id: $teamId) {
    id
    displayName
    smallAvatarImageUrl
    state
  }
}

# Search teams (requires beta opt-in)
query teamSearchV2(
  $organizationId: ID!
  $siteId: String!
  $query: String!
  $first: Int
) {
  team {
    teamSearchV2(
      organizationId: $organizationId
      siteId: $siteId
      filter: { query: $query }
      first: $first
    ) @optIn(to: "Team-search-v2") {
      nodes {
        team { id displayName smallAvatarImageUrl state }
      }
    }
  }
}
```

### 3.4 Team ID Format (ARI)

Teams use Atlassian Resource Identifiers:
```
ari:cloud:identity::team/{uuid}
```
Example: `ari:cloud:identity::team/36885b3c-1bf0-4f85-a357-c5b858c31de4`

### 3.5 Beta Headers Required

```http
X-ExperimentalApi: teams-beta
X-ExperimentalApi: team-members-beta
```

### 3.6 Developer Health Use Cases

| Use Case | Teams Data | Metric |
|----------|------------|--------|
| Team structure | Team membership | Team size, composition |
| Collaboration patterns | `teamworkGraph_userTeams` | Cross-team collaboration |
| Workload distribution | `teamworkGraph_teamActiveProjects` | Team capacity |
| Org hierarchy | `teamworkGraph_userManager` | Reporting structure |

### 3.7 Proposed Canonical Models

```yaml
# openapi/teams-developer-health.canonical.openapi.yaml
AtlassianTeam:
  type: object
  required: [id, displayName, state]
  properties:
    id: { type: string, description: "ARI format" }
    displayName: { type: string }
    description: { type: string, nullable: true }
    state: { type: string, enum: [ACTIVE, ARCHIVED] }
    avatarUrl: { type: string, nullable: true }
    memberCount: { type: integer, nullable: true }

AtlassianTeamMember:
  type: object
  required: [teamId, accountId]
  properties:
    teamId: { type: string }
    accountId: { type: string }
    displayName: { type: string }
    role: { type: string, enum: [REGULAR, ADMIN] }
```

---

## 4. Implementation Plan

### Phase 1: Compass Components (P1 - High Priority) ✅ COMPLETE

**Scope:** Component catalog sync for service ownership and dependency tracking.

| Task | Deliverable | Status |
|------|-------------|--------|
| 1.1 Add Compass to schema introspection | Verify Compass types in `schema.introspection.json` | ✅ |
| 1.2 Create `generate_compass_component_models.py` | Python generator for components | ✅ |
| 1.3 Create `generate_compass_component_models/main.go` | Go generator for components | ✅ |
| 1.4 Define canonical models | `openapi/compass-developer-health.canonical.openapi.yaml` | ✅ |
| 1.5 Implement mappers | `python/atlassian/graph/mappers/compass_components.py` | ✅ |
| 1.6 Add unit tests | Coverage for pagination, errors, mapping | ✅ |
| 1.7 Add integration tests | Env-gated tests against live Compass | ⏳ Future |

### Phase 2: Compass Scorecards & Relationships (P2) ✅ COMPLETE

**Scope:** Scorecard health tracking and service dependency graph.

| Task | Deliverable | Status |
|------|-------------|--------|
| 2.1 Generate scorecard models | Python/Go generators | ✅ |
| 2.2 Generate relationship models | Python/Go generators | ✅ |
| 2.3 Extend canonical models | Add scorecard/relationship schemas | ✅ |
| 2.4 Implement mappers | Scorecard score and relationship mappers | ✅ |
| 2.5 Add tests | Unit + integration | ✅ Unit |

### Phase 3: Teams Integration (P3 - Medium Priority) ✅ COMPLETE

**Scope:** Team structure for collaboration metrics.

| Task | Deliverable | Status |
|------|-------------|--------|
| 3.1 Add beta header support | `X-ExperimentalApi` handling in client | ✅ (existing) |
| 3.2 Generate team models | Python/Go generators | ✅ |
| 3.3 Define canonical models | `openapi/teams-developer-health.canonical.openapi.yaml` | ✅ |
| 3.4 Implement mappers | Team and membership mappers | ✅ |
| 3.5 Add tests | Unit + integration (beta API) | ✅ Unit |

### Phase 4: Teamwork Graph (P4 - Future) ✅ MODELS GENERATED

**Scope:** Cross-product relationship queries for advanced collaboration analytics.

| Task | Deliverable | Status |
|------|-------------|--------|
| 4.1 Evaluate `teamworkGraph_*` queries | Determine useful queries | ⏳ Future |
| 4.2 Generate models | Python/Go generators | ✅ |
| 4.3 Define canonical models | Work activity schemas | ⏳ Future |
| 4.4 Implement mappers | Activity mappers | ⏳ Future |

---

## 5. Technical Considerations

### 5.1 Rate Limiting

All products share the AGG rate limit:
- **Budget:** 10,000 points/minute
- **Enforcement:** HTTP 429
- **Retry-After:** Timestamp format (already handled in `client.py`)

Compass queries are typically higher cost due to component/relationship complexity.

### 5.2 Pagination

All connections must handle pagination:
- `pageInfo.hasNextPage`
- `pageInfo.endCursor`
- Nested pagination (e.g., component → relationships → nodes)

### 5.3 Error Handling

Compass/Teams use union types for errors:
```graphql
component(id: $id) {
  ... on CompassComponent { id name }
  ... on QueryError { message extensions { statusCode } }
}
```

Mappers must handle `QueryError` responses explicitly.

### 5.4 Schema Evolution

- **Compass:** Stable API, well-documented
- **Teams:** Beta API, requires opt-in headers, may change

Generate models frequently to catch schema changes.

---

## 6. Dependencies

### Required Before Starting

1. **Verify Compass/Teams in introspection** - Run `fetch_graphql_schema.py` with valid credentials
2. **Confirm OAuth scopes** - Check required scopes in GraphQL Explorer
3. **Test environment** - Need Compass instance with sample components

### Codebase Dependencies

- `python/atlassian/graph/client.py` - May need beta header support
- `python/atlassian/graph/schema_fetcher.py` - Already supports full introspection
- `openapi/` - New canonical schema files

---

## 7. Success Criteria

### Phase 1 Complete When: ✅ DONE

- [x] `compass_components_api.py` generated from schema
- [x] `CompassComponent` canonical model defined
- [x] Component sync working end-to-end
- [x] Unit tests passing with mocked HTTP
- [ ] Integration tests passing (env-gated) — future work

### Phase 3 Complete When: ✅ DONE

- [x] Teams queries working with beta headers
- [x] `AtlassianTeam` canonical model defined
- [x] Team membership sync working
- [x] Tests passing

---

## 8. Open Questions

1. **Compass Events:** Should we sync build/deployment/incident events? (Overlaps with GitHub/GitLab connectors)
2. **Teams REST API:** Do we need REST fallback for mutations?
3. **Teamwork Graph:** Is the EAP API stable enough for production use?
4. **Multi-tenancy:** How to handle multiple Atlassian sites?

---

## Appendix A: Schema Type Counts

```
Total AGG types: 21,920

Compass-related: 1,187
  - CompassComponent*: 45
  - CompassScorecard*: 38
  - CompassRelationship*: 12
  - CompassEvent*: 25
  - Other: 1,067

Teams-related: 555
  - Team*: 89
  - TeamworkGraph*: 34
  - Other: 432

Jira-related: 3,990 (currently covered: ~50)
```

## Appendix B: References

- [Atlassian GraphQL API](https://developer.atlassian.com/platform/atlassian-graphql-api/graphql/)
- [Compass GraphQL API](https://developer.atlassian.com/cloud/compass/graphql/)
- [Teams GraphQL API](https://developer.atlassian.com/platform/teams/teams-graphql-api/introduction/)
- [Compass Examples (GitHub)](https://github.com/atlassian-labs/compass-examples)
- [GitLab for Compass (GitHub)](https://github.com/atlassian-labs/gitlab-for-compass)
