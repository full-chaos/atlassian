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
	"regexp"
	"runtime"
	"strings"
	"time"

	"atlassian/atlassian"
	"atlassian/atlassian/graph"
)

var teamworkGraphQueries = []string{
	"teamworkGraph_teamActiveProjects",
	"teamworkGraph_teamUsers",
	"teamworkGraph_userTeams",
	"teamworkGraph_userManager",
	"teamworkGraph_userDirectReports",
}

type queryConfig struct {
	Name         string
	IDArgName    string
	IDArgType    string
	FirstArgType string
	AfterArgType string
	OptInTarget  string
}

type dataType struct {
	TypeName string
	Fields   []string
}

type config struct {
	ConnectionTypeName string
	EdgeTypeName       string
	NodeTypeName       string
	ColumnTypeName     string
	ValueUnionTypeName string
	PageInfoTypeName   string

	PageInfoHasEndCursor   bool
	PageInfoHasStartCursor bool
	PageInfoHasPrevious    bool
	EdgeHasCursor          bool
	ConnectionVersionField string

	QueryTypeName  string
	OptInTarget    string
	OptInDirective string

	AriNodeTypeName         string
	NodeListTypeName        string
	PathTypeName            string
	StringObjectTypeName    string
	IntObjectTypeName       string
	FloatObjectTypeName     string
	BooleanObjectTypeName   string
	TimestampObjectTypeName string

	DataTypes []dataType
	Queries   []queryConfig
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

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "teamwork_graph_api.go")
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
		return atlassian.BearerAuth{TokenGetter: func() (string, error) { return token, nil }}
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

func possibleTypeDefs(types map[string]map[string]any, typeDef map[string]any) []map[string]any {
	raw, _ := typeDef["possibleTypes"].([]any)
	var out []map[string]any
	for _, item := range raw {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		if name == "" {
			continue
		}
		if def, ok := types[name]; ok {
			out = append(out, def)
		}
	}
	return out
}

var optInRe = regexp.MustCompile(`@optIn\(to: \"([^\"]+)\"\)`)

func extractOptInTarget(fieldDef map[string]any, name string) (string, error) {
	desc, _ := fieldDef["description"].(string)
	if desc == "" {
		return "", fmt.Errorf("missing description for %s to extract optIn target", name)
	}
	match := optInRe.FindStringSubmatch(desc)
	if len(match) < 2 {
		return "", fmt.Errorf("missing @optIn target in %s description", name)
	}
	return match[1], nil
}

