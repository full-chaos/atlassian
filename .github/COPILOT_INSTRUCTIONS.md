COPILOT INSTRUCTIONS

Purpose

This file gives concise, project-specific guidance for GitHub Copilot, Copilot CLI, and other AI agents working on the atlassian-graphql repository. AGENTS.md is the authoritative policy; follow it first.

Quick Rules

- Always follow AGENTS.md. If there is any conflict, AGENTS.md wins.
- Do not hand-edit generated code in:
  - python/atlassian_graphql/gen/
  - go/graphql/gen/
  - graphql/schema.introspection.json is the source of truth for generation.
- Preserve separation of concerns: transport, mapping, and analytics are distinct.
- Make the smallest possible change to achieve the goal; prefer edits that change as few lines as possible.
- NEVER commit secrets, credentials, or tokens.
- Run only existing tests and linters; do not add new tooling without explicit approval.
- Retry logic: Only retry on HTTP 429; do not retry on >=500 or other 4xx errors (AGENTS.md rules).
- Pagination: Assume every GraphQL connection can paginate and handle pageInfo.hasNextPage.

Working with the Copilot CLI

- Use the repo-local tools: grep, glob, view, edit, create as supplied by the CLI.
- Always call report_intent when invoking tools that modify or inspect the codebase (Copilot CLI requirement).
- Before making edits, read the relevant files (use view/grep) and summarise intent in one sentence.
- When editing, make minimal, surgical changes and include a brief rationale in the commit message.

Commit & PR guidance

- Commit messages should be brief and factual: "fix: <short description>" or "chore: <short description>".
- Include link to an issue or task when available.
- Create a PR for changes that affect behavior, schema, or public APIs.

If Unsure

- Ask for clarification. If a user question remains ambiguous, prefer asking rather than guessing.
- When in doubt about schema or generated code, fetch introspection and regenerate rather than guessing fields.

Contact

- For policy questions, refer to AGENTS.md at the repo root.
