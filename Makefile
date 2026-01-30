.PHONY: all oauth graphql rest graphql-schema graphql-gen oauth-login oauth-login-server oauth-login-go test-python test-go jira-rest-openapi jira-rest-gen terraform terraform-test

GOCACHE ?= $(CURDIR)/go/.gocache
GOPATH ?= $(CURDIR)/go/.gopath
OAUTH_LOGIN_ARGS ?=

all: oauth rest graphql

graphql-schema:
	python python/tools/fetch_graphql_schema.py

graphql-gen:
	python python/tools/generate_jira_project_models.py
	python python/tools/generate_jira_issue_models.py
	python python/tools/generate_jira_sprint_models.py
	python python/tools/generate_jira_worklog_models.py
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_project_models
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_issue_models
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_sprint_models
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_worklog_models

graphql: graphql-schema graphql-gen

jira-rest-openapi:
	python python/tools/fetch_jira_rest_openapi.py

jira-rest-gen:
	python python/tools/generate_jira_rest_models.py
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_rest_models

rest: jira-rest-openapi jira-rest-gen

oauth-login:
	python python/tools/oauth_login.py $(OAUTH_LOGIN_ARGS)

oauth-login-server:
	python python/tools/oauth_login_server.py $(OAUTH_LOGIN_ARGS)

oauth-login-go:
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/oauth_login $(OAUTH_LOGIN_ARGS)

oauth:
	@if [ -z "$$ATLASSIAN_CLIENT_ID" ] || [ -z "$$ATLASSIAN_CLIENT_SECRET" ] || [ -z "$$ATLASSIAN_OAUTH_SCOPES" ]; then \
		echo "Missing required env vars for OAuth token: ATLASSIAN_CLIENT_ID, ATLASSIAN_CLIENT_SECRET, ATLASSIAN_OAUTH_SCOPES" >&2; \
		exit 2; \
	fi
	python python/tools/oauth_login_server.py $(OAUTH_LOGIN_ARGS)

test-python:
	cd python && PYTHONPATH=. python -m pytest

test-go:
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go test ./...

terraform:
	cd terraform && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go build -o terraform-provider-jira .

terraform-test:
	cd terraform && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go test ./...
