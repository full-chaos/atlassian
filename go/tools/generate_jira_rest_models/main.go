package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"go/format"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

func main() {
	repoRoot, err := findRepoRoot()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	specPath := filepath.Join(repoRoot, "openapi", "jira-rest.swagger-v3.json")
	docBytes, err := os.ReadFile(specPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "missing Jira REST OpenAPI spec at %s (run `make jira-rest-openapi`)\n", specPath)
		os.Exit(2)
	}

	var doc map[string]any
	if err := json.Unmarshal(docBytes, &doc); err != nil {
		fmt.Fprintf(os.Stderr, "parse OpenAPI JSON: %v\n", err)
		os.Exit(2)
	}

	rendered, err := generate(doc)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	formatted, err := format.Source([]byte(rendered))
	if err != nil {
		fmt.Fprintf(os.Stderr, "gofmt: %v\n", err)
		os.Exit(2)
	}

	outPath := filepath.Join(repoRoot, "go", "atlassian", "rest", "gen", "jira_api.go")
	if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "mkdir %s: %v\n", filepath.Dir(outPath), err)
		os.Exit(2)
	}
	if err := os.WriteFile(outPath, formatted, 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "write %s: %v\n", outPath, err)
		os.Exit(2)
	}
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

func refName(ref string) (string, error) {
	const prefix = "#/components/schemas/"
	if !strings.HasPrefix(ref, prefix) {
		return "", fmt.Errorf("unsupported $ref: %q", ref)
	}
	return strings.TrimPrefix(ref, prefix), nil
}

func getMap(m map[string]any, key string) (map[string]any, error) {
	raw, ok := m[key]
	if !ok || raw == nil {
		return nil, fmt.Errorf("missing %s", key)
	}
	out, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("expected object at %s", key)
	}
	return out, nil
}

func getOperationSchemaRef(doc map[string]any, path string, method string) (string, error) {
	paths, err := getMap(doc, "paths")
	if err != nil {
		return "", err
	}
	rawPath, ok := paths[path]
	if !ok || rawPath == nil {
		return "", fmt.Errorf("OpenAPI path not found: %s", path)
	}
	pathObj, ok := rawPath.(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid path object: %s", path)
	}
	opRaw, ok := pathObj[strings.ToLower(method)]
	if !ok || opRaw == nil {
		return "", fmt.Errorf("OpenAPI operation not found: %s %s", strings.ToUpper(method), path)
	}
	op, ok := opRaw.(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid operation object: %s %s", strings.ToUpper(method), path)
	}
	responses, err := getMap(op, "responses")
	if err != nil {
		return "", fmt.Errorf("missing responses: %s %s", strings.ToUpper(method), path)
	}
	respRaw, ok := responses["200"]
	if !ok || respRaw == nil {
		return "", fmt.Errorf("missing 200 response: %s %s", strings.ToUpper(method), path)
	}
	resp, ok := respRaw.(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid 200 response: %s %s", strings.ToUpper(method), path)
	}
	content, err := getMap(resp, "content")
	if err != nil {
		return "", fmt.Errorf("missing content: %s %s", strings.ToUpper(method), path)
	}
	appRaw, ok := content["application/json"]
	if !ok || appRaw == nil {
		return "", fmt.Errorf("missing application/json content: %s %s", strings.ToUpper(method), path)
	}
	app, ok := appRaw.(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid application/json content: %s %s", strings.ToUpper(method), path)
	}
	schemaRaw, ok := app["schema"]
	if !ok || schemaRaw == nil {
		return "", fmt.Errorf("missing schema: %s %s", strings.ToUpper(method), path)
	}
	schema, ok := schemaRaw.(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid schema: %s %s", strings.ToUpper(method), path)
	}
	refRaw, ok := schema["$ref"]
	if !ok || refRaw == nil {
		return "", fmt.Errorf("schema is not a $ref: %s %s", strings.ToUpper(method), path)
	}
	ref, ok := refRaw.(string)
	if !ok || strings.TrimSpace(ref) == "" {
		return "", fmt.Errorf("schema $ref invalid: %s %s", strings.ToUpper(method), path)
	}
	return ref, nil
}

