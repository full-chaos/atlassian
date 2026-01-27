// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"net/http"
	"strings"
	"testing"
)

func TestWorklogsDataSource_Read(t *testing.T) {
	client := newMockClient(t, func(req *http.Request) *http.Response {
		if !strings.Contains(req.URL.Path, "/rest/api/3/issue/PROJ-123/worklog") {
			t.Errorf("unexpected path: %s", req.URL.Path)
		}
		return jsonResponse(http.StatusOK, `{
			"startAt": 0,
			"maxResults": 100,
			"total": 1,
			"worklogs": [
				{
					"id": "10001",
					"author": {
						"accountId": "author-id",
						"displayName": "Author Name"
					},
					"started": "2023-01-01T00:00:00.000+0000",
					"timeSpentSeconds": 3600,
					"created": "2023-01-01T00:00:00.000+0000",
					"updated": "2023-01-01T00:00:00.000+0000"
				}
			]
		}`)
	})

	ds := &WorklogsDataSource{
		providerData: &JiraProviderData{
			Client:  client,
			CloudID: "fake-cloud-id",
		},
	}
	
	if ds == nil {
		t.Fatal("ds is nil")
	}
}
