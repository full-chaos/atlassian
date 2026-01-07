terraform {
  required_providers {
    jira = {
      source = "full-chaos/jira"
    }
  }
}

# Configure the provider using environment variables or explicit values
# Environment variables:
#   - ATLASSIAN_CLOUD_ID or ATLASSIAN_JIRA_CLOUD_ID
#   - ATLASSIAN_OAUTH_ACCESS_TOKEN (for OAuth)
#   - or ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN (for Basic auth)
provider "jira" {
  # cloud_id     = "your-cloud-id"      # Required: Cloud ID
  # access_token = "your-access-token"  # OAuth token (set via env var)
}

# Fetch all software projects
data "jira_projects" "software" {
  project_types = ["SOFTWARE"]
}

# Fetch recent issues from the first project
data "jira_issues" "recent" {
  jql = "project = ${length(data.jira_projects.software.projects) > 0 ? data.jira_projects.software.projects[0].key : "NOPROJECT"} AND updated >= -7d ORDER BY updated DESC"
}

output "software_projects" {
  description = "List of software projects"
  value       = data.jira_projects.software.projects
}

output "recent_issues" {
  description = "Recently updated issues"
  value       = data.jira_issues.recent.issues
}
