package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"go/format"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

type config struct {
	CloudIDType        string
	ProjectsFirstType  string
	ProjectsAfterType  string
	OpsFirstType       string
	OpsAfterType       string
	PageInfoEndCursor  bool
	ProjectsEdgeCursor bool
	OpsEdgeCursor      bool
	ProjectHasID       bool

	RefetchStrategy string // "node" or "jira"

	ProjectTypeName string
	NodeIDArgType   string

	JiraProjectFieldName   string
	JiraProjectKeyArgName  string
	JiraProjectKeyArgType  string
}

func main() {
	repoRoot, err := findRepoRoot()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	schemaPath := filepath.Join(repoRoot, "graphql", "schema.introspection.json")
	if _, err := os.Stat(schemaPath); err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		baseURL := strings.TrimSpace(os.Getenv("ATLASSIAN_GQL_BASE_URL"))
		if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN")) != "" {
			baseURL = "https://api.atlassian.com"
		}
		if baseURL == "" && strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN")) != "" {
			baseURL = "https://api.atlassian.com"
		}
		if baseURL == "" {
			fmt.Fprintf(os.Stderr, "Missing %s and ATLASSIAN_GQL_BASE_URL not set\n", schemaPath)
			os.Exit(2)
		}
		auth := buildAuthFromEnv()
		if auth == nil {
			fmt.Fprintln(os.Stderr, "No credentials available in env vars to fetch schema")
			os.Exit(2)
		}

		opts := graph.SchemaFetchOptions{
			OutputDir:        filepath.Dir(schemaPath),
			ExperimentalAPIs: parseExperimentalAPIs(),
			Timeout:          30 * time.Second,
			HTTPClient:       &http.Client{Timeout: 30 * time.Second},
		}
		if _, err := graph.FetchSchemaIntrospection(context.Background(), baseURL, auth, opts); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
	}

	schema, err := loadSchema(schemaPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	cfg, err := discoverConfig(schema)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "jira_projects_api.go")
	if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	source, err := renderGo(cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	formatted, err := format.Source([]byte(source))
	if err != nil {
		fmt.Fprintln(os.Stderr, "format generated code:", err)
		fmt.Fprintln(os.Stderr, source)
		os.Exit(2)
	}
	if err := os.WriteFile(outPath, formatted, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	fmt.Println("Wrote", outPath)
}

func findRepoRoot() (string, error) {
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		return "", errors.New("unable to locate generator path")
	}
	dir := filepath.Dir(thisFile)
	root := filepath.Clean(filepath.Join(dir, "..", "..", ".."))
	return root, nil
}

