package unit

import (
	"testing"

	"atlassian/atlassian/rest/gen"
	"atlassian/atlassian/rest/mappers"
)

func strPtr(s string) *string {
	return &s
}

func intPtr(i int) *int {
	return &i
}

func TestJiraSprintMapperTrimsFields(t *testing.T) {
	sprint := gen.Sprint{
		ID:           intPtr(100),
		Name:         strPtr("  Sprint 1  "),
		State:        strPtr("  active  "),
		StartDate:    strPtr("  2021-01-01T00:00:00.000Z  "),
		EndDate:      strPtr("  2021-01-15T00:00:00.000Z  "),
		CompleteDate: nil,
	}

	out, err := mappers.JiraSprintFromREST(sprint)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out.ID != "100" {
		t.Fatalf("expected ID 100, got %s", out.ID)
	}
	if out.Name != "Sprint 1" {
		t.Fatalf("expected Name 'Sprint 1', got %s", out.Name)
	}
	if out.State != "active" {
		t.Fatalf("expected State 'active', got %s", out.State)
	}
	if out.StartAt == nil || *out.StartAt != "2021-01-01T00:00:00.000Z" {
		t.Fatalf("unexpected StartAt: %v", out.StartAt)
	}
	if out.EndAt == nil || *out.EndAt != "2021-01-15T00:00:00.000Z" {
		t.Fatalf("unexpected EndAt: %v", out.EndAt)
	}
	if out.CompleteAt != nil {
		t.Fatalf("expected nil CompleteAt")
	}
}

func TestJiraSprintMapperHandlesOptionalDates(t *testing.T) {
	sprint := gen.Sprint{
		ID:           intPtr(101),
		Name:         strPtr("Sprint 2"),
		State:        strPtr("closed"),
		StartDate:    nil,
		EndDate:      nil,
		CompleteDate: strPtr("2021-01-30T12:00:00.000Z"),
	}

	out, err := mappers.JiraSprintFromREST(sprint)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out.ID != "101" {
		t.Fatalf("expected ID 101, got %s", out.ID)
	}
	if out.StartAt != nil {
		t.Fatalf("expected nil StartAt")
	}
	if out.EndAt != nil {
		t.Fatalf("expected nil EndAt")
	}
	if out.CompleteAt == nil || *out.CompleteAt != "2021-01-30T12:00:00.000Z" {
		t.Fatalf("unexpected CompleteAt: %v", out.CompleteAt)
	}
}

func TestJiraSprintMapperRequiresID(t *testing.T) {
	sprint := gen.Sprint{
		ID:    nil,
		Name:  strPtr("Sprint"),
		State: strPtr("active"),
	}

	_, err := mappers.JiraSprintFromREST(sprint)
	if err == nil {
		t.Fatal("expected error for missing ID")
	}
	if err.Error() != "sprint.id is required" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestJiraSprintMapperRequiresName(t *testing.T) {
	sprint := gen.Sprint{
		ID:    intPtr(100),
		Name:  strPtr(""),
		State: strPtr("active"),
	}

	_, err := mappers.JiraSprintFromREST(sprint)
	if err == nil {
		t.Fatal("expected error for empty name")
	}
	if err.Error() != "sprint.name is required" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestJiraSprintMapperRequiresNameNotWhitespace(t *testing.T) {
	sprint := gen.Sprint{
		ID:    intPtr(100),
		Name:  strPtr("   "),
		State: strPtr("active"),
	}

	_, err := mappers.JiraSprintFromREST(sprint)
	if err == nil {
		t.Fatal("expected error for whitespace-only name")
	}
	if err.Error() != "sprint.name is required" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestJiraSprintMapperRequiresState(t *testing.T) {
	sprint := gen.Sprint{
		ID:    intPtr(100),
		Name:  strPtr("Sprint"),
		State: strPtr(""),
	}

	_, err := mappers.JiraSprintFromREST(sprint)
	if err == nil {
		t.Fatal("expected error for empty state")
	}
	if err.Error() != "sprint.state is required" {
		t.Fatalf("unexpected error: %v", err)
	}
}
