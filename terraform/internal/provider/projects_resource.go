// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"fmt"

	"atlassian/atlassian"

	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure provider defined types fully satisfy framework interfaces.
var _ resource.Resource = &ProjectResource{}
var _ resource.ResourceWithImportState = &ProjectResource{}

func NewProjectResource() resource.Resource {
	return &ProjectResource{}
}

// ProjectResource defines the resource implementation.
type ProjectResource struct {
	providerData *JiraProviderData
}

// ProjectResourceModel describes the resource data model.
type ProjectResourceModel struct {
	CloudID types.String `tfsdk:"cloud_id"`
	Key     types.String `tfsdk:"key"`
	Name    types.String `tfsdk:"name"`
	Type    types.String `tfsdk:"type"`
}

func (r *ProjectResource) Metadata(ctx context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project"
}

func (r *ProjectResource) Schema(ctx context.Context, req resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Manages a Jira project.",
		Attributes: map[string]schema.Attribute{
			"cloud_id": schema.StringAttribute{
				Description: "The Atlassian Cloud ID.",
				Required:    true,
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"key": schema.StringAttribute{
				Description: "The project key (e.g., 'PROJ').",
				Required:    true,
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"name": schema.StringAttribute{
				Description: "The project name.",
				Required:    true,
			},
			"type": schema.StringAttribute{
				Description: "The project type (e.g., 'software', 'business'). Defaults to 'software'.",
				Optional:    true,
				Computed:    true,
			},
		},
	}
}

func (r *ProjectResource) Configure(ctx context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	if req.ProviderData == nil {
		return
	}

	providerData, ok := req.ProviderData.(*JiraProviderData)
	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected Resource Configure Type",
			fmt.Sprintf("Expected *JiraProviderData, got: %T. Please report this issue to the provider developers.", req.ProviderData),
		)
		return
	}

	r.providerData = providerData
}

func (r *ProjectResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var data ProjectResourceModel

	// Read Terraform plan data into the model
	resp.Diagnostics.Append(req.Plan.Get(ctx, &data)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Create project via Jira REST API
	p := atlassian.JiraProject{
		CloudID: data.CloudID.ValueString(),
		Key:     data.Key.ValueString(),
		Name:    data.Name.ValueString(),
	}
	if !data.Type.IsNull() {
		pt := data.Type.ValueString()
		p.Type = &pt
	}

	created, err := r.providerData.Client.CreateProject(ctx, p.CloudID, p)
	if err != nil {
		resp.Diagnostics.AddError("Error creating Jira project", err.Error())
		return
	}

	// Map response back to model
	data.Key = types.StringValue(created.Key)
	data.Name = types.StringValue(created.Name)
	if created.Type != nil {
		data.Type = types.StringValue(*created.Type)
	}

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}

func (r *ProjectResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var data ProjectResourceModel

	// Read Terraform current state data into the model
	resp.Diagnostics.Append(req.State.Get(ctx, &data)...)
	if resp.Diagnostics.HasError() {
		return
	}

	path := fmt.Sprintf("/rest/api/3/project/%s", data.Key.ValueString())
	payload, err := r.providerData.Client.GetJSON(ctx, path, nil)
	if err != nil {
		resp.State.RemoveResource(ctx)
		return
	}
	_ = payload

	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}

func (r *ProjectResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	// Jira REST API for updating projects is limited and often requires special permissions.
	// For simplicity, we'll just error for now or implement if needed.
	resp.Diagnostics.AddError("Update Not Implemented", "Updating Jira projects via this provider is not yet supported.")
}

func (r *ProjectResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var data ProjectResourceModel

	// Read Terraform current state data into the model
	resp.Diagnostics.Append(req.State.Get(ctx, &data)...)
	if resp.Diagnostics.HasError() {
		return
	}

	err := r.providerData.Client.DeleteProject(ctx, data.Key.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Error deleting Jira project", err.Error())
		return
	}
}

func (r *ProjectResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("key"), req, resp)
}
