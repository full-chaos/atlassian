package unit

import (
	"testing"

	"atlassian/atlassian/graph/gen"
	"atlassian/atlassian/graph/mappers"
)

func TestJiraProjectsMapperTrimsAndDedups(t *testing.T) {
	project := gen.JiraProjectNode{Key: "  KEY  ", Name: "  Name  "}
	teams := []gen.OpsgenieTeamNode{
		{ID: " t1 ", Name: " Team 1 "},
		{ID: "t1", Name: "Team 1 duplicate"},
		{ID: "t2", Name: "Team 2"},
	}

	out, err := mappers.ProjectWithOpsgenieTeams(" cloud ", project, teams)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out.Project.CloudID != "cloud" || out.Project.Key != "KEY" || out.Project.Name != "Name" {
		t.Fatalf("unexpected project mapping: %+v", out.Project)
	}
	if len(out.OpsgenieTeams) != 2 || out.OpsgenieTeams[0].ID != "t1" || out.OpsgenieTeams[1].ID != "t2" {
		t.Fatalf("unexpected team mapping: %+v", out.OpsgenieTeams)
	}
}

func TestJiraProjectsMapperRequiresFields(t *testing.T) {
	_, err := mappers.ProjectWithOpsgenieTeams("cloud", gen.JiraProjectNode{Key: "", Name: "n"}, nil)
	if err == nil {
		t.Fatal("expected error")
	}
}
