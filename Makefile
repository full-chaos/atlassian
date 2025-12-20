.PHONY: graphql-schema graphql-gen oauth-login oauth-login-go test-python test-go jira-rest-openapi jira-rest-gen

GOCACHE ?= $(CURDIR)/go/.gocache
GOPATH ?= $(CURDIR)/go/.gopath
OAUTH_LOGIN_ARGS ?=

graphql-schema:
	python python/tools/fetch_graphql_schema.py

graphql-gen:
	python python/tools/generate_jira_project_models.py
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_project_models

jira-rest-openapi:
	python python/tools/fetch_jira_rest_openapi.py

jira-rest-gen:
	python python/tools/generate_jira_rest_models.py
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/generate_jira_rest_models

oauth-login:
	python python/tools/oauth_login.py $(OAUTH_LOGIN_ARGS)

oauth-login-go:
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go run ./tools/oauth_login $(OAUTH_LOGIN_ARGS)

test-python:
	cd python && python -m pytest

test-go:
	cd go && GOCACHE="$(GOCACHE)" GOPATH="$(GOPATH)" go test ./...
