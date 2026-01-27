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
var _ datasource.DataSource = &SprintsDataSource{}

func NewSprintsDataSource() datasource.DataSource {
	return &SprintsDataSource{}
}

// SprintsDataSource defines the data source implementation.
type SprintsDataSource struct {
	providerData *JiraProviderData
}

// SprintsDataSourceModel describes the data source data model.
type SprintsDataSourceModel struct {
	CloudID  types.String  `tfsdk:"cloud_id"`
	BoardID  types.Int64   `tfsdk:"board_id"`
	State    types.String  `tfsdk:"state"`
	Sprints  []SprintModel `tfsdk:"sprints"`
}

// SprintModel describes a single Jira sprint.
type SprintModel struct {
	ID         types.String `tfsdk:"id"`
	Name       types.String `tfsdk:"name"`
	State      types.String `tfsdk:"state"`
	StartAt    types.String `tfsdk:"start_at"`
	EndAt      types.String `tfsdk:"end_at"`
	CompleteAt types.String `tfsdk:"complete_at"`
}

func (d *SprintsDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_sprints"
}

func (d *SprintsDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Fetches a list of Jira sprints for a given board from the Jira Agile REST API.",
		Attributes: map[string]schema.Attribute{
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID. If not specified, uses the provider's cloud_id.",
				Optional:    true,
				Computed:    true,
			},
			"board_id": schema.Int64Attribute{
				Description: "The ID of the Jira Agile board to fetch sprints from.",
				Required:    true,
			},
			"state": schema.StringAttribute{
				Description: "Filter sprints by state. Valid values: 'future', 'active', 'closed'. If not specified, returns all sprints.",
				Optional:    true,
			},
			"sprints": schema.ListNestedAttribute{
				Description: "List of Jira sprints matching the criteria.",
				Computed:    true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id": schema.StringAttribute{
							Description: "The sprint ID.",
							Computed:    true,
						},
						"name": schema.StringAttribute{
							Description: "The sprint name.",
							Computed:    true,
						},
						"state": schema.StringAttribute{
							Description: "The sprint state (e.g., 'future', 'active', 'closed').",
							Computed:    true,
						},
						"start_at": schema.StringAttribute{
							Description: "When the sprint started (RFC3339 format), if applicable.",
							Computed:    true,
						},
						"end_at": schema.StringAttribute{
							Description: "When the sprint is scheduled to end (RFC3339 format), if applicable.",
							Computed:    true,
						},
						"complete_at": schema.StringAttribute{
							Description: "When the sprint was completed (RFC3339 format), if applicable.",
							Computed:    true,
						},
					},
				},
			},
		},
	}
}

func (d *SprintsDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
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

func (d *SprintsDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data SprintsDataSourceModel

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

	// Get board ID (required)
	boardID := int(data.BoardID.ValueInt64())
	if boardID <= 0 {
		resp.Diagnostics.AddError(
			"Invalid Board ID",
			"board_id must be a positive integer.",
		)
		return
	}

	// Get optional state filter
	var state string
	if !data.State.IsNull() && !data.State.IsUnknown() {
		state = data.State.ValueString()
	}

	// Fetch sprints from Jira Agile REST API
	results, err := d.providerData.Client.ListBoardSprintsViaREST(ctx, boardID, state, 50)
	if err != nil {
		resp.Diagnostics.AddError(
			"Error fetching Jira sprints",
			fmt.Sprintf("Unable to fetch sprints for board %d: %s", boardID, err),
		)
		return
	}

	// Map results to Terraform model
	sprints := make([]SprintModel, 0, len(results))
	for _, r := range results {
		sprint := SprintModel{
			ID:    types.StringValue(r.ID),
			Name:  types.StringValue(r.Name),
			State: types.StringValue(r.State),
		}
		if r.StartAt != nil {
			sprint.StartAt = types.StringValue(*r.StartAt)
		} else {
			sprint.StartAt = types.StringNull()
		}
		if r.EndAt != nil {
			sprint.EndAt = types.StringValue(*r.EndAt)
		} else {
			sprint.EndAt = types.StringNull()
		}
		if r.CompleteAt != nil {
			sprint.CompleteAt = types.StringValue(*r.CompleteAt)
		} else {
			sprint.CompleteAt = types.StringNull()
		}
		sprints = append(sprints, sprint)
	}

	data.CloudID = types.StringValue(cloudID)
	data.Sprints = sprints

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
