// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"os"
	"strings"

	"atlassian/atlassian"
	"atlassian/atlassian/rest"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure JiraProvider satisfies various provider interfaces.
var _ provider.Provider = &JiraProvider{}

// JiraProvider defines the provider implementation.
type JiraProvider struct {
	// version is set to the provider version on release, "dev" when the
	// provider is built and run locally, and "test" when running acceptance
	// testing.
	version string
}

// JiraProviderModel describes the provider data model.
type JiraProviderModel struct {
	BaseURL     types.String `tfsdk:"base_url"`
	CloudID     types.String `tfsdk:"cloud_id"`
	Email       types.String `tfsdk:"email"`
	ApiToken    types.String `tfsdk:"api_token"`
	AccessToken types.String `tfsdk:"access_token"`
}

func (p *JiraProvider) Metadata(ctx context.Context, req provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "jira"
	resp.Version = p.version
}

func (p *JiraProvider) Schema(ctx context.Context, req provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Interact with Jira REST API to read project and issue data.",
		Attributes: map[string]schema.Attribute{
			"base_url": schema.StringAttribute{
				Description: "The base URL for Jira API. For OAuth, use 'https://api.atlassian.com/ex/jira/{cloudId}'. " +
					"For tenanted access, use 'https://{subdomain}.atlassian.net'. " +
					"Can also be set via the ATLASSIAN_JIRA_BASE_URL environment variable.",
				Optional: true,
			},
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID. Required for API operations. " +
					"Can also be set via the ATLASSIAN_CLOUD_ID or ATLASSIAN_JIRA_CLOUD_ID environment variable.",
				Optional: true,
			},
			"email": schema.StringAttribute{
				Description: "Email address for Basic API Token authentication. " +
					"Can also be set via the ATLASSIAN_EMAIL environment variable.",
				Optional: true,
			},
			"api_token": schema.StringAttribute{
				Description: "API Token for Basic authentication. " +
					"Can also be set via the ATLASSIAN_API_TOKEN environment variable.",
				Optional:  true,
				Sensitive: true,
			},
			"access_token": schema.StringAttribute{
				Description: "OAuth 2.0 access token for Bearer authentication. " +
					"Can also be set via the ATLASSIAN_OAUTH_ACCESS_TOKEN environment variable.",
				Optional:  true,
				Sensitive: true,
			},
		},
	}
}

// JiraProviderData holds the configured client and settings passed to data sources and resources.
type JiraProviderData struct {
	Client  *rest.JiraRESTClient
	CloudID string
}

func (p *JiraProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var config JiraProviderModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Resolve values from config or environment
	baseURL := getConfigOrEnv(config.BaseURL, "ATLASSIAN_JIRA_BASE_URL", "")
	cloudID := getConfigOrEnvMulti(config.CloudID, []string{"ATLASSIAN_CLOUD_ID", "ATLASSIAN_JIRA_CLOUD_ID"}, "")
	email := getConfigOrEnv(config.Email, "ATLASSIAN_EMAIL", "")
	apiToken := getConfigOrEnv(config.ApiToken, "ATLASSIAN_API_TOKEN", "")
	accessToken := getConfigOrEnv(config.AccessToken, "ATLASSIAN_OAUTH_ACCESS_TOKEN", "")

	// Validate cloud_id
	if cloudID == "" {
		resp.Diagnostics.AddError(
			"Missing Cloud ID",
			"The provider requires a Cloud ID. Set the cloud_id attribute or the ATLASSIAN_CLOUD_ID environment variable.",
		)
		return
	}

	// Determine authentication method
	var auth atlassian.AuthProvider
	if accessToken != "" {
		// OAuth Bearer authentication
		token := accessToken
		auth = atlassian.BearerAuth{
			TokenGetter: func() (string, error) {
				return token, nil
			},
		}
		// Default base URL for OAuth
		if baseURL == "" {
			baseURL = "https://api.atlassian.com/ex/jira/" + cloudID
		}
	} else if email != "" && apiToken != "" {
		// Basic API Token authentication
		auth = atlassian.BasicAPITokenAuth{
			Email: email,
			Token: apiToken,
		}
		// Base URL is required for Basic auth
		if baseURL == "" {
			resp.Diagnostics.AddError(
				"Missing Base URL",
				"When using Basic API Token authentication, base_url must be set to your Jira instance URL (e.g., https://yourteam.atlassian.net).",
			)
			return
		}
	} else {
		resp.Diagnostics.AddError(
			"Missing Authentication",
			"The provider requires authentication. Provide either access_token (OAuth) or email + api_token (Basic auth).",
		)
		return
	}

	client := &rest.JiraRESTClient{
		BaseURL: baseURL,
		Auth:    auth,
	}

	providerData := &JiraProviderData{
		Client:  client,
		CloudID: cloudID,
	}

	resp.DataSourceData = providerData
	resp.ResourceData = providerData
}

func (p *JiraProvider) Resources(ctx context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		NewProjectResource,
		NewVersionResource,
	}
}

func (p *JiraProvider) DataSources(ctx context.Context) []func() datasource.DataSource {
	return []func() datasource.DataSource{
		NewProjectsDataSource,
		NewIssuesDataSource,
		NewSprintsDataSource,
		NewWorklogsDataSource,
	}
}

// New creates a new provider instance.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &JiraProvider{
			version: version,
		}
	}
}

// Helper functions

func getConfigOrEnv(configValue types.String, envKey string, defaultValue string) string {
	if !configValue.IsNull() && !configValue.IsUnknown() {
		v := strings.TrimSpace(configValue.ValueString())
		if v != "" {
			return v
		}
	}
	if v := strings.TrimSpace(os.Getenv(envKey)); v != "" {
		return v
	}
	return defaultValue
}

func getConfigOrEnvMulti(configValue types.String, envKeys []string, defaultValue string) string {
	if !configValue.IsNull() && !configValue.IsUnknown() {
		v := strings.TrimSpace(configValue.ValueString())
		if v != "" {
			return v
		}
	}
	for _, key := range envKeys {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			return v
		}
	}
	return defaultValue
}
