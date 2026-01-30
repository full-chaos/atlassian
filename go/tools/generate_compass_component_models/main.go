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

type config struct {
	CloudIDType string
	QueryType   string

	ConnectionTypeName string
	ErrorTypeName      string

	PageInfoHasEndCursor      bool
	PageInfoEndCursorNullable bool
	EdgeHasCursor             bool

	EdgeNodeNullable        bool
	NodeComponentNullable   bool
	ComponentIDNullable     bool
	ComponentNameNullable   bool
	ComponentTypeIDNullable bool
	ComponentDescNullable   bool
	ComponentOwnerNullable  bool
	OwnerTeamIDNullable     bool
	OwnerTeamNameNullable   bool

	ErrorMessageNullable              bool
	ErrorHasExtensions                bool
	ErrorExtensionsNullable           bool
	ErrorExtensionsHasStatusCode      bool
	ErrorExtensionsStatusCodeNullable bool
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

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "compass_components_api.go")
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

func isNullable(typeRef any) bool {
	cur, _ := typeRef.(map[string]any)
	if cur == nil {
		return true
	}
	if kind, _ := cur["kind"].(string); kind == "NON_NULL" {
		return false
	}
	return true
}

func unwrapListElemTypeName(typeRef any) (string, error) {
	cur, ok := typeRef.(map[string]any)
	if !ok {
		return "", errors.New("invalid list type")
	}
	for i := 0; i < 16; i++ {
		kind, _ := cur["kind"].(string)
		if kind == "NON_NULL" {
			cur, _ = cur["ofType"].(map[string]any)
			continue
		}
		if kind != "LIST" {
			return "", errors.New("expected list type")
		}
		elem, _ := cur["ofType"].(map[string]any)
		name, _ := unwrapNamedType(elem)
		if name == "" {
			return "", errors.New("list element type missing name")
		}
		return name, nil
	}
	return "", errors.New("list type depth exceeded")
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

	compassField := getField(queryDef, "compass")
	if compassField == nil {
		return nil, fmt.Errorf("missing required field %s.compass", queryName)
	}
	compassTypeName, _ := unwrapNamedType(compassField["type"])
	compassDef := types[compassTypeName]
	if compassTypeName == "" || compassDef == nil {
		return nil, errors.New("failed to resolve type for field Query.compass")
	}

	searchComponents := getField(compassDef, "searchComponents")
	if searchComponents == nil {
		return nil, fmt.Errorf("missing required field %s.searchComponents", compassTypeName)
	}
	if getArg(searchComponents, "cloudId") == nil || getArg(searchComponents, "query") == nil {
		return nil, fmt.Errorf("field %s.searchComponents missing cloudId/query args", compassTypeName)
	}
	cloudIDType, err := typeRefToGQL(getArg(searchComponents, "cloudId")["type"])
	if err != nil {
		return nil, err
	}
	queryArgType, err := typeRefToGQL(getArg(searchComponents, "query")["type"])
	if err != nil {
		return nil, err
	}

	returnTypeName, returnKind := unwrapNamedType(searchComponents["type"])
	if returnTypeName == "" {
		return nil, errors.New("unable to resolve searchComponents return type")
	}

	connectionTypeName := ""
	errorTypeName := ""

	if returnKind == "UNION" {
		unionDef := types[returnTypeName]
		if unionDef == nil {
			return nil, fmt.Errorf("missing union definition: %s", returnTypeName)
		}
		possibleTypes, _ := unionDef["possibleTypes"].([]any)
		if len(possibleTypes) == 0 {
			return nil, fmt.Errorf("union %s missing possibleTypes", returnTypeName)
		}
		for _, raw := range possibleTypes {
			pt, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			name, _ := pt["name"].(string)
			if name == "" {
				continue
			}
			def := types[name]
			if def == nil {
				return nil, fmt.Errorf("missing possible type definition: %s", name)
			}
			if getField(def, "pageInfo") != nil && (getField(def, "edges") != nil || getField(def, "nodes") != nil) {
				if connectionTypeName != "" {
					return nil, errors.New("multiple connection-like types in searchComponents union")
				}
				connectionTypeName = name
				continue
			}
			if getField(def, "message") != nil {
				if errorTypeName != "" {
					return nil, errors.New("multiple error-like types in searchComponents union")
				}
				errorTypeName = name
			}
		}
		if connectionTypeName == "" {
			return nil, errors.New("unable to identify Compass searchComponents connection type")
		}
	} else {
		connectionTypeName = returnTypeName
	}

	connDef := types[connectionTypeName]
	if connDef == nil {
		return nil, fmt.Errorf("missing connection type definition: %s", connectionTypeName)
	}
	pageInfoField := getField(connDef, "pageInfo")
	edgesField := getField(connDef, "edges")
	nodesField := getField(connDef, "nodes")
	if pageInfoField == nil || edgesField == nil || nodesField == nil {
		return nil, fmt.Errorf("missing required connection fields on %s", connectionTypeName)
	}

	pageInfoTypeName, _ := unwrapNamedType(pageInfoField["type"])
	pageInfoDef := types[pageInfoTypeName]
	if pageInfoDef == nil {
		return nil, fmt.Errorf("missing PageInfo type definition: %s", pageInfoTypeName)
	}
	if getField(pageInfoDef, "hasNextPage") == nil {
		return nil, fmt.Errorf("missing PageInfo.hasNextPage on %s", pageInfoTypeName)
	}
	pageInfoEndCursor := getField(pageInfoDef, "endCursor")
	pageInfoHasEndCursor := pageInfoEndCursor != nil
	pageInfoEndCursorNullable := false
	if pageInfoEndCursor != nil {
		pageInfoEndCursorNullable = isNullable(pageInfoEndCursor["type"])
	}

	edgeTypeName, _ := unwrapNamedType(edgesField["type"])
	edgeDef := types[edgeTypeName]
	if edgeDef == nil {
		return nil, fmt.Errorf("missing edge type definition: %s", edgeTypeName)
	}
	edgeHasCursor := getField(edgeDef, "cursor") != nil
	edgeNodeField := getField(edgeDef, "node")
	if edgeNodeField == nil {
		return nil, fmt.Errorf("missing edge.node on %s", edgeTypeName)
	}
	edgeNodeNullable := isNullable(edgeNodeField["type"])
	edgeNodeTypeName, _ := unwrapNamedType(edgeNodeField["type"])
	if edgeNodeTypeName == "" {
		return nil, fmt.Errorf("missing edge.node type on %s", edgeTypeName)
	}

	nodeTypeName, err := unwrapListElemTypeName(nodesField["type"])
	if err != nil {
		return nil, fmt.Errorf("nodes field on %s: %w", connectionTypeName, err)
	}
	if nodeTypeName != edgeNodeTypeName {
		return nil, fmt.Errorf("nodes element type %s does not match edge.node type %s", nodeTypeName, edgeNodeTypeName)
	}

	nodeDef := types[nodeTypeName]
	if nodeDef == nil {
		return nil, fmt.Errorf("missing node type definition: %s", nodeTypeName)
	}
	componentField := getField(nodeDef, "component")
	if componentField == nil {
		return nil, fmt.Errorf("missing node.component on %s", nodeTypeName)
	}
	componentNullable := isNullable(componentField["type"])
	componentTypeName, _ := unwrapNamedType(componentField["type"])
	componentDef := types[componentTypeName]
	if componentTypeName == "" || componentDef == nil {
		return nil, errors.New("failed to resolve component type")
	}

	componentIDField := getField(componentDef, "id")
	componentNameField := getField(componentDef, "name")
	componentTypeIDField := getField(componentDef, "typeId")
	componentDescField := getField(componentDef, "description")
	componentOwnerField := getField(componentDef, "ownerTeam")
	if componentIDField == nil || componentNameField == nil || componentTypeIDField == nil || componentDescField == nil || componentOwnerField == nil {
		return nil, fmt.Errorf("component type %s missing required fields", componentTypeName)
	}
	ownerTeamNullable := isNullable(componentOwnerField["type"])
	ownerTeamTypeName, _ := unwrapNamedType(componentOwnerField["type"])
	ownerTeamDef := types[ownerTeamTypeName]
	if ownerTeamDef == nil {
		return nil, fmt.Errorf("missing owner team type definition: %s", ownerTeamTypeName)
	}
	ownerTeamIDField := getField(ownerTeamDef, "id")
	ownerTeamNameField := getField(ownerTeamDef, "displayName")
	if ownerTeamIDField == nil || ownerTeamNameField == nil {
		return nil, fmt.Errorf("owner team type %s missing id/displayName", ownerTeamTypeName)
	}

	var errorMessageNullable bool
	var errorHasExtensions bool
	var errorExtensionsNullable bool
	var errorExtensionsHasStatusCode bool
	var errorExtensionsStatusCodeNullable bool
	if errorTypeName != "" {
		errorDef := types[errorTypeName]
		if errorDef == nil {
			return nil, fmt.Errorf("missing error type definition: %s", errorTypeName)
		}
		errorMessageField := getField(errorDef, "message")
		if errorMessageField == nil {
			return nil, fmt.Errorf("error type %s missing message field", errorTypeName)
		}
		errorMessageNullable = isNullable(errorMessageField["type"])
		errorExtensionsField := getField(errorDef, "extensions")
		if errorExtensionsField != nil {
			errorHasExtensions = true
			errorExtensionsNullable = isNullable(errorExtensionsField["type"])
			extTypeName, _ := unwrapNamedType(errorExtensionsField["type"])
			extDef := types[extTypeName]
			if extDef == nil {
				return nil, fmt.Errorf("missing error extensions type definition: %s", extTypeName)
			}
			statusField := getField(extDef, "statusCode")
			if statusField != nil {
				errorExtensionsHasStatusCode = true
				errorExtensionsStatusCodeNullable = isNullable(statusField["type"])
			}
		}
	}

	return &config{
		CloudIDType: cloudIDType,
		QueryType:   queryArgType,

		ConnectionTypeName: connectionTypeName,
		ErrorTypeName:      errorTypeName,

		PageInfoHasEndCursor:      pageInfoHasEndCursor,
		PageInfoEndCursorNullable: pageInfoEndCursorNullable,
		EdgeHasCursor:             edgeHasCursor,

		EdgeNodeNullable:        edgeNodeNullable,
		NodeComponentNullable:   componentNullable,
		ComponentIDNullable:     isNullable(componentIDField["type"]),
		ComponentNameNullable:   isNullable(componentNameField["type"]),
		ComponentTypeIDNullable: isNullable(componentTypeIDField["type"]),
		ComponentDescNullable:   isNullable(componentDescField["type"]),
		ComponentOwnerNullable:  ownerTeamNullable,
		OwnerTeamIDNullable:     isNullable(ownerTeamIDField["type"]),
		OwnerTeamNameNullable:   isNullable(ownerTeamNameField["type"]),

		ErrorMessageNullable:              errorMessageNullable,
		ErrorHasExtensions:                errorHasExtensions,
		ErrorExtensionsNullable:           errorExtensionsNullable,
		ErrorExtensionsHasStatusCode:      errorExtensionsHasStatusCode,
		ErrorExtensionsStatusCodeNullable: errorExtensionsStatusCodeNullable,
	}, nil
}

