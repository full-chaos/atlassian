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
	if err := validateSchema(schema); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	outPath := filepath.Join(repoRoot, "go", "atlassian", "graph", "gen", "jira_sprints_api.go")
	if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	source := renderGo()
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
	if data, ok := envelope["data"].(map[string]any); ok {
		envelope = data
	}
	schema, ok := envelope["__schema"].(map[string]any)
	if !ok {
		return nil, errors.New("introspection missing __schema")
	}
	return schema, nil
}

func validateSchema(schema map[string]any) error {
	types := typesMap(schema)
	queryName, err := queryTypeName(schema)
	if err != nil {
		return err
	}
	queryDef := types[queryName]
	if queryDef == nil {
		return fmt.Errorf("missing query type %s", queryName)
	}
	sprintByID := field(queryDef, "sprintById")
	if sprintByID == nil {
		return fmt.Errorf("missing field %s.sprintById", queryName)
	}
	if arg(sprintByID, "id") == nil {
		return errors.New("sprintById missing id arg")
	}
	sprintTypeName := unwrapNamedType(sprintByID["type"])
	if sprintTypeName == "" {
		return errors.New("unable to resolve sprintById return type")
	}
	sprintDef := types[sprintTypeName]
	if sprintDef == nil {
		return fmt.Errorf("missing type %s", sprintTypeName)
	}
	for _, name := range []string{"sprintId", "name", "state", "startDate", "endDate", "completionDate"} {
		if field(sprintDef, name) == nil {
			return fmt.Errorf("sprintById missing %s field", name)
		}
	}
	return nil
}

func typesMap(schema map[string]any) map[string]map[string]any {
	out := map[string]map[string]any{}
	raw, ok := schema["types"].([]any)
	if !ok {
		return out
	}
	for _, item := range raw {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if name, ok := obj["name"].(string); ok && name != "" {
			out[name] = obj
		}
	}
	return out
}

func queryTypeName(schema map[string]any) (string, error) {
	raw, ok := schema["queryType"].(map[string]any)
	if !ok {
		return "", errors.New("missing queryType")
	}
	name, ok := raw["name"].(string)
	if !ok || name == "" {
		return "", errors.New("missing queryType.name")
	}
	return name, nil
}

func field(typeDef map[string]any, name string) map[string]any {
	raw, ok := typeDef["fields"].([]any)
	if !ok {
		return nil
	}
	for _, item := range raw {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if obj["name"] == name {
			return obj
		}
	}
	return nil
}

func arg(fieldDef map[string]any, name string) map[string]any {
	raw, ok := fieldDef["args"].([]any)
	if !ok {
		return nil
	}
	for _, item := range raw {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if obj["name"] == name {
			return obj
		}
	}
	return nil
}

func unwrapNamedType(ref any) string {
	cur, ok := ref.(map[string]any)
	if !ok {
		return ""
	}
	for i := 0; i < 16; i++ {
		if name, ok := cur["name"].(string); ok && name != "" {
			return name
		}
		next, ok := cur["ofType"].(map[string]any)
		if !ok {
			return ""
		}
		cur = next
	}
	return ""
}

func renderGo() string {
	return `// Code generated by go/tools/generate_jira_sprint_models/main.go. DO NOT EDIT.
package gen

import "encoding/json"

const JiraSprintByIdQuery = ` + "`" + `query JiraSprintById(
  $id: ID!
) {
  sprintById(id: $id) {
    sprintId
    name
    state
    startDate
    endDate
    completionDate
  }
}
` + "`" + `

type JiraSprintNode struct {
	SprintID       string  ` + "`json:\"sprintId\"`" + `
	Name           *string ` + "`json:\"name\"`" + `
	State          *string ` + "`json:\"state\"`" + `
	StartDate      *string ` + "`json:\"startDate\"`" + `
	EndDate        *string ` + "`json:\"endDate\"`" + `
	CompletionDate *string ` + "`json:\"completionDate\"`" + `
}

type JiraSprintByIdData struct {
	SprintById *JiraSprintNode ` + "`json:\"sprintById\"`" + `
}

func DecodeJiraSprintById(data map[string]any) (*JiraSprintByIdData, error) {
	b, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}
	var out JiraSprintByIdData
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, err
	}
	return &out, nil
}
`
}
