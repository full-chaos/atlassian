from dataclasses import dataclass
from typing import Any, Callable, cast

import pytest

from atlassian.graph.mappers.compass_components import map_compass_component
from tools.generate_compass_component_models import _Config, _render_python


@dataclass
class MockTeam:
    id: str | None = None
    name: str | None = None


@dataclass
class MockComponent:
    id: str | None = None
    name: str | None = None
    type: str | None = None
    description: str | None = None
    owner_team_id: str | None = None
    owner_team_name: str | None = None
    labels: list[str] | None = None
    owner_team: MockTeam | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _build_compass_api() -> dict[str, Any]:
    cfg = _Config(
        cloud_id_type="ID!",
        query_input_type="CompassSearchComponentsInput!",
        search_result_kind="UNION",
        connection_type_name="CompassSearchComponentConnection",
        error_type_name="QueryError",
        component_result_kind="UNION",
        component_type_name="CompassComponent",
        owner_team_type_name="CompassTeam",
        pageinfo_has_end_cursor=True,
        edge_has_cursor=True,
        connection_has_nodes=False,
        query_error_has_extensions=True,
        query_error_extensions_has_status_code=True,
        component_type_id_field="typeId",
        component_description_field="description",
        owner_team_field="ownerTeam",
        owner_team_id_field="id",
        owner_team_name_field="displayName",
    )
    namespace: dict[str, Any] = {}
    code = _render_python(cfg)
    exec(compile(code, "<compass_components_api>", "exec"), namespace)
    return namespace


class TestMapCompassComponent:
    def test_requires_component_id(self):
        component = MockComponent(id=None, name="Service", type="SERVICE")
        with pytest.raises(ValueError, match="component.id is required"):
            map_compass_component(cloud_id="cloud", component=component)

    def test_requires_component_name(self):
        component = MockComponent(id="comp-1", name="", type="SERVICE")
        with pytest.raises(ValueError, match="component.name is required"):
            map_compass_component(cloud_id="cloud", component=component)

    def test_requires_component_type(self):
        component = MockComponent(id="comp-1", name="Service", type="  ")
        with pytest.raises(ValueError, match="component.type is required"):
            map_compass_component(cloud_id="cloud", component=component)

    def test_optional_fields_can_be_none(self):
        component = MockComponent(id="comp-1", name="Service", type="SERVICE")
        mapped = map_compass_component(cloud_id="cloud", component=component)
        assert mapped.description is None
        assert mapped.owner_team_id is None
        assert mapped.owner_team_name is None
        assert mapped.labels == []

    def test_labels_empty_list(self):
        component = MockComponent(
            id="comp-1",
            name="Service",
            type="SERVICE",
            labels=[],
        )
        mapped = map_compass_component(cloud_id="cloud", component=component)
        assert mapped.labels == []

    def test_labels_trim_and_filter(self):
        component = MockComponent(
            id="comp-1",
            name="Service",
            type="SERVICE",
            labels=["  alpha ", "", "beta", "  "],
        )
        mapped = map_compass_component(cloud_id="cloud", component=component)
        assert mapped.labels == ["alpha", "beta"]

    def test_owner_team_object_overrides_fields(self):
        component = MockComponent(
            id="comp-1",
            name="Service",
            type="SERVICE",
            owner_team_id="team-legacy",
            owner_team_name="Legacy",
            owner_team=MockTeam(id="team-1", name="Platform"),
        )
        mapped = map_compass_component(cloud_id="cloud", component=component)
        assert mapped.owner_team_id == "team-1"
        assert mapped.owner_team_name == "Platform"


def test_compass_components_pagination_parses_page_info_and_edges():
    api = _build_compass_api()
    parse = cast(Callable[[Any], Any], api["parse_compass_search_components"])
    data = {
        "compass": {
            "searchComponents": {
                "__typename": "CompassSearchComponentConnection",
                "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                "edges": [
                    {
                        "cursor": "e1",
                        "node": {
                            "component": {
                                "__typename": "CompassComponent",
                                "id": "comp-1",
                                "name": "Service",
                                "typeId": "SERVICE",
                                "description": "Primary service",
                                "ownerTeam": {
                                    "id": "team-1",
                                    "displayName": "Platform",
                                },
                            }
                        },
                    }
                ],
            }
        }
    }
    result = parse(data)
    assert result.page_info.has_next_page is True
    assert result.page_info.end_cursor == "c1"
    assert result.edges[0].cursor == "e1"
    assert result.edges[0].node.component
    assert result.edges[0].node.component.id == "comp-1"


def test_compass_components_handles_query_error_union():
    api = _build_compass_api()
    parse = cast(Callable[[Any], Any], api["parse_compass_search_components"])
    query_error = cast(type, api["QueryError"])
    data = {
        "compass": {
            "searchComponents": {
                "__typename": "QueryError",
                "message": "Not authorized",
                "extensions": {"statusCode": 403},
            }
        }
    }
    result = parse(data)
    assert isinstance(result, query_error)
    assert result.message == "Not authorized"
    assert result.status_code == 403


def test_compass_components_handles_component_error_nodes():
    api = _build_compass_api()
    parse = cast(Callable[[Any], Any], api["parse_compass_search_components"])
    query_error = cast(type, api["QueryError"])
    data = {
        "compass": {
            "searchComponents": {
                "__typename": "CompassSearchComponentConnection",
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {
                        "cursor": "e1",
                        "node": {
                            "component": {
                                "__typename": "QueryError",
                                "message": "Component not accessible",
                                "extensions": {"statusCode": 404},
                            }
                        },
                    }
                ],
            }
        }
    }
    result = parse(data)
    node = result.edges[0].node
    assert node.component is None
    assert isinstance(node.error, query_error)
    assert node.error.message == "Component not accessible"
    assert node.error.status_code == 404
