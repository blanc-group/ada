from ada_bridge.tool_mapper import sanitize_name, sanitize_schema, to_function_declaration


def test_strips_unsupported_keys():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "email": {"type": "string", "format": "email", "description": "Contact email"},
        },
        "required": ["email"],
    }
    out = sanitize_schema(schema)
    assert out == {
        "type": "object",
        "properties": {"email": {"type": "string", "description": "Contact email"}},
        "required": ["email"],
    }


def test_anyof_collapses_to_nullable():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "maybe"}
    out = sanitize_schema(schema)
    assert out["type"] == "string"
    assert out["nullable"] is True
    assert out["description"] == "maybe"


def test_type_list_with_null():
    out = sanitize_schema({"type": ["integer", "null"]})
    assert out == {"type": "integer", "nullable": True}


def test_enum_coerced_to_string():
    out = sanitize_schema({"type": "integer", "enum": [1, 2, 3]})
    assert out["type"] == "string"
    assert out["enum"] == ["1", "2", "3"]


def test_array_items_sanitized():
    schema = {
        "type": "array",
        "items": {"type": "object", "properties": {"id": {"type": "string"}}, "extra": 1},
        "maxItems": 5,
    }
    out = sanitize_schema(schema)
    assert out["items"] == {"type": "object", "properties": {"id": {"type": "string"}}}
    assert out["maxItems"] == 5


def test_object_without_properties_degrades_to_string():
    out = sanitize_schema({"type": "object"})
    assert out["type"] == "string"


def test_required_filtered_to_known_properties():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a", "ghost"],
    }
    assert sanitize_schema(schema)["required"] == ["a"]


def test_sanitize_name():
    assert sanitize_name("ghl_contacts_list") == "ghl_contacts_list"
    assert sanitize_name("weird-name.v2") == "weird_name_v2"
    assert sanitize_name("1bad") == "t_1bad"
    assert len(sanitize_name("x" * 200)) == 64


def test_declaration_from_dict_tool():
    tool = {
        "name": "ghl_contacts_list",
        "description": "List contacts",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    }
    decl = to_function_declaration(tool)
    assert decl["name"] == "ghl_contacts_list"
    assert decl["parameters"]["properties"]["limit"] == {"type": "integer"}


def test_declaration_without_params_omits_parameters():
    decl = to_function_declaration({"name": "n8n_workflows_list", "description": "x"})
    assert "parameters" not in decl


class FakeSdkTool:
    name = "meta_campaigns_get"
    description = "Get a campaign"
    inputSchema = {"type": "object", "properties": {"id": {"type": "string"}}}


def test_declaration_from_sdk_object():
    decl = to_function_declaration(FakeSdkTool())
    assert decl["name"] == "meta_campaigns_get"
    assert decl["parameters"]["properties"]["id"] == {"type": "string"}
