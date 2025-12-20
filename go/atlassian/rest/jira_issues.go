package rest

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"atlassian/atlassian"
	"atlassian/atlassian/rest/gen"
	"atlassian/atlassian/rest/mappers"
)

var defaultJiraSearchFields = []string{
	"project",
	"issuetype",
	"status",
	"created",
	"updated",
	"resolutiondate",
	"assignee",
	"reporter",
	"labels",
	"components",
}

func (c *JiraRESTClient) ListIssuesViaREST(ctx context.Context, cloudID string, jql string, pageSize int) ([]atlassian.JiraIssue, error) {
	cloud := strings.TrimSpace(cloudID)
	if cloud == "" {
		return nil, errors.New("cloudID is required")
	}
	jqlClean := strings.TrimSpace(jql)
	if jqlClean == "" {
		return nil, errors.New("jql is required")
	}
	if pageSize <= 0 {
		pageSize = 50
	}

	fields := strings.Join(defaultJiraSearchFields, ",")
	startAt := 0
	seenStart := map[int]struct{}{}
	var out []atlassian.JiraIssue

	for {
		if _, ok := seenStart[startAt]; ok {
			return nil, errors.New("pagination startAt repeated; aborting to prevent infinite loop")
		}
		seenStart[startAt] = struct{}{}

		payload, err := c.GetJSON(ctx, "/rest/api/3/search", map[string]string{
			"jql":        jqlClean,
			"startAt":    strconv.Itoa(startAt),
			"maxResults": strconv.Itoa(pageSize),
			"fields":     fields,
		})
		if err != nil {
			return nil, err
		}
		page, err := gen.DecodeSearchResults(payload)
		if err != nil {
			return nil, fmt.Errorf("decode issue search response: %w", err)
		}

		for _, it := range page.Issues {
			mapped, err := mappers.JiraIssueFromREST(cloud, it)
			if err != nil {
				return nil, err
			}
			out = append(out, mapped)
		}

		if page.Total != nil && *page.Total >= 0 {
			if startAt+len(page.Issues) >= *page.Total {
				break
			}
		} else if len(page.Issues) < pageSize {
			break
		}

		if len(page.Issues) == 0 {
			break
		}
		startAt += len(page.Issues)
	}

	return out, nil
}