func getSchema(doc map[string]any, name string) (map[string]any, error) {
	components, err := getMap(doc, "components")
	if err != nil {
		return nil, err
	}
	schemas, err := getMap(components, "schemas")
	if err != nil {
		return nil, err
	}
	raw, ok := schemas[name]
	if !ok || raw == nil {
		return nil, fmt.Errorf("schema not found: %s", name)
	}
	out, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("schema %s is not an object", name)
	}
	return out, nil
}

func expectProperty(schema map[string]any, prop string) (map[string]any, error) {
	propertiesRaw, ok := schema["properties"]
	if !ok || propertiesRaw == nil {
		return nil, errors.New("schema missing properties")
	}
	properties, ok := propertiesRaw.(map[string]any)
	if !ok {
		return nil, errors.New("schema properties not an object")
	}
	raw, ok := properties[prop]
	if !ok || raw == nil {
		return nil, fmt.Errorf("schema missing property %q", prop)
	}
	propSchema, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("property %q schema not an object", prop)
	}
	return propSchema, nil
}

func propertyRef(schema map[string]any) (string, error) {
	if refRaw, ok := schema["$ref"]; ok && refRaw != nil {
		if ref, ok := refRaw.(string); ok && strings.TrimSpace(ref) != "" {
			return ref, nil
		}
	}
	if allOfRaw, ok := schema["allOf"]; ok && allOfRaw != nil {
		if arr, ok := allOfRaw.([]any); ok && len(arr) == 1 {
			if inner, ok := arr[0].(map[string]any); ok {
				if refRaw, ok := inner["$ref"]; ok && refRaw != nil {
					if ref, ok := refRaw.(string); ok && strings.TrimSpace(ref) != "" {
						return ref, nil
					}
				}
			}
		}
	}
	return "", errors.New("property schema does not contain a supported $ref/allOf")
}