func parseExperimentalAPIs() []string {
	raw := os.Getenv("ATLASSIAN_GQL_EXPERIMENTAL_APIS")
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	var out []string
	for _, p := range parts {
		if s := strings.TrimSpace(p); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func buildAuthFromEnv() atlassian.AuthProvider {
	token := strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN"))
	refreshToken := strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_REFRESH_TOKEN"))
	clientID := strings.TrimSpace(os.Getenv("ATLASSIAN_CLIENT_ID"))
	clientSecret := strings.TrimSpace(os.Getenv("ATLASSIAN_CLIENT_SECRET"))
	email := strings.TrimSpace(os.Getenv("ATLASSIAN_EMAIL"))
	apiToken := strings.TrimSpace(os.Getenv("ATLASSIAN_API_TOKEN"))
	cookiesJSON := strings.TrimSpace(os.Getenv("ATLASSIAN_COOKIES_JSON"))

	if refreshToken != "" && clientID != "" && clientSecret != "" {
		return &atlassian.OAuthRefreshTokenAuth{
			ClientID:     clientID,
			ClientSecret: clientSecret,
			RefreshToken: refreshToken,
			Timeout:      30 * time.Second,
		}
	}
	if token != "" {
		if clientSecret != "" && token == clientSecret {
			fmt.Fprintln(os.Stderr, "ATLASSIAN_OAUTH_ACCESS_TOKEN appears to be set to ATLASSIAN_CLIENT_SECRET; set an OAuth access token (not the client secret).")
			return nil
		}
		return atlassian.BearerAuth{
			TokenGetter: func() (string, error) { return token, nil },
		}
	}
	if email != "" && apiToken != "" {
		return atlassian.BasicAPITokenAuth{Email: email, Token: apiToken}
	}
	if cookiesJSON != "" {
		var cookies map[string]string
		if err := json.Unmarshal([]byte(cookiesJSON), &cookies); err == nil && len(cookies) > 0 {
			var httpCookies []*http.Cookie
			for k, v := range cookies {
				httpCookies = append(httpCookies, &http.Cookie{Name: k, Value: v})
			}
			return atlassian.CookieAuth{Cookies: httpCookies}
		}
	}
	return nil
}

func loadSchema(path string) (map[string]any, error) {
	rawBytes, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var envelope map[string]any
	if err := json.Unmarshal(rawBytes, &envelope); err != nil {
		return nil, err
	}
	data, ok := envelope["data"].(map[string]any)
	if ok {
		if schema, ok := data["__schema"].(map[string]any); ok {
			return schema, nil
		}
	}
	if schema, ok := envelope["__schema"].(map[string]any); ok {
		return schema, nil
	}
	return nil, errors.New("introspection JSON missing data.__schema")
}

func typesMap(schema map[string]any) (map[string]map[string]any, error) {
	rawTypes, ok := schema["types"].([]any)
	if !ok {
		return nil, errors.New("introspection JSON missing __schema.types[]")
	}
	out := make(map[string]map[string]any)
	for _, t := range rawTypes {
		m, ok := t.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		if name != "" {
			out[name] = m
		}
	}
	return out, nil
}

func unwrapNamedType(typeRef any) (name string, kind string) {
	cur, _ := typeRef.(map[string]any)
	for i := 0; i < 16 && cur != nil; i++ {
		if n, ok := cur["name"].(string); ok && n != "" {
			name = n
			kind, _ = cur["kind"].(string)
			return
		}
		next, _ := cur["ofType"].(map[string]any)
		cur = next
	}
	return "", ""
}

func typeRefToGQL(typeRef any) (string, error) {
	m, ok := typeRef.(map[string]any)
	if !ok {
		return "", errors.New("invalid typeRef")
	}
	kind, _ := m["kind"].(string)
	switch kind {
	case "NON_NULL":
		inner, err := typeRefToGQL(m["ofType"])
		if err != nil {
			return "", err
		}
		return inner + "!", nil
	case "LIST":
		inner, err := typeRefToGQL(m["ofType"])
		if err != nil {
			return "", err
		}
		return "[" + inner + "]", nil
	default:
		name, _ := m["name"].(string)
		if name == "" {
			return "", errors.New("invalid named typeRef")
		}
		return name, nil
	}
}

func getField(typeDef map[string]any, name string) map[string]any {
	rawFields, _ := typeDef["fields"].([]any)
	for _, f := range rawFields {
		m, ok := f.(map[string]any)
		if !ok {
			continue
		}
		if m["name"] == name {
			return m
		}
	}
	return nil
}

func getInputField(typeDef map[string]any, name string) map[string]any {
	rawFields, _ := typeDef["inputFields"].([]any)
	for _, f := range rawFields {
		m, ok := f.(map[string]any)
		if !ok {
			continue
		}
		if m["name"] == name {
			return m
		}
	}
	return nil
}

func getArg(fieldDef map[string]any, name string) map[string]any {
	rawArgs, _ := fieldDef["args"].([]any)
	for _, a := range rawArgs {
		m, ok := a.(map[string]any)
		if !ok {
			continue
		}
		if m["name"] == name {
			return m
		}
	}
	return nil
}

func discoverConfig(schema map[string]any) (*config, error) {
	types, err := typesMap(schema)
	if err != nil {
		return nil, err
	}

	queryType, ok := schema["queryType"].(map[string]any)
	if !ok {
		return nil, errors.New("introspection JSON missing __schema.queryType")
	}
	queryName, _ := queryType["name"].(string)
	if queryName == "" {
		return nil, errors.New("introspection JSON missing __schema.queryType.name")
	}
	queryDef := types[queryName]
	if queryDef == nil {
		return nil, fmt.Errorf("missing query type definition: %s", queryName)
	}

	jiraField := getField(queryDef, "jira")
	if jiraField == nil {
		return nil, fmt.Errorf("missing required field %s.jira", queryName)
	}
	jiraTypeName, _ := unwrapNamedType(jiraField["type"])
	jiraDef := types[jiraTypeName]
	if jiraTypeName == "" || jiraDef == nil {
		return nil, errors.New("failed to resolve type for field Query.jira")
	}

	allProjects := getField(jiraDef, "allJiraProjects")
	if allProjects == nil {
		return nil, fmt.Errorf("missing required field %s.allJiraProjects", jiraTypeName)
	}

	var missing []string
	for _, argName := range []string{"cloudId", "filter", "first", "after"} {
		if getArg(allProjects, argName) == nil {
			missing = append(missing, fmt.Sprintf("field jira.allJiraProjects.args.%s", argName))
		}
	}
	filterArg := getArg(allProjects, "filter")
	if filterArg != nil {
		filterTypeName, _ := unwrapNamedType(filterArg["type"])
		filterDef := types[filterTypeName]
		if filterDef == nil {
			missing = append(missing, "field jira.allJiraProjects.args.filter.type")
		} else if getInputField(filterDef, "types") == nil {
			missing = append(missing, fmt.Sprintf("type %s.inputFields.types", filterTypeName))
		}
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required fields:\n- %s", strings.Join(missing, "\n- "))
	}

	cloudIDType, err := typeRefToGQL(getArg(allProjects, "cloudId")["type"])
	if err != nil {
		return nil, err
	}
	projectsFirstType, err := typeRefToGQL(getArg(allProjects, "first")["type"])
	if err != nil {
		return nil, err
	}
	projectsAfterType, err := typeRefToGQL(getArg(allProjects, "after")["type"])
	if err != nil {
		return nil, err
	}

	connTypeName, _ := unwrapNamedType(allProjects["type"])
	connDef := types[connTypeName]
	if connDef == nil {
		return nil, errors.New("failed to resolve allJiraProjects connection type")
	}
	pageInfoField := getField(connDef, "pageInfo")
	edgesField := getField(connDef, "edges")
	if pageInfoField == nil || edgesField == nil {
		return nil, fmt.Errorf("missing required connection fields on %s", connTypeName)
	}

	pageInfoTypeName, _ := unwrapNamedType(pageInfoField["type"])
	pageInfoDef := types[pageInfoTypeName]
	if pageInfoDef == nil {
		return nil, fmt.Errorf("missing PageInfo type definition: %s", pageInfoTypeName)
	}
	if getField(pageInfoDef, "hasNextPage") == nil {
		return nil, fmt.Errorf("missing PageInfo.hasNextPage on %s", pageInfoTypeName)
	}
	pageInfoEndCursor := getField(pageInfoDef, "endCursor") != nil

	edgeTypeName, _ := unwrapNamedType(edgesField["type"])
	edgeDef := types[edgeTypeName]
	if edgeDef == nil {
		return nil, fmt.Errorf("missing edge type definition: %s", edgeTypeName)
	}
	projectsEdgeCursor := getField(edgeDef, "cursor") != nil
	nodeField := getField(edgeDef, "node")
	if nodeField == nil {
		return nil, fmt.Errorf("missing edge.node on %s", edgeTypeName)
	}
	projectTypeName, _ := unwrapNamedType(nodeField["type"])
	projectDef := types[projectTypeName]
	if projectDef == nil {
		return nil, fmt.Errorf("missing project type definition: %s", projectTypeName)
	}

	projectHasID := getField(projectDef, "id") != nil
	if getField(projectDef, "key") == nil {
		missing = append(missing, fmt.Sprintf("type %s.fields.key", projectTypeName))
	}
	if getField(projectDef, "name") == nil {
		missing = append(missing, fmt.Sprintf("type %s.fields.name", projectTypeName))
	}
	opsField := getField(projectDef, "opsgenieTeamsAvailableToLinkWith")
	if opsField == nil {
		missing = append(missing, fmt.Sprintf("type %s.fields.opsgenieTeamsAvailableToLinkWith", projectTypeName))
	} else {
		for _, argName := range []string{"first", "after"} {
			if getArg(opsField, argName) == nil {
				missing = append(missing, fmt.Sprintf("field %s.opsgenieTeamsAvailableToLinkWith.args.%s", projectTypeName, argName))
			}
		}
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required fields:\n- %s", strings.Join(missing, "\n- "))
	}

	opsFirstType, err := typeRefToGQL(getArg(opsField, "first")["type"])
	if err != nil {
		return nil, err
	}
	opsAfterType, err := typeRefToGQL(getArg(opsField, "after")["type"])
	if err != nil {
		return nil, err
	}

	opsConnTypeName, _ := unwrapNamedType(opsField["type"])
	opsConnDef := types[opsConnTypeName]
	if opsConnDef == nil {
		return nil, fmt.Errorf("missing opsgenie connection type: %s", opsConnTypeName)
	}
	opsEdgesField := getField(opsConnDef, "edges")
	if opsEdgesField == nil {
		return nil, fmt.Errorf("missing opsgenie edges field on %s", opsConnTypeName)
	}
	opsEdgeTypeName, _ := unwrapNamedType(opsEdgesField["type"])
	opsEdgeDef := types[opsEdgeTypeName]
	if opsEdgeDef == nil {
		return nil, fmt.Errorf("missing opsgenie edge type: %s", opsEdgeTypeName)
	}
	opsEdgeCursor := getField(opsEdgeDef, "cursor") != nil
	opsNodeField := getField(opsEdgeDef, "node")
	if opsNodeField == nil {
		return nil, fmt.Errorf("missing opsgenie edge.node on %s", opsEdgeTypeName)
	}
	opsTeamTypeName, _ := unwrapNamedType(opsNodeField["type"])
	opsTeamDef := types[opsTeamTypeName]
	if opsTeamDef == nil {
		return nil, fmt.Errorf("missing opsgenie team type: %s", opsTeamTypeName)
	}
	if getField(opsTeamDef, "id") == nil {
		missing = append(missing, fmt.Sprintf("type %s.fields.id", opsTeamTypeName))
	}
	if getField(opsTeamDef, "name") == nil {
		missing = append(missing, fmt.Sprintf("type %s.fields.name", opsTeamTypeName))
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required fields:\n- %s", strings.Join(missing, "\n- "))
	}

	refetchStrategy := "jira"
	nodeIDArgType := ""

	if nodeFieldDef := getField(queryDef, "node"); nodeFieldDef != nil {
		if idArg := getArg(nodeFieldDef, "id"); idArg != nil && projectHasID {
			if gqlType, err := typeRefToGQL(idArg["type"]); err == nil && gqlType != "" {
				refetchStrategy = "node"
				nodeIDArgType = gqlType
			}
		}
	}

	jiraProjectFieldName := ""
	jiraProjectKeyArgName := ""
	jiraProjectKeyArgType := ""

	if refetchStrategy != "node" {
		rawFields, _ := jiraDef["fields"].([]any)
		type candidate struct {
			Name string
			Def  map[string]any
		}
		var candidates []candidate
		for _, f := range rawFields {
			fd, ok := f.(map[string]any)
			if !ok {
				continue
			}
			fTypeName, _ := unwrapNamedType(fd["type"])
			if fTypeName == projectTypeName {
				n, _ := fd["name"].(string)
				if n != "" {
					candidates = append(candidates, candidate{Name: n, Def: fd})
				}
			}
		}
		sort.Slice(candidates, func(i, j int) bool { return candidates[i].Name < candidates[j].Name })
		for _, c := range candidates {
			if getArg(c.Def, "cloudId") == nil {
				continue
			}
			for _, keyArgName := range []string{"key", "projectKey"} {
				if keyArg := getArg(c.Def, keyArgName); keyArg != nil {
					if gqlType, err := typeRefToGQL(keyArg["type"]); err == nil && gqlType != "" {
						jiraProjectFieldName = c.Name
						jiraProjectKeyArgName = keyArgName
						jiraProjectKeyArgType = gqlType
						break
					}
				}
			}
			if jiraProjectFieldName != "" {
				break
			}
		}
		if jiraProjectFieldName == "" {
			return nil, errors.New("unable to determine per-project refetch strategy for nested opsgenie pagination")
		}
	}

	return &config{
		CloudIDType:        cloudIDType,
		ProjectsFirstType:  projectsFirstType,
		ProjectsAfterType:  projectsAfterType,
		OpsFirstType:       opsFirstType,
		OpsAfterType:       opsAfterType,
		PageInfoEndCursor:  pageInfoEndCursor,
		ProjectsEdgeCursor: projectsEdgeCursor,
		OpsEdgeCursor:      opsEdgeCursor,
		ProjectHasID:       projectHasID,
		RefetchStrategy:    refetchStrategy,
		ProjectTypeName:    projectTypeName,
		NodeIDArgType:      nodeIDArgType,
		JiraProjectFieldName:  jiraProjectFieldName,
		JiraProjectKeyArgName: jiraProjectKeyArgName,
		JiraProjectKeyArgType: jiraProjectKeyArgType,
	}, nil
}

func renderGo(cfg *config) (string, error) {
	pageInfoSelect := "hasNextPage"
	if cfg.PageInfoEndCursor {
		pageInfoSelect += " endCursor"
	}
	projectEdgeSelect := "node {"
	if cfg.ProjectsEdgeCursor {
		projectEdgeSelect = "cursor\n      node {"
	}
	opsEdgeSelect := "node {"
	if cfg.OpsEdgeCursor {
		opsEdgeSelect = "cursor\n            node {"
	}
	projectIDSelect := ""
	if cfg.ProjectHasID {
		projectIDSelect = "id\n          "
	}

	projectsTemplate := fmt.Sprintf(`query JiraProjectsPage(
  $cloudId: %s,
  $first: %s,
  $after: %s,
  $opsFirst: %s
) {
  jira {
    projects: allJiraProjects(
      cloudId: $cloudId,
      filter: { types: [__PROJECT_TYPES__] },
      first: $first,
      after: $after
    ) {
      pageInfo { %s }
      edges {
        %s
          %skey
          name
          opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $opsFirst) {
            pageInfo { %s }
            edges {
              %s
                id
                name
              }
            }
          }
        }
      }
    }
  }
}
`, cfg.CloudIDType, cfg.ProjectsFirstType, cfg.ProjectsAfterType, cfg.OpsFirstType, pageInfoSelect, projectEdgeSelect, projectIDSelect, pageInfoSelect, opsEdgeSelect)

	var opsQuery string
	if cfg.RefetchStrategy == "node" {
		if cfg.NodeIDArgType == "" {
			return "", errors.New("invalid config: node strategy missing NodeIDArgType")
		}
		opsQuery = fmt.Sprintf(`query JiraProjectOpsgenieTeamsPage(
  $projectId: %s,
  $first: %s,
  $after: %s
) {
  project: node(id: $projectId) {
    ... on %s {
      opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $first, after: $after) {
        pageInfo { %s }
        edges {
          %s
            id
            name
          }
        }
      }
    }
  }
}
`, cfg.NodeIDArgType, cfg.OpsFirstType, cfg.OpsAfterType, cfg.ProjectTypeName, pageInfoSelect, opsEdgeSelect)
	} else {
		if cfg.JiraProjectFieldName == "" || cfg.JiraProjectKeyArgName == "" || cfg.JiraProjectKeyArgType == "" {
			return "", errors.New("invalid config: jira strategy missing project lookup details")
		}
		opsQuery = fmt.Sprintf(`query JiraProjectOpsgenieTeamsPage(
  $cloudId: %s,
  $projectKey: %s,
  $first: %s,
  $after: %s
) {
  jira {
    project: %s(cloudId: $cloudId, %s: $projectKey) {
      opsgenieTeams: opsgenieTeamsAvailableToLinkWith(first: $first, after: $after) {
        pageInfo { %s }
        edges {
          %s
            id
            name
          }
        }
      }
    }
  }
}
`, cfg.CloudIDType, cfg.JiraProjectKeyArgType, cfg.OpsFirstType, cfg.OpsAfterType, cfg.JiraProjectFieldName, cfg.JiraProjectKeyArgName, pageInfoSelect, opsEdgeSelect)
	}

	lines := []string{
		"// Code generated by go/tools/generate_jira_project_models/main.go. DO NOT EDIT.",
		"package gen",
		"",
		"import (",
		`\t"encoding/json"`,
		`\t"errors"`,
		`\t"fmt"`,
		`\t"strings"`,
		")",
		"",
		"const (",
		fmt.Sprintf("\tPageInfoHasEndCursor = %t", cfg.PageInfoEndCursor),
		fmt.Sprintf("\tProjectsEdgeHasCursor = %t", cfg.ProjectsEdgeCursor),
		fmt.Sprintf("\tOpsgenieEdgeHasCursor = %t", cfg.OpsEdgeCursor),
		fmt.Sprintf("\tProjectHasID = %t", cfg.ProjectHasID),
		fmt.Sprintf("\tRefetchStrategy = %q", cfg.RefetchStrategy),
		")",
		"",
		fmt.Sprintf("const JiraProjectsPageQueryTemplate = %q", projectsTemplate),
		fmt.Sprintf("const JiraProjectOpsgenieTeamsPageQuery = %q", opsQuery),
		"",
		"func BuildJiraProjectsPageQuery(projectTypes []string) (string, error) {",
		"\tif len(projectTypes) == 0 {",
		`\t\treturn "", errors.New("projectTypes must be non-empty")`,
		"\t}",
		"\tclean := make([]string, 0, len(projectTypes))",
		"\tfor _, raw := range projectTypes {",
		"\t\tv := strings.ToUpper(strings.TrimSpace(raw))",
		"\t\tif v == \"\" {",
		`\t\t\treturn "", errors.New("empty project type")`,
		"\t\t}",
		"\t\tfor i, r := range v {",
		"\t\t\tif r == '_' {",
		"\t\t\t\tcontinue",
		"\t\t\t}",
		"\t\t\tif i == 0 {",
		"\t\t\t\tif r < 'A' || r > 'Z' {",
		`\t\t\t\t\treturn "", fmt.Errorf("invalid project type %q", raw)`,
		"\t\t\t\t}",
		"\t\t\t\tcontinue",
		"\t\t\t}",
		"\t\t\tif (r < 'A' || r > 'Z') && (r < '0' || r > '9') {",
		`\t\t\t\treturn "", fmt.Errorf("invalid project type %q", raw)`,
		"\t\t\t}",
		"\t\t}",
		"\t\tclean = append(clean, v)",
		"\t}",
		"\treturn strings.ReplaceAll(JiraProjectsPageQueryTemplate, \"__PROJECT_TYPES__\", strings.Join(clean, \", \")), nil",
		"}",
		"",
		"type PageInfo struct {",
		"\tHasNextPage bool `json:\"hasNextPage\"`",
		"\tEndCursor   *string `json:\"endCursor,omitempty\"`",
		"}",
		"",
		"type OpsgenieTeamNode struct {",
		"\tID   string `json:\"id\"`",
		"\tName string `json:\"name\"`",
		"}",
		"",
		"type OpsgenieTeamEdge struct {",
		"\tCursor *string `json:\"cursor,omitempty\"`",
		"\tNode   OpsgenieTeamNode `json:\"node\"`",
		"}",
		"",
		"type OpsgenieTeamsConnection struct {",
		"\tPageInfo PageInfo `json:\"pageInfo\"`",
		"\tEdges    []OpsgenieTeamEdge `json:\"edges\"`",
		"}",
		"",
		"type JiraProjectNode struct {",
		"\tID           *string `json:\"id,omitempty\"`",
		"\tKey          string `json:\"key\"`",
		"\tName         string `json:\"name\"`",
		"\tOpsgenieTeams OpsgenieTeamsConnection `json:\"opsgenieTeams\"`",
		"}",
		"",
		"type JiraProjectEdge struct {",
		"\tCursor *string `json:\"cursor,omitempty\"`",
		"\tNode   JiraProjectNode `json:\"node\"`",
		"}",
		"",
		"type JiraProjectsConnection struct {",
		"\tPageInfo PageInfo `json:\"pageInfo\"`",
		"\tEdges    []JiraProjectEdge `json:\"edges\"`",
		"}",
		"",
		"type JiraProjectsPageData struct {",
		"\tJira struct {",
		"\t\tProjects JiraProjectsConnection `json:\"projects\"`",
		"\t} `json:\"jira\"`",
		"}",
		"",
		"type ProjectOpsgenieTeamsByNodeData struct {",
		"\tProject *struct {",
		"\t\tOpsgenieTeams OpsgenieTeamsConnection `json:\"opsgenieTeams\"`",
		"\t} `json:\"project\"`",
		"}",
		"",
		"type ProjectOpsgenieTeamsByJiraData struct {",
		"\tJira struct {",
		"\t\tProject *struct {",
		"\t\t\tOpsgenieTeams OpsgenieTeamsConnection `json:\"opsgenieTeams\"`",
		"\t\t} `json:\"project\"`",
		"\t} `json:\"jira\"`",
		"}",
		"",
		"func DecodeJiraProjectsPage(data map[string]any) (*JiraProjectsPageData, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tvar out JiraProjectsPageData",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\treturn &out, nil",
		"}",
		"",
		"func DecodeProjectOpsgenieTeams(data map[string]any) (*OpsgenieTeamsConnection, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tif RefetchStrategy == \"node\" {",
		"\t\tvar out ProjectOpsgenieTeamsByNodeData",
		"\t\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\t\treturn nil, err",
		"\t\t}",
		"\t\tif out.Project == nil {",
		"\t\t\treturn nil, errors.New(\"missing project\")",
		"\t\t}",
		"\t\tteams := out.Project.OpsgenieTeams",
		"\t\treturn &teams, nil",
		"\t}",
		"\tvar out ProjectOpsgenieTeamsByJiraData",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tif out.Jira.Project == nil {",
		"\t\treturn nil, errors.New(\"missing jira.project\")",
		"\t}",
		"\tteams := out.Jira.Project.OpsgenieTeams",
		"\treturn &teams, nil",
		"}",
	}

	return strings.Join(lines, "\n"), nil
}
