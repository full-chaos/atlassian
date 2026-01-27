// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure provider defined types fully satisfy framework interfaces.
var _ datasource.DataSource = &WorklogsDataSource{}

func NewWorklogsDataSource() datasource.DataSource {
	return &WorklogsDataSource{}
}

// WorklogsDataSource defines the data source implementation.
type WorklogsDataSource struct {
	providerData *JiraProviderData
}

// WorklogsDataSourceModel describes the data source data model.
type WorklogsDataSourceModel struct {
	CloudID  types.String   `tfsdk:"cloud_id"`
	IssueKey types.String   `tfsdk:"issue_key"`
	Worklogs []WorklogModel `tfsdk:"worklogs"`
}

// WorklogModel describes a single Jira worklog entry.
type WorklogModel struct {
	IssueKey         types.String `tfsdk:"issue_key"`
	WorklogID        types.String `tfsdk:"worklog_id"`
	AuthorAccountID  types.String `tfsdk:"author_account_id"`
	AuthorName       types.String `tfsdk:"author_name"`
	StartedAt        types.String `tfsdk:"started_at"`
	TimeSpentSeconds types.Int64  `tfsdk:"time_spent_seconds"`
	CreatedAt        types.String `tfsdk:"created_at"`
	UpdatedAt        types.String `tfsdk:"updated_at"`
}

func (d *WorklogsDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_worklogs"
}

func (d *WorklogsDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Fetches a list of Jira worklogs for a given issue from the Jira REST API.",
		Attributes: map[string]schema.Attribute{
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID. If not specified, uses the provider's cloud_id.",
				Optional:    true,
				Computed:    true,
			},
			"issue_key": schema.StringAttribute{
				Description: "The Jira issue key (e.g., 'PROJ-123') to fetch worklogs from.",
				Required:    true,
			},
			"worklogs": schema.ListNestedAttribute{
				Description: "List of worklogs for the specified issue.",
				Computed:    true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"issue_key": schema.StringAttribute{
							Description: "The issue key this worklog belongs to.",
							Computed:    true,
						},
						"worklog_id": schema.StringAttribute{
							Description: "The worklog ID.",
							Computed:    true,
						},
						"author_account_id": schema.StringAttribute{
							Description: "The Atlassian account ID of the worklog author.",
							Computed:    true,
						},
						"author_name": schema.StringAttribute{
							Description: "The display name of the worklog author.",
							Computed:    true,
						},
						"started_at": schema.StringAttribute{
							Description: "When the work was started (RFC3339 format).",
							Computed:    true,
						},
						"time_spent_seconds": schema.Int64Attribute{
							Description: "The time spent in seconds.",
							Computed:    true,
						},
						"created_at": schema.StringAttribute{
							Description: "When the worklog was created (RFC3339 format).",
							Computed:    true,
						},
						"updated_at": schema.StringAttribute{
							Description: "When the worklog was last updated (RFC3339 format).",
							Computed:    true,
						},
					},
				},
			},
		},
	}
}

func (d *WorklogsDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
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

func (d *WorklogsDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data WorklogsDataSourceModel

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

	// Get issue key (required)
	issueKey := data.IssueKey.ValueString()
	if issueKey == "" {
		resp.Diagnostics.AddError(
			"Missing Issue Key",
			"issue_key is required and cannot be empty.",
		)
		return
	}

	// Fetch worklogs from Jira REST API
	results, err := d.providerData.Client.ListIssueWorklogsViaREST(ctx, issueKey, 100)
	if err != nil {
		resp.Diagnostics.AddError(
			"Error fetching Jira worklogs",
			fmt.Sprintf("Unable to fetch worklogs for issue %s: %s", issueKey, err),
		)
		return
	}

	// Map results to Terraform model
	worklogs := make([]WorklogModel, 0, len(results))
	for _, r := range results {
		wl := WorklogModel{
			IssueKey:         types.StringValue(r.IssueKey),
			WorklogID:        types.StringValue(r.WorklogID),
			StartedAt:        types.StringValue(r.StartedAt),
			TimeSpentSeconds: types.Int64Value(int64(r.TimeSpentSeconds)),
			CreatedAt:        types.StringValue(r.CreatedAt),
			UpdatedAt:        types.StringValue(r.UpdatedAt),
		}
		if r.Author != nil {
			wl.AuthorAccountID = types.StringValue(r.Author.AccountID)
			wl.AuthorName = types.StringValue(r.Author.DisplayName)
		} else {
			wl.AuthorAccountID = types.StringNull()
			wl.AuthorName = types.StringNull()
		}
		worklogs = append(worklogs, wl)
	}

	data.CloudID = types.StringValue(cloudID)
	data.Worklogs = worklogs

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
