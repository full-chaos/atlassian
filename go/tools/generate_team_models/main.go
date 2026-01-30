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
	"strings"
	"time"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

type teamField struct {
	Name     string
	GoName   string
	GoType   string
	Optional bool
}

type config struct {
	TeamNamespaceFieldName string
	TeamLookupFieldName    string
	TeamIDArgType          string
	TeamSiteIDArgType      string
	TeamTypeName           string
	TeamFields             []teamField

	TeamSearchFieldName         string
	TeamSearchOrgIDType         string
	TeamSearchSiteIDType        string
	TeamSearchQueryType         string
	TeamSearchFirstType         string
	TeamSearchAfterType         string
	TeamSearchConnectionType    string
	TeamSearchNodeType          string
	TeamSearchNodeTeamOptional  bool
	TeamSearchPageInfoHasCursor bool
}

func main() {
	repoRoot, err := findRepoRoot()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	tokenFile := strings.TrimSpace(os.Getenv("ATLASSIAN_OAUTH_TOKEN_FILE"))
	if tokenFile == "" {
		tokenFile = filepath.Join(repoRoot, "oauth_tokens.txt")
	}
	loadEnvFile(tokenFile)

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

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "teams_api.go")
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

func loadEnvFile(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		if strings.HasPrefix(trimmed, "export ") {
			trimmed = strings.TrimSpace(strings.TrimPrefix(trimmed, "export "))
		}
		eq := strings.Index(trimmed, "=")
		if eq <= 0 {
			continue
		}
		key := strings.TrimSpace(trimmed[:eq])
		val := strings.TrimSpace(trimmed[eq+1:])
		if key == "" {
			continue
		}
		if _, ok := os.LookupEnv(key); ok {
			continue
		}
		val = stripQuotes(val)
		_ = os.Setenv(key, val)
	}
}