func goType(base string, nullable bool) string {
	if !nullable {
		return base
	}
	if strings.HasPrefix(base, "[]") {
		return base
	}
	return "*" + base
}

func jsonTag(name string, nullable bool) string {
	if nullable {
		return fmt.Sprintf("`json:\"%s,omitempty\"`", name)
	}
	return fmt.Sprintf("`json:\"%s\"`", name)
}

func renderGo(cfg *config) (string, error) {
	pageInfoSelect := "pageInfo { hasNextPage"
	if cfg.PageInfoHasEndCursor {
		pageInfoSelect += " endCursor"
	}
	pageInfoSelect += " }"

	componentSelect := "component { id name typeId description ownerTeam { id displayName } }"

	edgeSelect := "node { " + componentSelect + " }"
	if cfg.EdgeHasCursor {
		edgeSelect = "cursor " + edgeSelect
	}

	errorFragment := ""
	if cfg.ErrorTypeName != "" {
		errorFields := "message"
		if cfg.ErrorHasExtensions && cfg.ErrorExtensionsHasStatusCode {
			errorFields += " extensions { statusCode }"
		}
		errorFragment = fmt.Sprintf("\n      ... on %s { %s }", cfg.ErrorTypeName, errorFields)
	}

	query := fmt.Sprintf(`query CompassSearchComponents(
  $cloudId: %s,
  $query: %s
) {
  compass {
    searchComponents(cloudId: $cloudId, query: $query) {
      __typename
      ... on %s {
        nodes { %s }
        %s
        edges { %s }
      }%s
    }
  }
}
`, cfg.CloudIDType, cfg.QueryType, cfg.ConnectionTypeName, componentSelect, pageInfoSelect, edgeSelect, errorFragment)

	pageInfoEndCursorLine := "\tEndCursor   " + goType("string", cfg.PageInfoEndCursorNullable) + " " + jsonTag("endCursor", cfg.PageInfoEndCursorNullable)
	pageInfoLines := []string{
		"type PageInfo struct {",
		"\tHasNextPage bool " + jsonTag("hasNextPage", false),
	}
	if cfg.PageInfoHasEndCursor {
		pageInfoLines = append(pageInfoLines, pageInfoEndCursorLine)
	}
	pageInfoLines = append(pageInfoLines, "}")

	ownerTeamIDType := goType("string", cfg.OwnerTeamIDNullable)
	ownerTeamNameType := goType("string", cfg.OwnerTeamNameNullable)
	componentIDType := goType("string", cfg.ComponentIDNullable)
	componentNameType := goType("string", cfg.ComponentNameNullable)
	componentTypeIDType := goType("string", cfg.ComponentTypeIDNullable)
	componentDescType := goType("string", cfg.ComponentDescNullable)
	componentOwnerType := goType("CompassComponentOwnerTeam", cfg.ComponentOwnerNullable)
	componentNodeType := goType("CompassComponent", cfg.NodeComponentNullable)
	edgeNodeType := goType("CompassComponentNode", cfg.EdgeNodeNullable)

	lines := []string{
		"// Code generated by go/tools/generate_compass_component_models/main.go. DO NOT EDIT.",
		"package gen",
		"",
		"import (",
		"\t\"encoding/json\"",
		"\t\"errors\"",
		"\t\"fmt\"",
		")",
		"",
		"const (",
		fmt.Sprintf("\tCompassSearchComponentsPageInfoHasEndCursor = %t", cfg.PageInfoHasEndCursor),
		fmt.Sprintf("\tCompassSearchComponentsEdgeHasCursor = %t", cfg.EdgeHasCursor),
		fmt.Sprintf("\tCompassSearchComponentsConnectionTypename = %q", cfg.ConnectionTypeName),
	}
	if cfg.ErrorTypeName != "" {
		lines = append(lines, fmt.Sprintf("\tCompassSearchComponentsErrorTypename = %q", cfg.ErrorTypeName))
	}
	lines = append(lines,
		")",
		"",
		fmt.Sprintf("const CompassSearchComponentsQuery = %q", query),
		"",
	)

	lines = append(lines, pageInfoLines...)
	lines = append(lines, "",
		"type CompassComponentOwnerTeam struct {",
		"\tID "+ownerTeamIDType+" "+jsonTag("id", cfg.OwnerTeamIDNullable),
		"\tDisplayName "+ownerTeamNameType+" "+jsonTag("displayName", cfg.OwnerTeamNameNullable),
		"}",
		"",
		"type CompassComponent struct {",
		"\tID "+componentIDType+" "+jsonTag("id", cfg.ComponentIDNullable),
		"\tName "+componentNameType+" "+jsonTag("name", cfg.ComponentNameNullable),
		"\tTypeID "+componentTypeIDType+" "+jsonTag("typeId", cfg.ComponentTypeIDNullable),
		"\tDescription "+componentDescType+" "+jsonTag("description", cfg.ComponentDescNullable),
		"\tOwnerTeam "+componentOwnerType+" "+jsonTag("ownerTeam", cfg.ComponentOwnerNullable),
		"}",
		"",
		"type CompassComponentNode struct {",
		"\tComponent "+componentNodeType+" "+jsonTag("component", cfg.NodeComponentNullable),
		"}",
		"",
		"type CompassComponentEdge struct {",
	)
	if cfg.EdgeHasCursor {
		lines = append(lines, "\tCursor *string "+jsonTag("cursor", true))
	}
	lines = append(lines,
		"\tNode "+edgeNodeType+" "+jsonTag("node", cfg.EdgeNodeNullable),
		"}",
		"",
		"type CompassSearchComponentConnection struct {",
		"\tPageInfo PageInfo "+jsonTag("pageInfo", false),
		"\tEdges []CompassComponentEdge "+jsonTag("edges", false),
		"\tNodes []CompassComponentNode "+jsonTag("nodes", false),
		"}",
		"",
	)

	if cfg.ErrorTypeName != "" {
		errorMessageType := goType("string", cfg.ErrorMessageNullable)
		errorExtensionsType := "CompassSearchComponentsErrorExtensions"
		errorExtensionsFieldType := goType(errorExtensionsType, cfg.ErrorExtensionsNullable)
		lines = append(lines,
			"type CompassSearchComponentsErrorExtensions struct {",
		)
		if cfg.ErrorExtensionsHasStatusCode {
			statusType := goType("int", cfg.ErrorExtensionsStatusCodeNullable)
			lines = append(lines, "\tStatusCode "+statusType+" "+jsonTag("statusCode", cfg.ErrorExtensionsStatusCodeNullable))
		}
		lines = append(lines,
			"}",
			"",
			"type CompassSearchComponentsError struct {",
			"\tMessage "+errorMessageType+" "+jsonTag("message", cfg.ErrorMessageNullable),
		)
		if cfg.ErrorHasExtensions {
			lines = append(lines, "\tExtensions "+errorExtensionsFieldType+" "+jsonTag("extensions", cfg.ErrorExtensionsNullable))
		}
		lines = append(lines,
			"}",
			"",
		)
	}

	lines = append(lines,
		"type CompassSearchComponentsResult struct {",
		"\tTypename string `json:\"__typename\"`",
		"\tConnection *CompassSearchComponentConnection `json:\"-\"`",
	)
	if cfg.ErrorTypeName != "" {
		lines = append(lines, "\tError *CompassSearchComponentsError `json:\"-\"`")
	}
	lines = append(lines,
		"}",
		"",
		"func (r *CompassSearchComponentsResult) UnmarshalJSON(data []byte) error {",
		"\tvar base struct {",
		"\t\tTypename string `json:\"__typename\"`",
		"\t}",
		"\tif err := json.Unmarshal(data, &base); err != nil {",
		"\t\treturn err",
		"\t}",
		"\tif base.Typename == \"\" {",
		"\t\treturn errors.New(\"missing __typename for searchComponents\")",
		"\t}",
		"\tr.Typename = base.Typename",
		"\tswitch base.Typename {",
		"\tcase CompassSearchComponentsConnectionTypename:",
		"\t\tvar conn CompassSearchComponentConnection",
		"\t\tif err := json.Unmarshal(data, &conn); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tr.Connection = &conn",
	)
	if cfg.ErrorTypeName != "" {
		lines = append(lines,
			"\tcase CompassSearchComponentsErrorTypename:",
			"\t\tvar errResp CompassSearchComponentsError",
			"\t\tif err := json.Unmarshal(data, &errResp); err != nil {",
			"\t\t\treturn err",
			"\t\t}",
			"\t\tr.Error = &errResp",
		)
	}
	lines = append(lines,
		"\tdefault:",
		"\t\treturn fmt.Errorf(\"unsupported searchComponents type: %s\", base.Typename)",
		"\t}",
		"\treturn nil",
		"}",
		"",
		"type CompassSearchComponentsData struct {",
		"\tCompass struct {",
		"\t\tSearchComponents CompassSearchComponentsResult `json:\"searchComponents\"`",
		"\t} `json:\"compass\"`",
		"}",
		"",
		"func DecodeCompassSearchComponents(data map[string]any) (*CompassSearchComponentsData, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tvar out CompassSearchComponentsData",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\treturn &out, nil",
		"}",
	)

	return strings.Join(lines, "\n"), nil
}
