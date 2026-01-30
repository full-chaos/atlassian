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
	ComponentIDType   string
	ComponentTypeName string
	ErrorTypeName     string

	ScorecardsFieldName string
	ConnectionTypeName  string

	PageInfoHasEndCursor      bool
	PageInfoEndCursorNullable bool
	EdgeHasCursor             bool
	ConnectionHasNodes        bool

	ScoreFieldName     string
	ScoreFieldNullable bool

	MaxScoreFieldName     string
	MaxScoreFieldNullable bool

	EvaluatedAtFieldName     string
	EvaluatedAtFieldNullable bool

	ScorecardFieldName         string
	ScorecardIDFieldName       string
	ScorecardIDFieldNullable   bool
	ScorecardNameFieldName     string
	ScorecardNameFieldNullable bool

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

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "compass_scorecards_api.go")
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

func discoverComponentType(types map[string]map[string]any, unionDef map[string]any) (map[string]any, error) {
	raw, _ := unionDef["possibleTypes"].([]any)
	for _, item := range raw {
		pt, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name, _ := pt["name"].(string)
		if name == "" {
			continue
		}
		def := types[name]
		if def == nil {
			continue
		}
		if getField(def, "id") != nil && getField(def, "name") != nil {
			return def, nil
		}
	}
	return nil, errors.New("unable to identify CompassComponent type in union")
}