func stripQuotes(raw string) string {
	if len(raw) >= 2 {
		first := raw[0]
		last := raw[len(raw)-1]
		if (first == '"' && last == '"') || (first == '\'' && last == '\'') {
			return raw[1 : len(raw)-1]
		}
	}
	return raw
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

func isNonNull(typeRef any) bool {
	m, ok := typeRef.(map[string]any)
	if !ok {
		return false
	}
	kind, _ := m["kind"].(string)
	return kind == "NON_NULL"
}

func baseTypeInfo(typeRef any) (name string, kind string) {
	cur, _ := typeRef.(map[string]any)
	for i := 0; i < 16 && cur != nil; i++ {
		kind, _ = cur["kind"].(string)
		if kind == "NON_NULL" || kind == "LIST" {
			next, _ := cur["ofType"].(map[string]any)
			cur = next
			continue
		}
		name, _ = cur["name"].(string)
		return name, kind
	}
	return "", ""
}

func goTypeForScalar(name string) (string, error) {
	switch name {
	case "ID", "String":
		return "string", nil
	case "Int":
		return "int", nil
	case "Float":
		return "float64", nil
	case "Boolean":
		return "bool", nil
	default:
		return "", fmt.Errorf("unsupported scalar %s", name)
	}
}

func goTypeForField(typeRef any, types map[string]map[string]any) (string, error) {
	name, kind := baseTypeInfo(typeRef)
	if name == "" {
		return "", errors.New("invalid typeRef")
	}
	switch kind {
	case "SCALAR":
		return goTypeForScalar(name)
	case "ENUM":
		return "string", nil
	default:
		if def, ok := types[name]; ok {
			if k, _ := def["kind"].(string); k == "ENUM" {
				return "string", nil
			}
		}
		return "", fmt.Errorf("unsupported field type %s (%s)", name, kind)
	}
}

func hasDirective(schema map[string]any, name string) bool {
	raw, _ := schema["directives"].([]any)
	for _, d := range raw {
		m, ok := d.(map[string]any)
		if !ok {
			continue
		}
		if m["name"] == name {
			return true
		}
	}
	return false
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

	teamNamespaceField := getField(queryDef, "team")
	teamQueryDef := queryDef
	teamNamespaceFieldName := ""
	if teamNamespaceField != nil {
		teamNamespaceFieldName = "team"
		teamQueryTypeName, _ := unwrapNamedType(teamNamespaceField["type"])
		teamQueryDef = types[teamQueryTypeName]
		if teamQueryDef == nil {
			return nil, fmt.Errorf("missing team query type definition: %s", teamQueryTypeName)
		}
	}

	teamLookupField := getField(teamQueryDef, "teamV2")
	if teamLookupField == nil {
		teamLookupField = getField(teamQueryDef, "team")
	}
	if teamLookupField == nil {
		return nil, errors.New("missing team lookup field (teamV2 or team)")
	}
	if getArg(teamLookupField, "id") == nil {
		return nil, errors.New("team lookup missing id arg")
	}
	if getArg(teamLookupField, "siteId") == nil {
		return nil, errors.New("team lookup missing siteId arg")
	}
	teamIDArgType, err := typeRefToGQL(getArg(teamLookupField, "id")["type"])
	if err != nil {
		return nil, err
	}
	teamSiteIDArgType, err := typeRefToGQL(getArg(teamLookupField, "siteId")["type"])
	if err != nil {
		return nil, err
	}

	teamTypeName, _ := unwrapNamedType(teamLookupField["type"])
	teamDef := types[teamTypeName]
	if teamDef == nil {
		return nil, fmt.Errorf("missing team type definition: %s", teamTypeName)
	}

	teamFieldNames := []string{"id", "displayName", "smallAvatarImageUrl", "state"}
	fields := make([]teamField, 0, len(teamFieldNames))
	var missing []string
	for _, name := range teamFieldNames {
		f := getField(teamDef, name)
		if f == nil {
			missing = append(missing, fmt.Sprintf("type %s.fields.%s", teamTypeName, name))
			continue
		}
		goType, err := goTypeForField(f["type"], types)
		if err != nil {
			return nil, err
		}
		fields = append(fields, teamField{
			Name:     name,
			GoName:   toGoName(name),
			GoType:   goType,
			Optional: !isNonNull(f["type"]),
		})
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required fields:\n- %s", strings.Join(missing, "\n- "))
	}

	teamSearchField := getField(teamQueryDef, "teamSearchV2")
	if teamSearchField == nil {
		return nil, errors.New("missing teamSearchV2 field")
	}
	if getArg(teamSearchField, "organizationId") == nil {
		return nil, errors.New("teamSearchV2 missing organizationId arg")
	}
	if getArg(teamSearchField, "siteId") == nil {
		return nil, errors.New("teamSearchV2 missing siteId arg")
	}
	if getArg(teamSearchField, "filter") == nil {
		return nil, errors.New("teamSearchV2 missing filter arg")
	}
	if getArg(teamSearchField, "first") == nil {
		return nil, errors.New("teamSearchV2 missing first arg")
	}

	teamSearchOrgIDType, err := typeRefToGQL(getArg(teamSearchField, "organizationId")["type"])
	if err != nil {
		return nil, err
	}
	teamSearchSiteIDType, err := typeRefToGQL(getArg(teamSearchField, "siteId")["type"])
	if err != nil {
		return nil, err
	}
	teamSearchFirstType, err := typeRefToGQL(getArg(teamSearchField, "first")["type"])
	if err != nil {
		return nil, err
	}
	teamSearchAfterType := ""
	if afterArg := getArg(teamSearchField, "after"); afterArg != nil {
		if gqlType, err := typeRefToGQL(afterArg["type"]); err == nil {
			teamSearchAfterType = gqlType
		} else {
			return nil, err
		}
	}

	filterArg := getArg(teamSearchField, "filter")
	filterTypeName, _ := unwrapNamedType(filterArg["type"])
	filterDef := types[filterTypeName]
	if filterDef == nil {
		return nil, fmt.Errorf("missing teamSearchV2 filter input type %s", filterTypeName)
	}
	filterQueryField := getInputField(filterDef, "query")
	if filterQueryField == nil {
		return nil, fmt.Errorf("missing input field %s.query", filterTypeName)
	}
	teamSearchQueryType, err := typeRefToGQL(filterQueryField["type"])
	if err != nil {
		return nil, err
	}

	teamSearchConnTypeName, _ := unwrapNamedType(teamSearchField["type"])
	teamSearchConnDef := types[teamSearchConnTypeName]
	if teamSearchConnDef == nil {
		return nil, fmt.Errorf("missing teamSearchV2 connection type %s", teamSearchConnTypeName)
	}
	nodesField := getField(teamSearchConnDef, "nodes")
	pageInfoField := getField(teamSearchConnDef, "pageInfo")
	if nodesField == nil {
		return nil, fmt.Errorf("missing teamSearchV2 nodes field on %s", teamSearchConnTypeName)
	}
	if pageInfoField == nil {
		return nil, fmt.Errorf("missing teamSearchV2 pageInfo field on %s", teamSearchConnTypeName)
	}

	teamSearchNodeTypeName, _ := unwrapNamedType(nodesField["type"])
	teamSearchNodeDef := types[teamSearchNodeTypeName]
	if teamSearchNodeDef == nil {
		return nil, fmt.Errorf("missing teamSearchV2 node type %s", teamSearchNodeTypeName)
	}
	nodeTeamField := getField(teamSearchNodeDef, "team")
	if nodeTeamField == nil {
		return nil, fmt.Errorf("missing teamSearchV2 node.team field on %s", teamSearchNodeTypeName)
	}
	nodeTeamTypeName, _ := unwrapNamedType(nodeTeamField["type"])
	if nodeTeamTypeName != teamTypeName {
		return nil, fmt.Errorf("teamSearchV2 node.team type %s does not match team type %s", nodeTeamTypeName, teamTypeName)
	}

	pageInfoTypeName, _ := unwrapNamedType(pageInfoField["type"])
	pageInfoDef := types[pageInfoTypeName]
	if pageInfoDef == nil {
		return nil, fmt.Errorf("missing PageInfo type definition: %s", pageInfoTypeName)
	}
	if getField(pageInfoDef, "hasNextPage") == nil {
		return nil, fmt.Errorf("missing PageInfo.hasNextPage on %s", pageInfoTypeName)
	}
	pageInfoHasCursor := getField(pageInfoDef, "endCursor") != nil

	if !hasDirective(schema, "optIn") {
		return nil, errors.New("schema missing optIn directive")
	}

	return &config{
		TeamNamespaceFieldName:      teamNamespaceFieldName,
		TeamLookupFieldName:         teamLookupField["name"].(string),
		TeamIDArgType:               teamIDArgType,
		TeamSiteIDArgType:           teamSiteIDArgType,
		TeamTypeName:                teamTypeName,
		TeamFields:                  fields,
		TeamSearchFieldName:         "teamSearchV2",
		TeamSearchOrgIDType:         teamSearchOrgIDType,
		TeamSearchSiteIDType:        teamSearchSiteIDType,
		TeamSearchQueryType:         teamSearchQueryType,
		TeamSearchFirstType:         teamSearchFirstType,
		TeamSearchAfterType:         teamSearchAfterType,
		TeamSearchConnectionType:    teamSearchConnTypeName,
		TeamSearchNodeType:          teamSearchNodeTypeName,
		TeamSearchNodeTeamOptional:  !isNonNull(nodeTeamField["type"]),
		TeamSearchPageInfoHasCursor: pageInfoHasCursor,
	}, nil
}

func renderGo(cfg *config) (string, error) {
	var teamFields []string
	for _, f := range cfg.TeamFields {
		teamFields = append(teamFields, f.Name)
	}
	teamSelect := strings.Join(teamFields, "\n      ")
	teamQuery := fmt.Sprintf(`query TeamById(
  $teamId: %s,
  $siteId: %s
) {
  %s
}
`, cfg.TeamIDArgType, cfg.TeamSiteIDArgType, renderTeamLookupRoot(cfg.TeamNamespaceFieldName, cfg.TeamLookupFieldName, teamSelect))

	pageInfoSelect := "hasNextPage"
	if cfg.TeamSearchPageInfoHasCursor {
		pageInfoSelect += " endCursor"
	}
	teamSearchArgs := []string{
		fmt.Sprintf("organizationId: $organizationId"),
		fmt.Sprintf("siteId: $siteId"),
		fmt.Sprintf("filter: { query: $query }"),
		fmt.Sprintf("first: $first"),
	}
	if cfg.TeamSearchAfterType != "" {
		teamSearchArgs = append(teamSearchArgs, "after: $after")
	}
	teamSearchQuery := fmt.Sprintf(`query TeamSearchV2(
  $organizationId: %s,
  $siteId: %s,
  $query: %s,
  $first: %s%s
) {
  %s
}
`, cfg.TeamSearchOrgIDType, cfg.TeamSearchSiteIDType, cfg.TeamSearchQueryType, cfg.TeamSearchFirstType, renderAfterVar(cfg.TeamSearchAfterType), renderTeamSearchRoot(cfg.TeamNamespaceFieldName, cfg.TeamSearchFieldName, strings.Join(teamSearchArgs, ",\n      "), pageInfoSelect, teamSelect))

	lines := []string{
		"// Code generated by go/tools/generate_team_models/main.go. DO NOT EDIT.",
		"package gen",
		"",
		"import (",
		"\t\"encoding/json\"",
		"\t\"errors\"",
		"\t\"strings\"",
		")",
		"",
		"const TeamARIFormatPrefix = \"ari:cloud:identity::team/\"",
		"",
		"func NormalizeTeamID(raw string) string {",
		"\ttrimmed := strings.TrimSpace(raw)",
		"\tif trimmed == \"\" {",
		"\t\treturn trimmed",
		"\t}",
		"\tif strings.HasPrefix(trimmed, TeamARIFormatPrefix) {",
		"\t\treturn trimmed",
		"\t}",
		"\treturn TeamARIFormatPrefix + trimmed",
		"}",
		"",
		"const (",
		fmt.Sprintf("\tTeamSearchPageInfoHasEndCursor = %t", cfg.TeamSearchPageInfoHasCursor),
		")",
		"",
		"const TeamByIdQuery = `" + teamQuery + "`",
		"",
		"const TeamSearchV2Query = `" + teamSearchQuery + "`",
		"",
		"type TeamNode struct {",
	}
	for _, field := range cfg.TeamFields {
		goType := field.GoType
		if field.Optional {
			goType = "*" + goType
		}
		lines = append(lines, fmt.Sprintf("\t%s %s `json:\"%s\"`", field.GoName, goType, field.Name))
	}
	lines = append(lines,
		"}",
		"",
		"type TeamSearchResultNode struct {",
	)
	teamFieldType := "TeamNode"
	if cfg.TeamSearchNodeTeamOptional {
		teamFieldType = "*TeamNode"
	}
	lines = append(lines,
		fmt.Sprintf("\tTeam %s `json:\"team\"`", teamFieldType),
		"}",
		"",
		"type TeamPageInfo struct {",
		"\tHasNextPage bool `json:\"hasNextPage\"`",
		"\tEndCursor   *string `json:\"endCursor,omitempty\"`",
		"}",
		"",
		"type TeamSearchConnection struct {",
		"\tPageInfo TeamPageInfo `json:\"pageInfo\"`",
		"\tNodes    []TeamSearchResultNode `json:\"nodes\"`",
		"}",
		"",
		"type TeamByIdData struct {",
		"\tTeam *struct {",
		fmt.Sprintf("\t\tTeam *TeamNode `json:\"%s\"`", cfg.TeamLookupFieldName),
		"\t} `json:\"team\"`",
		"}",
		"",
		"type TeamSearchV2Data struct {",
		"\tTeam *struct {",
		fmt.Sprintf("\t\tSearch *TeamSearchConnection `json:\"%s\"`", cfg.TeamSearchFieldName),
		"\t} `json:\"team\"`",
		"}",
		"",
		"func DecodeTeam(data map[string]any) (*TeamNode, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tvar out TeamByIdData",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tif out.Team == nil {",
		"\t\treturn nil, errors.New(\"missing team\")",
		"\t}",
		"\tif out.Team.Team == nil {",
		"\t\treturn nil, errors.New(\"missing team node\")",
		"\t}",
		"\treturn out.Team.Team, nil",
		"}",
		"",
		"func DecodeTeamSearchV2(data map[string]any) (*TeamSearchConnection, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tvar out TeamSearchV2Data",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tif out.Team == nil {",
		"\t\treturn nil, errors.New(\"missing team\")",
		"\t}",
		"\tif out.Team.Search == nil {",
		"\t\treturn nil, errors.New(\"missing teamSearchV2\")",
		"\t}",
		"\tconn := out.Team.Search",
		"\treturn conn, nil",
		"}",
	)

	return strings.Join(lines, "\n"), nil
}

func renderTeamLookupRoot(namespace, lookupField, selection string) string {
	if namespace == "" {
		return fmt.Sprintf("%s(id: $teamId, siteId: $siteId) {\n      %s\n    }", lookupField, selection)
	}
	return fmt.Sprintf("%s {\n    %s(id: $teamId, siteId: $siteId) {\n      %s\n    }\n  }", namespace, lookupField, selection)
}

func renderAfterVar(afterType string) string {
	if afterType == "" {
		return ""
	}
	return ",\n  $after: " + afterType
}

func renderTeamSearchRoot(namespace, fieldName, args, pageInfoSelect, teamSelect string) string {
	if namespace == "" {
		return fmt.Sprintf("%s(\n      %s\n    ) @optIn(to: \"Team-search-v2\") {\n      pageInfo { %s }\n      nodes {\n        team {\n          %s\n        }\n      }\n    }", fieldName, args, pageInfoSelect, teamSelect)
	}
	return fmt.Sprintf("%s {\n    %s(\n      %s\n    ) @optIn(to: \"Team-search-v2\") {\n      pageInfo { %s }\n      nodes {\n        team {\n          %s\n        }\n      }\n    }\n  }", namespace, fieldName, args, pageInfoSelect, teamSelect)
}

func toGoName(name string) string {
	if name == "" {
		return ""
	}
	var out []rune
	for i, r := range name {
		if i == 0 {
			out = append(out, []rune(strings.ToUpper(string(r)))...)
			continue
		}
		if r == '_' {
			continue
		}
		if r >= 'A' && r <= 'Z' {
			out = append(out, r)
			continue
		}
		out = append(out, r)
	}
	s := string(out)
	replacements := []struct{ from, to string }{
		{"Id", "ID"},
		{"Url", "URL"},
	}
	for _, r := range replacements {
		s = strings.ReplaceAll(s, r.from, r.to)
	}
	return s
}