func discoverConfig(schema map[string]any) (*config, error) {
	types, err := typesMap(schema)
	if err != nil {
		return nil, err
	}
	if !hasDirective(schema, "optIn") {
		return nil, errors.New("schema missing optIn directive")
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

	fieldsRaw, _ := queryDef["fields"].([]any)
	fieldMap := map[string]map[string]any{}
	for _, f := range fieldsRaw {
		m, ok := f.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		if name != "" {
			fieldMap[name] = m
		}
	}

	var queries []queryConfig
	optInTargets := map[string]struct{}{}
	connectionTypeName := ""

	for _, name := range teamworkGraphQueries {
		fieldDef := fieldMap[name]
		if fieldDef == nil {
			return nil, fmt.Errorf("missing required teamworkGraph query field: %s", name)
		}
		optInTarget, err := extractOptInTarget(fieldDef, name)
		if err != nil {
			return nil, err
		}
		optInTargets[optInTarget] = struct{}{}

		idArg := getArg(fieldDef, "teamId")
		idArgName := "teamId"
		if idArg == nil {
			idArg = getArg(fieldDef, "userId")
			idArgName = "userId"
		}
		if idArg == nil {
			return nil, fmt.Errorf("missing teamId/userId arg on %s", name)
		}
		idArgType, err := typeRefToGQL(idArg["type"])
		if err != nil {
			return nil, err
		}

		firstArg := getArg(fieldDef, "first")
		afterArg := getArg(fieldDef, "after")
		firstArgType := ""
		afterArgType := ""
		if firstArg != nil {
			firstArgType, err = typeRefToGQL(firstArg["type"])
			if err != nil {
				return nil, err
			}
		}
		if afterArg != nil {
			afterArgType, err = typeRefToGQL(afterArg["type"])
			if err != nil {
				return nil, err
			}
		}

		returnTypeName, _ := unwrapNamedType(fieldDef["type"])
		if returnTypeName == "" {
			return nil, fmt.Errorf("unable to resolve return type for %s", name)
		}
		if connectionTypeName == "" {
			connectionTypeName = returnTypeName
		} else if connectionTypeName != returnTypeName {
			return nil, fmt.Errorf("mismatched return type for %s", name)
		}

		queries = append(queries, queryConfig{
			Name:         name,
			IDArgName:    idArgName,
			IDArgType:    idArgType,
			FirstArgType: firstArgType,
			AfterArgType: afterArgType,
			OptInTarget:  optInTarget,
		})
	}

	if len(optInTargets) != 1 {
		return nil, errors.New("teamworkGraph queries did not agree on a single optIn target")
	}
	optInTarget := ""
	for key := range optInTargets {
		optInTarget = key
	}

	connDef := types[connectionTypeName]
	if connDef == nil {
		return nil, fmt.Errorf("missing connection type definition: %s", connectionTypeName)
	}
	pageInfoField := getField(connDef, "pageInfo")
	if pageInfoField == nil {
		return nil, fmt.Errorf("missing pageInfo on %s", connectionTypeName)
	}
	edgesField := getField(connDef, "edges")
	if edgesField == nil {
		return nil, fmt.Errorf("missing edges on %s", connectionTypeName)
	}
	versionField := getField(connDef, "version")
	if versionField == nil {
		return nil, fmt.Errorf("missing version on %s", connectionTypeName)
	}
	pageInfoTypeName, _ := unwrapNamedType(pageInfoField["type"])
	pageInfoDef := types[pageInfoTypeName]
	if pageInfoDef == nil {
		return nil, fmt.Errorf("missing PageInfo type %s", pageInfoTypeName)
	}
	if getField(pageInfoDef, "hasNextPage") == nil {
		return nil, fmt.Errorf("missing PageInfo.hasNextPage on %s", pageInfoTypeName)
	}

	edgeTypeName, _ := unwrapNamedType(edgesField["type"])
	edgeDef := types[edgeTypeName]
	if edgeDef == nil {
		return nil, fmt.Errorf("missing edge type %s", edgeTypeName)
	}
	edgeHasCursor := getField(edgeDef, "cursor") != nil
	nodeField := getField(edgeDef, "node")
	if nodeField == nil {
		return nil, fmt.Errorf("missing node on %s", edgeTypeName)
	}
	nodeTypeName, _ := unwrapNamedType(nodeField["type"])
	nodeDef := types[nodeTypeName]
	if nodeDef == nil {
		return nil, fmt.Errorf("missing node type %s", nodeTypeName)
	}
	columnsField := getField(nodeDef, "columns")
	if columnsField == nil {
		return nil, fmt.Errorf("missing columns on %s", nodeTypeName)
	}
	columnTypeName, _ := unwrapNamedType(columnsField["type"])
	columnDef := types[columnTypeName]
	if columnDef == nil {
		return nil, fmt.Errorf("missing column type %s", columnTypeName)
	}
	if getField(columnDef, "key") == nil || getField(columnDef, "value") == nil {
		return nil, fmt.Errorf("missing column key/value on %s", columnTypeName)
	}
	valueField := getField(columnDef, "value")
	valueUnionName, valueUnionKind := unwrapNamedType(valueField["type"])
	if valueUnionName == "" || (valueUnionKind != "UNION" && valueUnionKind != "INTERFACE") {
		return nil, errors.New("column value is not a union type")
	}
	valueUnionDef := types[valueUnionName]
	if valueUnionDef == nil {
		return nil, fmt.Errorf("missing value union type %s", valueUnionName)
	}
	possible := possibleTypeDefs(types, valueUnionDef)
	possibleNames := map[string]struct{}{}
	for _, p := range possible {
		if name, _ := p["name"].(string); name != "" {
			possibleNames[name] = struct{}{}
		}
	}
	requirePossible := func(name string) (string, error) {
		if _, ok := possibleNames[name]; !ok {
			return "", fmt.Errorf("missing %s in %s possible types", name, valueUnionName)
		}
		return name, nil
	}
	ariNodeType, err := requirePossible("GraphStoreCypherQueryV2AriNode")
	if err != nil {
		return nil, err
	}
	nodeListType, err := requirePossible("GraphStoreCypherQueryV2NodeList")
	if err != nil {
		return nil, err
	}
	pathType, err := requirePossible("GraphStoreCypherQueryV2Path")
	if err != nil {
		return nil, err
	}
	stringObjType, err := requirePossible("GraphStoreCypherQueryV2StringObject")
	if err != nil {
		return nil, err
	}
	intObjType, err := requirePossible("GraphStoreCypherQueryV2IntObject")
	if err != nil {
		return nil, err
	}
	floatObjType, err := requirePossible("GraphStoreCypherQueryV2FloatObject")
	if err != nil {
		return nil, err
	}
	boolObjType, err := requirePossible("GraphStoreCypherQueryV2BooleanObject")
	if err != nil {
		return nil, err
	}
	tsObjType, err := requirePossible("GraphStoreCypherQueryV2TimestampObject")
	if err != nil {
		return nil, err
	}

	pageInfoHasEnd := getField(pageInfoDef, "endCursor") != nil
	pageInfoHasStart := getField(pageInfoDef, "startCursor") != nil
	pageInfoHasPrev := getField(pageInfoDef, "hasPreviousPage") != nil

	dataTypes := []dataType{}
	dataCandidates := []string{"TeamV2", "AtlassianAccountUser", "JiraProject", "TownsquareProject"}
	ariNodeDef := types[ariNodeType]
	if ariNodeDef == nil {
		return nil, fmt.Errorf("missing ari node type %s", ariNodeType)
	}
	dataField := getField(ariNodeDef, "data")
	if dataField == nil {
		return nil, fmt.Errorf("missing data field on %s", ariNodeType)
	}
	dataUnionName, dataUnionKind := unwrapNamedType(dataField["type"])
	if dataUnionName == "" || (dataUnionKind != "UNION" && dataUnionKind != "INTERFACE") {
		return nil, errors.New("ari node data is not a union type")
	}
	dataUnionDef := types[dataUnionName]
	if dataUnionDef == nil {
		return nil, fmt.Errorf("missing data union type %s", dataUnionName)
	}
	dataPossible := possibleTypeDefs(types, dataUnionDef)
	dataPossibleMap := map[string]map[string]any{}
	for _, d := range dataPossible {
		if name, _ := d["name"].(string); name != "" {
			dataPossibleMap[name] = d
		}
	}
	for _, candidate := range dataCandidates {
		def := dataPossibleMap[candidate]
		if def == nil {
			continue
		}
		fields := []string{"id", "accountId", "name", "displayName", "key"}
		var selectFields []string
		for _, field := range fields {
			if getField(def, field) != nil {
				selectFields = append(selectFields, field)
			}
		}
		if len(selectFields) == 0 {
			continue
		}
		dataTypes = append(dataTypes, dataType{TypeName: candidate, Fields: selectFields})
	}

	return &config{
		ConnectionTypeName:      connectionTypeName,
		EdgeTypeName:            edgeTypeName,
		NodeTypeName:            nodeTypeName,
		ColumnTypeName:          columnTypeName,
		ValueUnionTypeName:      valueUnionName,
		PageInfoTypeName:        pageInfoTypeName,
		PageInfoHasEndCursor:    pageInfoHasEnd,
		PageInfoHasStartCursor:  pageInfoHasStart,
		PageInfoHasPrevious:     pageInfoHasPrev,
		EdgeHasCursor:           edgeHasCursor,
		ConnectionVersionField:  versionField["name"].(string),
		QueryTypeName:           queryName,
		OptInTarget:             optInTarget,
		OptInDirective:          "optIn",
		AriNodeTypeName:         ariNodeType,
		NodeListTypeName:        nodeListType,
		PathTypeName:            pathType,
		StringObjectTypeName:    stringObjType,
		IntObjectTypeName:       intObjType,
		FloatObjectTypeName:     floatObjType,
		BooleanObjectTypeName:   boolObjType,
		TimestampObjectTypeName: tsObjType,
		DataTypes:               dataTypes,
		Queries:                 queries,
	}, nil
}

func renderGo(cfg *config) (string, error) {
	dataSelectLines := []string{"__typename"}
	for _, data := range cfg.DataTypes {
		if len(data.Fields) == 0 {
			continue
		}
		dataSelectLines = append(dataSelectLines, fmt.Sprintf("... on %s { %s }", data.TypeName, strings.Join(data.Fields, " ")))
	}
	dataSelect := strings.Join(dataSelectLines, "\n        ")

	valueSelect := strings.Join([]string{
		"__typename",
		fmt.Sprintf("... on %s { id\n      data {\n        %s\n      }\n    }", cfg.AriNodeTypeName, dataSelect),
		fmt.Sprintf("... on %s { nodes { id\n      data {\n        %s\n      }\n    } }", cfg.NodeListTypeName, dataSelect),
		fmt.Sprintf("... on %s { value }", cfg.StringObjectTypeName),
		fmt.Sprintf("... on %s { value }", cfg.IntObjectTypeName),
		fmt.Sprintf("... on %s { value }", cfg.FloatObjectTypeName),
		fmt.Sprintf("... on %s { value }", cfg.BooleanObjectTypeName),
		fmt.Sprintf("... on %s { value }", cfg.TimestampObjectTypeName),
		fmt.Sprintf("... on %s { elements }", cfg.PathTypeName),
	}, "\n    ")

	pageInfoFields := []string{"hasNextPage"}
	if cfg.PageInfoHasEndCursor {
		pageInfoFields = append(pageInfoFields, "endCursor")
	}
	if cfg.PageInfoHasStartCursor {
		pageInfoFields = append(pageInfoFields, "startCursor")
	}
	if cfg.PageInfoHasPrevious {
		pageInfoFields = append(pageInfoFields, "hasPreviousPage")
	}
	pageInfoSelect := strings.Join(pageInfoFields, " ")

	var queryConstants []string
	for _, query := range cfg.Queries {
		varLines := []string{fmt.Sprintf("  $%s: %s,", query.IDArgName, query.IDArgType)}
		argLines := []string{fmt.Sprintf("%s: $%s", query.IDArgName, query.IDArgName)}
		if query.FirstArgType != "" {
			varLines = append(varLines, fmt.Sprintf("  $first: %s,", query.FirstArgType))
			argLines = append(argLines, "first: $first")
		}
		if query.AfterArgType != "" {
			varLines = append(varLines, fmt.Sprintf("  $after: %s,", query.AfterArgType))
			argLines = append(argLines, "after: $after")
		}
		varBlock := strings.Join(varLines, "\n")
		argsBlock := strings.Join(argLines, ",\n      ")
		queryName := toPublicName(strings.ReplaceAll(query.Name, "teamworkGraph_", ""))
		queryText := fmt.Sprintf(`query TeamworkGraph%s(
%s
) {
  %s(
      %s
    ) @optIn(to: "%s") {
      %s
      pageInfo { %s }
      edges {
        %s
        node {
          columns {
            key
            value {
    %s
            }
          }
        }
      }
    }
}
`, queryName, varBlock, query.Name, argsBlock, query.OptInTarget, cfg.ConnectionVersionField, pageInfoSelect, cursorSelection(cfg.EdgeHasCursor), valueSelect)
		constName := strings.ToUpper(query.Name)
		queryConstants = append(queryConstants, fmt.Sprintf("%s = `%s`", constName, queryText))
	}

	lines := []string{
		"// Code generated by go/tools/generate_teamwork_graph_models/main.go. DO NOT EDIT.",
		"package gen",
		"",
		"import (",
		"\t\"encoding/json\"",
		"\t\"errors\"",
		"\t\"strings\"",
		")",
		"",
		"// Teamwork Graph APIs are EAP/experimental. They require @optIn(to: \"" + cfg.OptInTarget + "\")",
		"// and are not available for OAuth-authenticated requests.",
		"// Manager relationship queries require the X-Force-Dynamo: true header.",
		"",
		fmt.Sprintf("const TeamworkGraphOptIn = \"%s\"", cfg.OptInTarget),
		"",
		fmt.Sprintf("const (\n%s\n)", strings.Join(queryConstants, "\n")),
		"",
		"const (",
		fmt.Sprintf("\tvalueTypeAriNode = \"%s\"", cfg.AriNodeTypeName),
		fmt.Sprintf("\tvalueTypeNodeList = \"%s\"", cfg.NodeListTypeName),
		fmt.Sprintf("\tvalueTypePath = \"%s\"", cfg.PathTypeName),
		fmt.Sprintf("\tvalueTypeString = \"%s\"", cfg.StringObjectTypeName),
		fmt.Sprintf("\tvalueTypeInt = \"%s\"", cfg.IntObjectTypeName),
		fmt.Sprintf("\tvalueTypeFloat = \"%s\"", cfg.FloatObjectTypeName),
		fmt.Sprintf("\tvalueTypeBool = \"%s\"", cfg.BooleanObjectTypeName),
		fmt.Sprintf("\tvalueTypeTimestamp = \"%s\"", cfg.TimestampObjectTypeName),
		")",
		"type GraphStoreCypherQueryV2AriNodeData struct {",
		"\tTypename string `json:\"__typename\"`",
		"\tID *string `json:\"id,omitempty\"`",
		"\tAccountID *string `json:\"accountId,omitempty\"`",
		"\tName *string `json:\"name,omitempty\"`",
		"\tDisplayName *string `json:\"displayName,omitempty\"`",
		"\tKey *string `json:\"key,omitempty\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2AriNode struct {",
		"\tID string `json:\"id\"`",
		"\tData *GraphStoreCypherQueryV2AriNodeData `json:\"data,omitempty\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2NodeList struct {",
		"\tNodes []GraphStoreCypherQueryV2AriNode `json:\"nodes\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2Path struct {",
		"\tElements []string `json:\"elements\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2StringObject struct {",
		"\tValue string `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2IntObject struct {",
		"\tValue int `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2FloatObject struct {",
		"\tValue float64 `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2BooleanObject struct {",
		"\tValue bool `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2TimestampObject struct {",
		"\tValue int64 `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2Value struct {",
		"\tTypename string `json:\"__typename\"`",
		"\tAriNode *GraphStoreCypherQueryV2AriNode",
		"\tNodeList *GraphStoreCypherQueryV2NodeList",
		"\tPath *GraphStoreCypherQueryV2Path",
		"\tStringObject *GraphStoreCypherQueryV2StringObject",
		"\tIntObject *GraphStoreCypherQueryV2IntObject",
		"\tFloatObject *GraphStoreCypherQueryV2FloatObject",
		"\tBooleanObject *GraphStoreCypherQueryV2BooleanObject",
		"\tTimestampObject *GraphStoreCypherQueryV2TimestampObject",
		"}",
		"",
		"func (v *GraphStoreCypherQueryV2Value) UnmarshalJSON(data []byte) error {",
		"\tif string(data) == \"null\" {",
		"\t\treturn nil",
		"\t}",
		"\tvar probe struct { Typename string `json:\"__typename\"` }",
		"\tif err := json.Unmarshal(data, &probe); err != nil {",
		"\t\treturn err",
		"\t}",
		"\tv.Typename = probe.Typename",
		"\tswitch probe.Typename {",
		"\tcase valueTypeAriNode:",
		"\t\tvar obj GraphStoreCypherQueryV2AriNode",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.AriNode = &obj",
		"\tcase valueTypeNodeList:",
		"\t\tvar obj GraphStoreCypherQueryV2NodeList",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.NodeList = &obj",
		"\tcase valueTypePath:",
		"\t\tvar obj GraphStoreCypherQueryV2Path",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.Path = &obj",
		"\tcase valueTypeString:",
		"\t\tvar obj GraphStoreCypherQueryV2StringObject",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.StringObject = &obj",
		"\tcase valueTypeInt:",
		"\t\tvar obj GraphStoreCypherQueryV2IntObject",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.IntObject = &obj",
		"\tcase valueTypeFloat:",
		"\t\tvar obj GraphStoreCypherQueryV2FloatObject",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.FloatObject = &obj",
		"\tcase valueTypeBool:",
		"\t\tvar obj GraphStoreCypherQueryV2BooleanObject",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.BooleanObject = &obj",
		"\tcase valueTypeTimestamp:",
		"\t\tvar obj GraphStoreCypherQueryV2TimestampObject",
		"\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tv.TimestampObject = &obj",
		"\tdefault:",
		"\t\tvar probeMap map[string]any",
		"\t\tif err := json.Unmarshal(data, &probeMap); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tif _, ok := probeMap[\"id\"]; ok {",
		"\t\t\tvar obj GraphStoreCypherQueryV2AriNode",
		"\t\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\t\treturn err",
		"\t\t\t}",
		"\t\t\tv.AriNode = &obj",
		"\t\t\treturn nil",
		"\t\t}",
		"\t\tif _, ok := probeMap[\"nodes\"]; ok {",
		"\t\t\tvar obj GraphStoreCypherQueryV2NodeList",
		"\t\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\t\treturn err",
		"\t\t\t}",
		"\t\t\tv.NodeList = &obj",
		"\t\t\treturn nil",
		"\t\t}",
		"\t\tif _, ok := probeMap[\"elements\"]; ok {",
		"\t\t\tvar obj GraphStoreCypherQueryV2Path",
		"\t\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\t\treturn err",
		"\t\t\t}",
		"\t\t\tv.Path = &obj",
		"\t\t\treturn nil",
		"\t\t}",
		"\t\tif _, ok := probeMap[\"value\"]; ok {",
		"\t\t\tvar obj GraphStoreCypherQueryV2StringObject",
		"\t\t\tif err := json.Unmarshal(data, &obj); err != nil {",
		"\t\t\t\treturn err",
		"\t\t\t}",
		"\t\t\tv.StringObject = &obj",
		"\t\t\treturn nil",
		"\t\t}",
		"\t}\n\treturn nil",
		"}",
		"",
		"type GraphStoreCypherQueryV2Column struct {",
		"\tKey string `json:\"key\"`",
		"\tValue *GraphStoreCypherQueryV2Value `json:\"value\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2Node struct {",
		"\tColumns []GraphStoreCypherQueryV2Column `json:\"columns\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2Edge struct {",
		"\tCursor *string `json:\"cursor,omitempty\"`",
		"\tNode GraphStoreCypherQueryV2Node `json:\"node\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2PageInfo struct {",
		"\tHasNextPage bool `json:\"hasNextPage\"`",
		"\tHasPreviousPage *bool `json:\"hasPreviousPage,omitempty\"`",
		"\tStartCursor *string `json:\"startCursor,omitempty\"`",
		"\tEndCursor *string `json:\"endCursor,omitempty\"`",
		"}",
		"",
		"type GraphStoreCypherQueryV2Connection struct {",
		"\tPageInfo GraphStoreCypherQueryV2PageInfo `json:\"pageInfo\"`",
		"\tEdges []GraphStoreCypherQueryV2Edge `json:\"edges\"`",
		fmt.Sprintf("\tVersion string `json:\"%s\"`", cfg.ConnectionVersionField),
		"}",
	}

	for _, query := range cfg.Queries {
		name := query.Name
		structName := toPublicName(strings.ReplaceAll(name, "teamworkGraph_", ""))
		lines = append(lines,
			"",
			fmt.Sprintf("type %sData struct {", structName),
			fmt.Sprintf("\tResult *GraphStoreCypherQueryV2Connection `json:\"%s\"`", name),
			"}",
			"",
			fmt.Sprintf("func Decode%s(data map[string]any) (*GraphStoreCypherQueryV2Connection, error) {", structName),
			"\tb, err := json.Marshal(data)",
			"\tif err != nil {",
			"\t\treturn nil, err",
			"\t}",
			fmt.Sprintf("\tvar out %sData", structName),
			"\tif err := json.Unmarshal(b, &out); err != nil {",
			"\t\treturn nil, err",
			"\t}",
			"\tif out.Result == nil {",
			fmt.Sprintf("\t\treturn nil, errors.New(\"missing %s\")", name),
			"\t}",
			"\treturn out.Result, nil",
			"}",
		)
	}

	return strings.Join(lines, "\n"), nil
}

func cursorSelection(hasCursor bool) string {
	if !hasCursor {
		return ""
	}
	return "cursor"
}

func toPublicName(raw string) string {
	if raw == "" {
		return ""
	}
	trimmed := strings.ReplaceAll(raw, "_", " ")
	parts := strings.Fields(trimmed)
	if len(parts) == 0 {
		return ""
	}
	var out strings.Builder
	for _, part := range parts {
		if part == "" {
			continue
		}
		out.WriteString(strings.ToUpper(part[:1]))
		if len(part) > 1 {
			out.WriteString(part[1:])
		}
	}
	return out.String()
}
