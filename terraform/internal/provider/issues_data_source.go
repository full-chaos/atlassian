// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"fmt"
	"math/big"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure provider defined types fully satisfy framework interfaces.
var _ datasource.DataSource = &IssuesDataSource{}

func NewIssuesDataSource() datasource.DataSource {
	return &IssuesDataSource{}
}

// IssuesDataSource defines the data source implementation.
type IssuesDataSource struct {
	providerData *JiraProviderData
}

// IssuesDataSourceModel describes the data source data model.
type IssuesDataSourceModel struct {
	CloudID types.String `tfsdk:"cloud_id"`
	JQL     types.String `tfsdk:"jql"`
	Issues  []IssueModel `tfsdk:"issues"`
}

// IssueModel describes a single Jira issue.
type IssueModel struct {
	CloudID     types.String `tfsdk:"cloud_id"`
	Key         types.String `tfsdk:"key"`
	ProjectKey  types.String `tfsdk:"project_key"`
	IssueType   types.String `tfsdk:"issue_type"`
	Status      types.String `tfsdk:"status"`
	CreatedAt   types.String `tfsdk:"created_at"`
	UpdatedAt   types.String `tfsdk:"updated_at"`
	ResolvedAt  types.String `tfsdk:"resolved_at"`
	Labels      types.List   `tfsdk:"labels"`
	Components  types.List   `tfsdk:"components"`
	StoryPoints types.Number `tfsdk:"story_points"`
}

func (d *IssuesDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_issues"
}

func (d *IssuesDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Fetches a list of Jira issues from the Jira REST API using JQL.",
		Attributes: map[string]schema.Attribute{
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID. If not specified, uses the provider's cloud_id.",
				Optional:    true,
				Computed:    true,
			},
			"jql": schema.StringAttribute{
				Description: "JQL query to filter issues (e.g., 'project = PROJ AND status = Open').",
				Required:    true,
			},
			"issues": schema.ListNestedAttribute{
				Description: "List of Jira issues matching the JQL query.",
				Computed:    true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"cloud_id": schema.StringAttribute{
							Description: "The Atlassian Cloud ID.",
							Computed:    true,
						},
						"key": schema.StringAttribute{
							Description: "The issue key (e.g., 'PROJ-123').",
							Computed:    true,
						},
						"project_key": schema.StringAttribute{
							Description: "The project key.",
							Computed:    true,
						},
						"issue_type": schema.StringAttribute{
							Description: "The issue type (e.g., 'Bug', 'Story').",
							Computed:    true,
						},
						"status": schema.StringAttribute{
							Description: "The issue status.",
							Computed:    true,
						},
						"created_at": schema.StringAttribute{
							Description: "When the issue was created (RFC3339 format).",
							Computed:    true,
						},
						"updated_at": schema.StringAttribute{
							Description: "When the issue was last updated (RFC3339 format).",
							Computed:    true,
						},
						"resolved_at": schema.StringAttribute{
							Description: "When the issue was resolved (RFC3339 format), if applicable.",
							Computed:    true,
						},
						"labels": schema.ListAttribute{
							Description: "Labels assigned to the issue.",
							ElementType: types.StringType,
							Computed:    true,
						},
						"components": schema.ListAttribute{
							Description: "Components assigned to the issue.",
							ElementType: types.StringType,
							Computed:    true,
						},
						"story_points": schema.NumberAttribute{
							Description: "Story points assigned to the issue, if applicable.",
							Computed:    true,
						},
					},
				},
			},
		},
	}
}

func (d *IssuesDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	// Prevent panic if the provider has not been configured.
	if req.ProviderData == nil {
		return
	}

	providerData, ok := req.ProviderData.(*JiraProviderData)
	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected Data Source Configure Type",
			fmt.Sprintf("Expected *JiraProviderData, got: %T. Please report this issue to the provider developers.", req.ProviderData),
		)
		return
	}

	d.providerData = providerData
}

func (d *IssuesDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data IssuesDataSourceModel

	// Read Terraform configuration data into the model
	resp.Diagnostics.Append(req.Config.Get(ctx, &data)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Determine cloud ID
	cloudID := d.providerData.CloudID
	if !data.CloudID.IsNull() && !data.CloudID.IsUnknown() {
		cloudID = data.CloudID.ValueString()
	}

	// Validate JQL
	jql := data.JQL.ValueString()
	if jql == "" {
		resp.Diagnostics.AddError(
			"Missing JQL Query",
			"The jql attribute is required to query Jira issues.",
		)
		return
	}

	// Fetch issues from Jira REST API
	results, err := d.providerData.Client.ListIssuesViaREST(ctx, cloudID, jql, 100)
	if err != nil {
		resp.Diagnostics.AddError(
			"Error fetching Jira issues",
			fmt.Sprintf("Unable to fetch issues: %s", err),
		)
		return
	}

	// Map results to Terraform model
	issues := make([]IssueModel, 0, len(results))
	for _, r := range results {
		issue := IssueModel{
			CloudID:    types.StringValue(r.CloudID),
			Key:        types.StringValue(r.Key),
			ProjectKey: types.StringValue(r.ProjectKey),
			IssueType:  types.StringValue(r.IssueType),
			Status:     types.StringValue(r.Status),
			CreatedAt:  types.StringValue(r.CreatedAt),
			UpdatedAt:  types.StringValue(r.UpdatedAt),
		}

		if r.ResolvedAt != nil {
			issue.ResolvedAt = types.StringValue(*r.ResolvedAt)
		} else {
			issue.ResolvedAt = types.StringNull()
		}

		// Convert labels
		labels, diags := types.ListValueFrom(ctx, types.StringType, r.Labels)
		resp.Diagnostics.Append(diags...)
		if resp.Diagnostics.HasError() {
			return
		}
		issue.Labels = labels

		// Convert components
		components, diags := types.ListValueFrom(ctx, types.StringType, r.Components)
		resp.Diagnostics.Append(diags...)
		if resp.Diagnostics.HasError() {
			return
		}
		issue.Components = components

		// Story points
		if r.StoryPoints != nil {
			issue.StoryPoints = types.NumberValue(bigFloatFromFloat64(*r.StoryPoints))
		} else {
			issue.StoryPoints = types.NumberNull()
		}

		issues = append(issues, issue)
	}

	data.CloudID = types.StringValue(cloudID)
	data.Issues = issues

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}

// bigFloatFromFloat64 converts a float64 to a *big.Float for Terraform's Number type.
func bigFloatFromFloat64(f float64) *big.Float {
	return big.NewFloat(f)
}
