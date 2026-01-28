from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

import httpx

from ..auth import AuthProvider
from ..errors import SerializationError
from ..models import GraphQLErrorItem
from .client import GraphQLClient


_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
    directives {
      name
      description
      locations
      args {
        ...InputValue
      }
    }
  }
}

fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    args {
      ...InputValue
    }
    type {
      ...TypeRef
    }
    isDeprecated
    deprecationReason
  }
  inputFields {
    ...InputValue
  }
  interfaces {
    ...TypeRef
  }
  enumValues(includeDeprecated: true) {
    name
    description
    isDeprecated
    deprecationReason
  }
  possibleTypes {
    ...TypeRef
  }
}

fragment InputValue on __InputValue {
  name
  description
  type { ...TypeRef }
  defaultValue
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
  }
}
""".strip()


@dataclass(frozen=True)
class SchemaFetchResult:
    introspection_json_path: Path
    sdl_path: Optional[Path]


def _error_item_to_dict(item: GraphQLErrorItem) -> Dict[str, Any]:
    raw = asdict(item)
    return {k: v for k, v in raw.items() if v is not None}


def _maybe_introspection_to_sdl(envelope: Dict[str, Any]) -> Optional[str]:
    try:
        from graphql import build_client_schema, print_schema  # type: ignore[import-not-found]
    except Exception:
        return None

    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    try:
        schema = build_client_schema(data)
        return print_schema(schema)
    except Exception:
        return None


def fetch_schema_introspection(
    base_url: str,
    auth: AuthProvider,
    *,
    output_dir: Union[str, Path] = "graphql",
    timeout_seconds: float = 30.0,
    logger=None,
    experimental_apis: Optional[Sequence[str]] = None,
    http_client: httpx.Client | None = None,
) -> SchemaFetchResult:
    if not base_url or not base_url.strip():
        raise ValueError("base_url is required")
    if auth is None:
        raise ValueError("auth is required")
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = GraphQLClient(
        base_url,
        auth=auth,
        timeout_seconds=timeout_seconds,
        strict=True,
        logger=logger,
        max_retries_429=2,
        http_client=http_client,
    )
    try:
        result = client.execute(
            _INTROSPECTION_QUERY,
            operation_name="IntrospectionQuery",
            experimental_apis=list(experimental_apis) if experimental_apis else None,
        )
    finally:
        client.close()

    if not isinstance(result.data, dict) or "__schema" not in result.data:
        raise SerializationError("Introspection response missing data.__schema")

    envelope: Dict[str, Any] = {"data": result.data}
    if result.errors:
        envelope["errors"] = [_error_item_to_dict(e) for e in result.errors]
    if result.extensions:
        envelope["extensions"] = result.extensions

    introspection_path = out_dir / "schema.introspection.json"
    introspection_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    sdl_path: Optional[Path] = None
    sdl = _maybe_introspection_to_sdl(envelope)
    if sdl:
        sdl_path = out_dir / "schema.sdl.graphql"
        sdl_path.write_text(sdl.strip() + "\n", encoding="utf-8")

    return SchemaFetchResult(
        introspection_json_path=introspection_path,
        sdl_path=sdl_path,
    )
