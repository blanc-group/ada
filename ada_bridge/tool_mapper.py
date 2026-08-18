"""Convert MCP tool definitions into Gemini Live function declarations.

Gemini's function-calling schema is a subset of JSON Schema: unknown keys make
the Live API reject the whole session config, so everything the Blanc MCP
gateway emits (Zod adds `additionalProperties`, `$schema`, `anyOf`, ...) must
be sanitized down to the supported vocabulary before it reaches
`LiveConnectConfig.tools`.
"""

from __future__ import annotations

import re
from typing import Any

# Keys Gemini's Schema accepts (see google.genai.types.Schema).
_ALLOWED_KEYS = {
    "type",
    "description",
    "enum",
    "properties",
    "required",
    "items",
    "nullable",
    "minItems",
    "maxItems",
}

_VALID_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")
_MAX_NAME_LEN = 64
_MAX_DESCRIPTION_LEN = 4096


def sanitize_name(name: str) -> str:
    """Coerce an MCP tool name into a valid Gemini function name."""
    cleaned = _NAME_RE.sub("_", name)[:_MAX_NAME_LEN]
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"t_{cleaned}"[:_MAX_NAME_LEN]
    return cleaned


def _pick_from_union(subschemas: list[Any]) -> tuple[dict[str, Any], bool]:
    """Collapse anyOf/oneOf to its first non-null branch; report nullability."""
    nullable = False
    chosen: dict[str, Any] | None = None
    for sub in subschemas:
        if not isinstance(sub, dict):
            continue
        if sub.get("type") == "null":
            nullable = True
            continue
        if chosen is None:
            chosen = sub
    return chosen or {}, nullable


def sanitize_schema(schema: Any) -> dict[str, Any]:
    """Recursively strip a JSON Schema down to Gemini-supported keys."""
    if not isinstance(schema, dict):
        return {"type": "string"}

    schema = dict(schema)
    nullable = bool(schema.get("nullable"))

    union = schema.get("anyOf") or schema.get("oneOf") or schema.get("allOf")
    if isinstance(union, list) and union:
        chosen, union_nullable = _pick_from_union(union)
        merged = {**{k: v for k, v in schema.items() if k in ("description",)}, **chosen}
        result = sanitize_schema(merged)
        if nullable or union_nullable:
            result["nullable"] = True
        return result

    out: dict[str, Any] = {}

    type_value = schema.get("type")
    if isinstance(type_value, list):
        non_null = [t for t in type_value if t != "null"]
        if "null" in type_value:
            nullable = True
        type_value = non_null[0] if non_null else None
    if isinstance(type_value, str) and type_value.lower() in _VALID_TYPES:
        out["type"] = type_value.lower()

    if "type" not in out:
        out["type"] = "object" if isinstance(schema.get("properties"), dict) else "string"

    description = schema.get("description")
    if isinstance(description, str) and description:
        out["description"] = description[:_MAX_DESCRIPTION_LEN]

    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        out["enum"] = [str(v) for v in enum]
        out["type"] = "string"

    if out["type"] == "object":
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            out["properties"] = {
                str(key): sanitize_schema(value) for key, value in properties.items()
            }
            required = schema.get("required")
            if isinstance(required, list):
                kept = [r for r in required if r in out["properties"]]
                if kept:
                    out["required"] = kept
        else:
            # Gemini rejects object schemas without properties.
            out["type"] = "string"
            out.setdefault(
                "description",
                "Opaque JSON object, pass as a JSON-encoded string.",
            )

    if out["type"] == "array":
        out["items"] = sanitize_schema(schema.get("items"))
        for bound in ("minItems", "maxItems"):
            if isinstance(schema.get(bound), int):
                out[bound] = schema[bound]

    if nullable:
        out["nullable"] = True

    return {k: v for k, v in out.items() if k in _ALLOWED_KEYS}


def to_function_declaration(tool: Any) -> dict[str, Any]:
    """Map one MCP tool (SDK object or plain dict) to a Gemini declaration.

    Accepts either `mcp.types.Tool` instances or dicts with the same shape
    (`name`, `description`, `inputSchema`).
    """
    if isinstance(tool, dict):
        name = tool.get("name", "")
        description = tool.get("description") or ""
        input_schema = tool.get("inputSchema") or tool.get("input_schema")
    else:
        name = getattr(tool, "name", "")
        description = getattr(tool, "description", None) or ""
        input_schema = getattr(tool, "inputSchema", None)

    declaration: dict[str, Any] = {
        "name": sanitize_name(name),
        "description": description[:_MAX_DESCRIPTION_LEN],
    }

    if isinstance(input_schema, dict) and isinstance(
        input_schema.get("properties"), dict
    ) and input_schema["properties"]:
        parameters = sanitize_schema(input_schema)
        if parameters.get("type") == "object":
            declaration["parameters"] = parameters

    return declaration
