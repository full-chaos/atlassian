# Terraform Provider for Jira

This Terraform provider allows you to read Jira project and issue data using the Jira REST API.

## Requirements

- [Terraform](https://www.terraform.io/downloads.html) >= 1.0
- [Go](https://golang.org/doc/install) >= 1.21 (for building from source)

## Building the Provider

1. Clone the repository
2. Build the provider:
   ```shell
   cd terraform
   go build -o terraform-provider-jira
   ```

## Using the Provider

### Provider Configuration

Configure the provider with your Atlassian credentials:

```hcl
terraform {
  required_providers {
    jira = {
      source = "full-chaos/jira"
    }
  }
}

provider "jira" {
  cloud_id     = "your-cloud-id"
  access_token = "your-oauth-access-token"  # OAuth 2.0 token
}
```

Or use Basic authentication:

```hcl
provider "jira" {
  base_url  = "https://yourteam.atlassian.net"
  cloud_id  = "your-cloud-id"
  email     = "you@example.com"
  api_token = "your-api-token"
}
```

### Environment Variables

The provider can also read configuration from environment variables:

| Variable | Description |
|----------|-------------|
| `ATLASSIAN_JIRA_BASE_URL` | Jira API base URL |
| `ATLASSIAN_CLOUD_ID` or `ATLASSIAN_JIRA_CLOUD_ID` | Atlassian Cloud ID |
| `ATLASSIAN_EMAIL` | Email for Basic auth |
| `ATLASSIAN_API_TOKEN` | API token for Basic auth |
| `ATLASSIAN_OAUTH_ACCESS_TOKEN` | OAuth 2.0 access token |

## Data Sources

### jira_projects

Fetches a list of Jira projects.

```hcl
data "jira_projects" "software" {
  project_types = ["SOFTWARE"]
}

output "projects" {
  value = data.jira_projects.software.projects
}
```

#### Arguments

- `cloud_id` (Optional) - Override the provider's cloud ID
- `project_types` (Optional) - List of project types to filter. Valid values: `SOFTWARE`, `BUSINESS`, `SERVICE_DESK`. Defaults to `["SOFTWARE"]`

#### Attributes

- `projects` - List of projects with the following attributes:
  - `cloud_id` - The Atlassian Cloud ID
  - `key` - The project key (e.g., "PROJ")
  - `name` - The project name
  - `type` - The project type

### jira_issues

Fetches Jira issues using JQL (Jira Query Language).

```hcl
data "jira_issues" "open_bugs" {
  jql = "project = PROJ AND type = Bug AND status != Done"
}

output "bugs" {
  value = data.jira_issues.open_bugs.issues
}
```

#### Arguments

- `cloud_id` (Optional) - Override the provider's cloud ID
- `jql` (Required) - JQL query to filter issues

#### Attributes

- `issues` - List of issues with the following attributes:
  - `cloud_id` - The Atlassian Cloud ID
  - `key` - The issue key (e.g., "PROJ-123")
  - `project_key` - The project key
  - `issue_type` - The issue type (e.g., "Bug", "Story")
  - `status` - The issue status
  - `created_at` - When the issue was created (RFC3339 format)
  - `updated_at` - When the issue was last updated (RFC3339 format)
  - `resolved_at` - When the issue was resolved (RFC3339 format), if applicable
  - `labels` - Labels assigned to the issue
  - `components` - Components assigned to the issue
  - `story_points` - Story points assigned to the issue, if applicable

## Example Usage

```hcl
terraform {
  required_providers {
    jira = {
      source = "full-chaos/jira"
    }
  }
}

provider "jira" {
  cloud_id = var.atlassian_cloud_id
}

variable "atlassian_cloud_id" {
  description = "Atlassian Cloud ID"
  type        = string
}

# Get all software projects
data "jira_projects" "all" {
  project_types = ["SOFTWARE", "BUSINESS"]
}

# Get issues from a specific project
data "jira_issues" "recent" {
  jql = "project = ${data.jira_projects.all.projects[0].key} AND updated >= -7d ORDER BY updated DESC"
}

output "project_count" {
  value = length(data.jira_projects.all.projects)
}

output "recent_issue_count" {
  value = length(data.jira_issues.recent.issues)
}
```

## Authentication Methods

### OAuth 2.0 (Recommended)

1. Create a 3LO (three-legged OAuth) app in the [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/)
2. Configure the required OAuth scopes:
   - `read:jira-work`
   - `read:jira-user`
3. Obtain an access token using the OAuth flow
4. Set the `access_token` in the provider configuration or the `ATLASSIAN_OAUTH_ACCESS_TOKEN` environment variable

### Basic API Token

1. Generate an API token from [Atlassian Account Settings](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Set `email` and `api_token` in the provider configuration, or use the corresponding environment variables
3. Set `base_url` to your Jira instance URL (e.g., `https://yourteam.atlassian.net`)

## Development

### Running Tests

```shell
cd terraform
go test ./...
```

### Building

```shell
cd terraform
go build -o terraform-provider-jira
```