func generate(doc map[string]any) (string, error) {
	pageProjectsRef, err := getOperationSchemaRef(doc, "/rest/api/3/project/search", "get")
	if err != nil {
		return "", err
	}
	searchResultsRef, err := getOperationSchemaRef(doc, "/rest/api/3/search", "get")
	if err != nil {
		return "", err
	}
	pageChangelogRef, err := getOperationSchemaRef(doc, "/rest/api/3/issue/{issueIdOrKey}/changelog", "get")
	if err != nil {
		return "", err
	}
	pageWorklogsRef, err := getOperationSchemaRef(doc, "/rest/api/3/issue/{issueIdOrKey}/worklog", "get")
	if err != nil {
		return "", err
	}

	pageProjectsName, err := refName(pageProjectsRef)
	if err != nil {
		return "", err
	}
	searchResultsName, err := refName(searchResultsRef)
	if err != nil {
		return "", err
	}
	pageChangelogName, err := refName(pageChangelogRef)
	if err != nil {
		return "", err
	}
	pageWorklogsName, err := refName(pageWorklogsRef)
	if err != nil {
		return "", err
	}

	pageProjectsSchema, err := getSchema(doc, pageProjectsName)
	if err != nil {
		return "", err
	}
	valuesProp, err := expectProperty(pageProjectsSchema, "values")
	if err != nil {
		return "", err
	}
	itemsRaw, ok := valuesProp["items"].(map[string]any)
	if !ok {
		return "", errors.New("PageBeanProject.values.items missing or invalid")
	}
	projectRef, err := propertyRef(itemsRaw)
	if err != nil {
		return "", err
	}
	projectName, err := refName(projectRef)
	if err != nil {
		return "", err
	}

	searchSchema, err := getSchema(doc, searchResultsName)
	if err != nil {
		return "", err
	}
	issuesProp, err := expectProperty(searchSchema, "issues")
	if err != nil {
		return "", err
	}
	issuesItemsRaw, ok := issuesProp["items"].(map[string]any)
	if !ok {
		return "", errors.New("SearchResults.issues.items missing or invalid")
	}
	issueRef, err := propertyRef(issuesItemsRaw)
	if err != nil {
		return "", err
	}
	issueName, err := refName(issueRef)
	if err != nil {
		return "", err
	}

	pageChangelogSchema, err := getSchema(doc, pageChangelogName)
	if err != nil {
		return "", err
	}
	chValuesProp, err := expectProperty(pageChangelogSchema, "values")
	if err != nil {
		return "", err
	}
	chItemsRaw, ok := chValuesProp["items"].(map[string]any)
	if !ok {
		return "", errors.New("PageBeanChangelog.values.items missing or invalid")
	}
	changelogRef, err := propertyRef(chItemsRaw)
	if err != nil {
		return "", err
	}
	changelogName, err := refName(changelogRef)
	if err != nil {
		return "", err
	}

	changelogSchema, err := getSchema(doc, changelogName)
	if err != nil {
		return "", err
	}
	authorProp, err := expectProperty(changelogSchema, "author")
	if err != nil {
		return "", err
	}
	userRef, err := propertyRef(authorProp)
	if err != nil {
		return "", err
	}
	userDetailsName, err := refName(userRef)
	if err != nil {
		return "", err
	}
	itemsProp, err := expectProperty(changelogSchema, "items")
	if err != nil {
		return "", err
	}
	itemsItemsRaw, ok := itemsProp["items"].(map[string]any)
	if !ok {
		return "", errors.New("Changelog.items.items missing or invalid")
	}
	changeRef, err := propertyRef(itemsItemsRaw)
	if err != nil {
		return "", err
	}
	changeDetailsName, err := refName(changeRef)
	if err != nil {
		return "", err
	}

	pageWorklogsSchema, err := getSchema(doc, pageWorklogsName)
	if err != nil {
		return "", err
	}
	worklogsProp, err := expectProperty(pageWorklogsSchema, "worklogs")
	if err != nil {
		return "", err
	}
	worklogsItemsRaw, ok := worklogsProp["items"].(map[string]any)
	if !ok {
		return "", errors.New("PageOfWorklogs.worklogs.items missing or invalid")
	}
	worklogRef, err := propertyRef(worklogsItemsRaw)
	if err != nil {
		return "", err
	}
	worklogName, err := refName(worklogRef)
	if err != nil {
		return "", err
	}

	worklogSchema, err := getSchema(doc, worklogName)
	if err != nil {
		return "", err
	}
	wAuthor, err := expectProperty(worklogSchema, "author")
	if err != nil {
		return "", err
	}
	wUserRef, err := propertyRef(wAuthor)
	if err != nil {
		return "", err
	}
	if n, _ := refName(wUserRef); n != userDetailsName {
		return "", fmt.Errorf("Worklog.author expected %s but got %s", userDetailsName, n)
	}

	// Ensure key properties exist.
	for _, prop := range []string{"key", "name", "projectTypeKey"} {
		if _, err := expectProperty(mustSchema(doc, projectName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", projectName, prop, err)
		}
	}
	for _, prop := range []string{"id", "key", "fields"} {
		if _, err := expectProperty(mustSchema(doc, issueName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", issueName, prop, err)
		}
	}
	for _, prop := range []string{"id", "created", "items"} {
		if _, err := expectProperty(mustSchema(doc, changelogName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", changelogName, prop, err)
		}
	}
	for _, prop := range []string{"field", "from", "to", "fromString", "toString"} {
		if _, err := expectProperty(mustSchema(doc, changeDetailsName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", changeDetailsName, prop, err)
		}
	}
	for _, prop := range []string{"accountId", "displayName", "emailAddress"} {
		if _, err := expectProperty(mustSchema(doc, userDetailsName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", userDetailsName, prop, err)
		}
	}
	for _, prop := range []string{"id", "started", "timeSpentSeconds", "created", "updated", "author"} {
		if _, err := expectProperty(mustSchema(doc, worklogName), prop); err != nil {
			return "", fmt.Errorf("%s.%s missing: %w", worklogName, prop, err)
		}
	}

	out := strings.Builder{}
	out.WriteString("// Code generated by go/tools/generate_jira_rest_models/main.go. DO NOT EDIT.\n")
	out.WriteString("package gen\n\n")
	out.WriteString("import \"encoding/json\"\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", userDetailsName))
	out.WriteString("\tAccountID *string `json:\"accountId,omitempty\"`\n")
	out.WriteString("\tDisplayName *string `json:\"displayName,omitempty\"`\n")
	out.WriteString("\tEmailAddress *string `json:\"emailAddress,omitempty\"`\n")
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", projectName))
	out.WriteString("\tID *string `json:\"id,omitempty\"`\n")
	out.WriteString("\tKey string `json:\"key,omitempty\"`\n")
	out.WriteString("\tName string `json:\"name,omitempty\"`\n")
	out.WriteString("\tProjectTypeKey *string `json:\"projectTypeKey,omitempty\"`\n")
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", pageProjectsName))
	out.WriteString("\tStartAt *int `json:\"startAt,omitempty\"`\n")
	out.WriteString("\tMaxResults *int `json:\"maxResults,omitempty\"`\n")
	out.WriteString("\tTotal *int `json:\"total,omitempty\"`\n")
	out.WriteString("\tIsLast *bool `json:\"isLast,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tValues []%s `json:\"values,omitempty\"`\n", projectName))
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", issueName))
	out.WriteString("\tID *string `json:\"id,omitempty\"`\n")
	out.WriteString("\tKey *string `json:\"key,omitempty\"`\n")
	out.WriteString("\tFields map[string]any `json:\"fields,omitempty\"`\n")
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", searchResultsName))
	out.WriteString("\tStartAt *int `json:\"startAt,omitempty\"`\n")
	out.WriteString("\tMaxResults *int `json:\"maxResults,omitempty\"`\n")
	out.WriteString("\tTotal *int `json:\"total,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tIssues []%s `json:\"issues,omitempty\"`\n", issueName))
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", changeDetailsName))
	out.WriteString("\tField *string `json:\"field,omitempty\"`\n")
	out.WriteString("\tFrom *string `json:\"from,omitempty\"`\n")
	out.WriteString("\tTo *string `json:\"to,omitempty\"`\n")
	out.WriteString("\tFromString *string `json:\"fromString,omitempty\"`\n")
	out.WriteString("\tToString *string `json:\"toString,omitempty\"`\n")
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", changelogName))
	out.WriteString("\tID *string `json:\"id,omitempty\"`\n")
	out.WriteString("\tCreated *string `json:\"created,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tItems []%s `json:\"items,omitempty\"`\n", changeDetailsName))
	out.WriteString(fmt.Sprintf("\tAuthor *%s `json:\"author,omitempty\"`\n", userDetailsName))
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", pageChangelogName))
	out.WriteString("\tStartAt *int `json:\"startAt,omitempty\"`\n")
	out.WriteString("\tMaxResults *int `json:\"maxResults,omitempty\"`\n")
	out.WriteString("\tTotal *int `json:\"total,omitempty\"`\n")
	out.WriteString("\tIsLast *bool `json:\"isLast,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tValues []%s `json:\"values,omitempty\"`\n", changelogName))
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", worklogName))
	out.WriteString("\tID *string `json:\"id,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tAuthor *%s `json:\"author,omitempty\"`\n", userDetailsName))
	out.WriteString("\tStarted *string `json:\"started,omitempty\"`\n")
	out.WriteString("\tTimeSpentSeconds *int `json:\"timeSpentSeconds,omitempty\"`\n")
	out.WriteString("\tCreated *string `json:\"created,omitempty\"`\n")
	out.WriteString("\tUpdated *string `json:\"updated,omitempty\"`\n")
	out.WriteString("}\n\n")

	out.WriteString(fmt.Sprintf("type %s struct {\n", pageWorklogsName))
	out.WriteString("\tStartAt *int `json:\"startAt,omitempty\"`\n")
	out.WriteString("\tMaxResults *int `json:\"maxResults,omitempty\"`\n")
	out.WriteString("\tTotal *int `json:\"total,omitempty\"`\n")
	out.WriteString(fmt.Sprintf("\tWorklogs []%s `json:\"worklogs,omitempty\"`\n", worklogName))
	out.WriteString("}\n\n")

	for _, name := range []string{pageProjectsName, searchResultsName, pageChangelogName, pageWorklogsName} {
		out.WriteString(fmt.Sprintf("func Decode%s(data map[string]any) (*%s, error) {\n", name, name))
		out.WriteString("\tb, err := json.Marshal(data)\n")
		out.WriteString("\tif err != nil {\n\t\treturn nil, err\n\t}\n")
		out.WriteString(fmt.Sprintf("\tvar out %s\n", name))
		out.WriteString("\tif err := json.Unmarshal(b, &out); err != nil {\n\t\treturn nil, err\n\t}\n")
		out.WriteString("\treturn &out, nil\n}\n\n")
	}

	return out.String(), nil
}

func mustSchema(doc map[string]any, name string) map[string]any {
	s, err := getSchema(doc, name)
	if err != nil {
		panic(err)
	}
	return s
}
