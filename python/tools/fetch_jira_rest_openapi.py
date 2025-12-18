from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_project_to_syspath() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))


_add_project_to_syspath()

from atlassian.rest.openapi_fetcher import (
    DEFAULT_JIRA_REST_OPENAPI_URL,
    fetch_jira_rest_openapi,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Jira Cloud REST OpenAPI (swagger-v3) spec JSON.")
    parser.add_argument(
        "--url",
        default=DEFAULT_JIRA_REST_OPENAPI_URL,
        help=f"OpenAPI spec URL (default: {DEFAULT_JIRA_REST_OPENAPI_URL})",
    )
    parser.add_argument(
        "--out",
        default="openapi/jira-rest.swagger-v3.json",
        help="Output path (default: openapi/jira-rest.swagger-v3.json)",
    )
    args = parser.parse_args()

    out = fetch_jira_rest_openapi(url=args.url, output_path=args.out)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