func discoverScorecardsField(types map[string]map[string]any, componentDef map[string]any) (string, map[string]any, map[string]any, error) {
	rawFields, _ := componentDef["fields"].([]any)
	for _, f := range rawFields {
		field, ok := f.(map[string]any)
		if !ok {
			continue
		}
		fieldName, _ := field["name"].(string)
		if fieldName == "" {
			continue
		}
		typeName, typeKind := unwrapNamedType(field["type"])
		if typeName == "" || typeKind == "" {
			continue
		}
		typeDef := types[typeName]
		if typeDef == nil {
			continue
		}
		var connDef map[string]any
		if typeKind == "UNION" || typeKind == "INTERFACE" {
			possibleTypes, _ := typeDef["possibleTypes"].([]any)
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
					continue
				}
				if getField(def, "pageInfo") != nil && getField(def, "edges") != nil {
					connDef = def
					break
				}
			}
		} else if getField(typeDef, "pageInfo") != nil && getField(typeDef, "edges") != nil {
			connDef = typeDef
		}
		if connDef == nil {
			continue
		}
		edgeTypeName, _ := unwrapNamedType(getField(connDef, "edges")["type"])
		edgeDef := types[edgeTypeName]
		if edgeDef == nil {
			continue
		}
		nodeField := getField(edgeDef, "node")
		if nodeField == nil {
			continue
		}
		nodeTypeName, _ := unwrapNamedType(nodeField["type"])
		nodeDef := types[nodeTypeName]
		if nodeDef == nil {
			continue
		}
		if getField(nodeDef, "score") == nil {
			continue
		}
		if getField(nodeDef, "scorecard") == nil {
			continue
		}
		return fieldName, connDef, nodeDef, nil
	}
	return "", nil, nil, errors.New("unable to locate scorecards field on CompassComponent")
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

	componentField := getField(compassDef, "component")
	if componentField == nil {
		return nil, fmt.Errorf("missing required field %s.component", compassTypeName)
	}
	componentIDArg := getArg(componentField, "id")
	if componentIDArg == nil {
		return nil, errors.New("component field missing id argument")
	}
	componentIDType, err := typeRefToGQL(componentIDArg["type"])
	if err != nil {
		return nil, err
	}

	componentReturnName, componentReturnKind := unwrapNamedType(componentField["type"])
	if componentReturnName == "" {
		return nil, errors.New("unable to resolve component return type")
	}
	componentReturnDef := types[componentReturnName]
	if componentReturnDef == nil {
		return nil, fmt.Errorf("missing component return type definition: %s", componentReturnName)
	}

	componentDef := componentReturnDef
	errorTypeName := ""
	if componentReturnKind == "UNION" || componentReturnKind == "INTERFACE" {
		if componentReturnDef == nil {
			return nil, fmt.Errorf("missing union definition: %s", componentReturnName)
		}
		compDef, err := discoverComponentType(types, componentReturnDef)
		if err != nil {
			return nil, err
		}
		componentDef = compDef
		possibleTypes, _ := componentReturnDef["possibleTypes"].([]any)
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
				continue
			}
			if getField(def, "message") != nil {
				errorTypeName = name
				break
			}
		}
	}

	componentTypeName, _ := componentDef["name"].(string)
	if componentTypeName == "" {
		return nil, errors.New("unable to resolve component type name")
	}

	scorecardsFieldName, connDef, nodeDef, err := discoverScorecardsField(types, componentDef)
	if err != nil {
		return nil, err
	}

	connectionTypeName, _ := connDef["name"].(string)
	if connectionTypeName == "" {
		return nil, errors.New("scorecards connection missing name")
	}

	pageInfoField := getField(connDef, "pageInfo")
	edgesField := getField(connDef, "edges")
	nodesField := getField(connDef, "nodes")
	if pageInfoField == nil || edgesField == nil {
		return nil, fmt.Errorf("missing required connection fields on %s", connectionTypeName)
	}
	connectionHasNodes := nodesField != nil

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

	scoreField := getField(nodeDef, "score")
	if scoreField == nil {
		return nil, errors.New("scorecard node missing score field")
	}
	scoreFieldName, _ := scoreField["name"].(string)
	scoreFieldNullable := isNullable(scoreField["type"])

	maxScoreField := getField(nodeDef, "maxScore")
	maxScoreFieldName := ""
	maxScoreFieldNullable := true
	if maxScoreField != nil {
		maxScoreFieldName, _ = maxScoreField["name"].(string)
		maxScoreFieldNullable = isNullable(maxScoreField["type"])
	}

	evaluatedAtField := getField(nodeDef, "evaluatedAt")
	evaluatedAtFieldName := ""
	evaluatedAtFieldNullable := true
	if evaluatedAtField != nil {
		evaluatedAtFieldName, _ = evaluatedAtField["name"].(string)
		evaluatedAtFieldNullable = isNullable(evaluatedAtField["type"])
	}

	scorecardField := getField(nodeDef, "scorecard")
	if scorecardField == nil {
		return nil, errors.New("scorecard node missing scorecard field")
	}
	scorecardFieldName, _ := scorecardField["name"].(string)
	scorecardTypeName, _ := unwrapNamedType(scorecardField["type"])
	scorecardDef := types[scorecardTypeName]
	if scorecardDef == nil {
		return nil, fmt.Errorf("missing scorecard type definition: %s", scorecardTypeName)
	}
	scorecardIDField := getField(scorecardDef, "id")
	if scorecardIDField == nil {
		return nil, fmt.Errorf("scorecard type %s missing id field", scorecardTypeName)
	}
	scorecardIDFieldName, _ := scorecardIDField["name"].(string)
	scorecardIDFieldNullable := isNullable(scorecardIDField["type"])
	scorecardNameField := getField(scorecardDef, "name")
	if scorecardNameField == nil {
		scorecardNameField = getField(scorecardDef, "displayName")
	}
	scorecardNameFieldName := ""
	scorecardNameFieldNullable := true
	if scorecardNameField != nil {
		scorecardNameFieldName, _ = scorecardNameField["name"].(string)
		scorecardNameFieldNullable = isNullable(scorecardNameField["type"])
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
		ComponentIDType:   componentIDType,
		ComponentTypeName: componentTypeName,
		ErrorTypeName:     errorTypeName,

		ScorecardsFieldName: scorecardsFieldName,
		ConnectionTypeName:  connectionTypeName,

		PageInfoHasEndCursor:      pageInfoHasEndCursor,
		PageInfoEndCursorNullable: pageInfoEndCursorNullable,
		EdgeHasCursor:             edgeHasCursor,
		ConnectionHasNodes:        connectionHasNodes,

		ScoreFieldName:     scoreFieldName,
		ScoreFieldNullable: scoreFieldNullable,

		MaxScoreFieldName:     maxScoreFieldName,
		MaxScoreFieldNullable: maxScoreFieldNullable,

		EvaluatedAtFieldName:     evaluatedAtFieldName,
		EvaluatedAtFieldNullable: evaluatedAtFieldNullable,

		ScorecardFieldName:         scorecardFieldName,
		ScorecardIDFieldName:       scorecardIDFieldName,
		ScorecardIDFieldNullable:   scorecardIDFieldNullable,
		ScorecardNameFieldName:     scorecardNameFieldName,
		ScorecardNameFieldNullable: scorecardNameFieldNullable,

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

	nodeFields := []string{cfg.ScoreFieldName}
	if cfg.MaxScoreFieldName != "" {
		nodeFields = append(nodeFields, cfg.MaxScoreFieldName)
	}
	if cfg.EvaluatedAtFieldName != "" {
		nodeFields = append(nodeFields, cfg.EvaluatedAtFieldName)
	}
	scorecardSelect := cfg.ScorecardFieldName + " { " + cfg.ScorecardIDFieldName
	if cfg.ScorecardNameFieldName != "" {
		scorecardSelect += " " + cfg.ScorecardNameFieldName
	}
	scorecardSelect += " }"
	nodeFields = append(nodeFields, scorecardSelect)

	nodeSelect := strings.Join(nodeFields, " ")
	edgeSelect := "node { " + nodeSelect + " }"
	if cfg.EdgeHasCursor {
		edgeSelect = "cursor " + edgeSelect
	}

	nodesSelect := ""
	if cfg.ConnectionHasNodes {
		nodesSelect = "nodes { " + nodeSelect + " }"
	}

	errorFragment := ""
	if cfg.ErrorTypeName != "" {
		errorFields := "message"
		if cfg.ErrorHasExtensions && cfg.ErrorExtensionsHasStatusCode {
			errorFields += " extensions { statusCode }"
		}
		errorFragment = fmt.Sprintf("\n      ... on %s { %s }", cfg.ErrorTypeName, errorFields)
	}

	query := fmt.Sprintf(`query CompassComponentScorecards(
  $componentId: %s
) {
  compass {
    component(id: $componentId) {
      __typename
      ... on %s {
        %s {
          %s
          edges { %s }
          %s
        }
      }%s
    }
  }
}
`, cfg.ComponentIDType, cfg.ComponentTypeName, cfg.ScorecardsFieldName, pageInfoSelect, edgeSelect, nodesSelect, errorFragment)

	pageInfoLines := []string{
		"type PageInfo struct {",
		"\tHasNextPage bool " + jsonTag("hasNextPage", false),
	}
	if cfg.PageInfoHasEndCursor {
		pageInfoLines = append(pageInfoLines, "\tEndCursor "+goType("string", cfg.PageInfoEndCursorNullable)+" "+jsonTag("endCursor", cfg.PageInfoEndCursorNullable))
	}
	pageInfoLines = append(pageInfoLines, "}")

	scoreType := goType("float64", cfg.ScoreFieldNullable)
	maxScoreType := goType("float64", cfg.MaxScoreFieldNullable)
	evaluatedAtType := goType("string", cfg.EvaluatedAtFieldNullable)
	scorecardIDType := goType("string", cfg.ScorecardIDFieldNullable)
	scorecardNameType := goType("string", cfg.ScorecardNameFieldNullable)

	lines := []string{
		"// Code generated by go/tools/generate_compass_scorecard_models/main.go. DO NOT EDIT.",
		"package gen",
		"",
		"import (",
		"\t\"encoding/json\"",
		"\t\"errors\"",
		"\t\"fmt\"",
		")",
		"",
		"const (",
		fmt.Sprintf("\tCompassComponentScorecardsConnectionTypename = %q", cfg.ConnectionTypeName),
	}
	if cfg.ErrorTypeName != "" {
		lines = append(lines, fmt.Sprintf("\tCompassComponentScorecardsErrorTypename = %q", cfg.ErrorTypeName))
	}
	lines = append(lines,
		")",
		"",
		fmt.Sprintf("const CompassComponentScorecardsQuery = %q", query),
		"",
	)

	lines = append(lines, pageInfoLines...)
	lines = append(lines,
		"",
		"type CompassScorecardRef struct {",
		"\tID "+scorecardIDType+" "+jsonTag(cfg.ScorecardIDFieldName, cfg.ScorecardIDFieldNullable),
	)
	if cfg.ScorecardNameFieldName != "" {
		lines = append(lines, "\tName "+scorecardNameType+" "+jsonTag(cfg.ScorecardNameFieldName, cfg.ScorecardNameFieldNullable))
	}
	lines = append(lines,
		"}",
		"",
		"type CompassScorecardNode struct {",
		"\tScorecard *CompassScorecardRef "+jsonTag(cfg.ScorecardFieldName, true),
		"\tScore "+scoreType+" "+jsonTag(cfg.ScoreFieldName, cfg.ScoreFieldNullable),
	)
	if cfg.MaxScoreFieldName != "" {
		lines = append(lines, "\tMaxScore "+maxScoreType+" "+jsonTag(cfg.MaxScoreFieldName, cfg.MaxScoreFieldNullable))
	}
	if cfg.EvaluatedAtFieldName != "" {
		lines = append(lines, "\tEvaluatedAt "+evaluatedAtType+" "+jsonTag(cfg.EvaluatedAtFieldName, cfg.EvaluatedAtFieldNullable))
	}
	lines = append(lines,
		"}",
		"",
		"type CompassScorecardEdge struct {",
	)
	if cfg.EdgeHasCursor {
		lines = append(lines, "\tCursor *string "+jsonTag("cursor", true))
	}
	lines = append(lines,
		"\tNode CompassScorecardNode "+jsonTag("node", false),
		"}",
		"",
		"type CompassScorecardConnection struct {",
		"\tPageInfo PageInfo "+jsonTag("pageInfo", false),
		"\tEdges []CompassScorecardEdge "+jsonTag("edges", false),
	)
	if cfg.ConnectionHasNodes {
		lines = append(lines, "\tNodes []CompassScorecardNode "+jsonTag("nodes", false))
	}
	lines = append(lines,
		"}",
		"",
	)

	if cfg.ErrorTypeName != "" {
		errorMessageType := goType("string", cfg.ErrorMessageNullable)
		errorExtensionsType := "CompassComponentScorecardsErrorExtensions"
		errorExtensionsFieldType := goType(errorExtensionsType, cfg.ErrorExtensionsNullable)
		lines = append(lines,
			"type CompassComponentScorecardsErrorExtensions struct {",
		)
		if cfg.ErrorExtensionsHasStatusCode {
			statusType := goType("int", cfg.ErrorExtensionsStatusCodeNullable)
			lines = append(lines, "\tStatusCode "+statusType+" "+jsonTag("statusCode", cfg.ErrorExtensionsStatusCodeNullable))
		}
		lines = append(lines,
			"}",
			"",
			"type CompassComponentScorecardsError struct {",
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
		"type CompassComponentScorecardsResult struct {",
		"\tTypename string `json:\"__typename\"`",
		"\tConnection *CompassScorecardConnection `json:\"-\"`",
	)
	if cfg.ErrorTypeName != "" {
		lines = append(lines, "\tError *CompassComponentScorecardsError `json:\"-\"`")
	}
	lines = append(lines,
		"}",
		"",
		"func (r *CompassComponentScorecardsResult) UnmarshalJSON(data []byte) error {",
		"\tvar base struct {",
		"\t\tTypename string `json:\"__typename\"`",
		"\t}",
		"\tif err := json.Unmarshal(data, &base); err != nil {",
		"\t\treturn err",
		"\t}",
		"\tif base.Typename == \"\" {",
		"\t\treturn errors.New(\"missing __typename for component\")",
		"\t}",
		"\tr.Typename = base.Typename",
		"\tswitch base.Typename {",
		"\tcase CompassComponentScorecardsConnectionTypename:",
		"\t\tvar conn CompassScorecardConnection",
		"\t\tif err := json.Unmarshal(data, &conn); err != nil {",
		"\t\t\treturn err",
		"\t\t}",
		"\t\tr.Connection = &conn",
	)
	if cfg.ErrorTypeName != "" {
		lines = append(lines,
			"\tcase CompassComponentScorecardsErrorTypename:",
			"\t\tvar errResp CompassComponentScorecardsError",
			"\t\tif err := json.Unmarshal(data, &errResp); err != nil {",
			"\t\t\treturn err",
			"\t\t}",
			"\t\tr.Error = &errResp",
		)
	}
	lines = append(lines,
		"\tdefault:",
		"\t\treturn fmt.Errorf(\"unsupported component type: %s\", base.Typename)",
		"\t}",
		"\treturn nil",
		"}",
		"",
		"type CompassComponentScorecardsData struct {",
		"\tCompass struct {",
		"\t\tComponent CompassComponentScorecardsResult `json:\"component\"`",
		"\t} `json:\"compass\"`",
		"}",
		"",
		"func DecodeCompassComponentScorecards(data map[string]any) (*CompassComponentScorecardsData, error) {",
		"\tb, err := json.Marshal(data)",
		"\tif err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\tvar out CompassComponentScorecardsData",
		"\tif err := json.Unmarshal(b, &out); err != nil {",
		"\t\treturn nil, err",
		"\t}",
		"\treturn &out, nil",
		"}",
	)

	return strings.Join(lines, "\n"), nil
}
