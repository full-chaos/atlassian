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
var _ datasource.DataSource = &ProjectsDataSource{}

func NewProjectsDataSource() datasource.DataSource {
	return &ProjectsDataSource{}
}

// ProjectsDataSource defines the data source implementation.
type ProjectsDataSource struct {
	providerData *JiraProviderData
}

// ProjectsDataSourceModel describes the data source data model.
type ProjectsDataSourceModel struct {
	CloudID      types.String   `tfsdk:"cloud_id"`
	ProjectTypes types.List     `tfsdk:"project_types"`
	Projects     []ProjectModel `tfsdk:"projects"`
}

// ProjectModel describes a single Jira project.
type ProjectModel struct {
	CloudID types.String `tfsdk:"cloud_id"`
	Key     types.String `tfsdk:"key"`
	Name    types.String `tfsdk:"name"`
	Type    types.String `tfsdk:"type"`
}

func (d *ProjectsDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_projects"
}

func (d *ProjectsDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Fetches a list of Jira projects from the Jira REST API.",
		Attributes: map[string]schema.Attribute{
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID. If not specified, uses the provider's cloud_id.",
				Optional:    true,
				Computed:    true,
			},
			"project_types": schema.ListAttribute{
				Description: "Filter projects by type. Valid values: SOFTWARE, BUSINESS, SERVICE_DESK. Defaults to ['SOFTWARE'].",
				ElementType: types.StringType,
				Optional:    true,
			},
			"projects": schema.ListNestedAttribute{
				Description: "List of Jira projects matching the criteria.",
				Computed:    true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"cloud_id": schema.StringAttribute{
							Description: "The Atlassian Cloud ID.",
							Computed:    true,
						},
						"key": schema.StringAttribute{
							Description: "The project key (e.g., 'PROJ').",
							Computed:    true,
						},
						"name": schema.StringAttribute{
							Description: "The project name.",
							Computed:    true,
						},
						"type": schema.StringAttribute{
							Description: "The project type (e.g., 'software', 'business').",
							Computed:    true,
						},
					},
				},
			},
		},
	}
}

func (d *ProjectsDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
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

func (d *ProjectsDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data ProjectsDataSourceModel

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

	// Determine project types
	var projectTypes []string
	if !data.ProjectTypes.IsNull() && !data.ProjectTypes.IsUnknown() {
		resp.Diagnostics.Append(data.ProjectTypes.ElementsAs(ctx, &projectTypes, false)...)
		if resp.Diagnostics.HasError() {
			return
		}
	}
	if len(projectTypes) == 0 {
		projectTypes = []string{"SOFTWARE"}
	}

	// Fetch projects from Jira REST API
	results, err := d.providerData.Client.ListProjectsViaREST(ctx, cloudID, projectTypes, 100)
	if err != nil {
		resp.Diagnostics.AddError(
			"Error fetching Jira projects",
			fmt.Sprintf("Unable to fetch projects: %s", err),
		)
		return
	}

	// Map results to Terraform model
	projects := make([]ProjectModel, 0, len(results))
	for _, r := range results {
		proj := ProjectModel{
			CloudID: types.StringValue(r.Project.CloudID),
			Key:     types.StringValue(r.Project.Key),
			Name:    types.StringValue(r.Project.Name),
		}
		if r.Project.Type != nil {
			proj.Type = types.StringValue(*r.Project.Type)
		} else {
			proj.Type = types.StringNull()
		}
		projects = append(projects, proj)
	}

	data.CloudID = types.StringValue(cloudID)
	data.Projects = projects

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
