"""AdaMcpBridge: expose Blanc MCP tools to a Gemini Live session.

Usage inside ADA v2's `backend/ada.py` (see the README for the full patch):

    bridge = AdaMcpBridge()
    await bridge.start()
    tools = [{"function_declarations": [*ADA_NATIVE_TOOLS, *bridge.declarations]}]
    ...
    if bridge.handles(fc.name):
        result = await bridge.execute(fc.name, dict(fc.args or {}))
"""

from __future__ import annotations

import logging
from typing import Any

from .config import BridgeConfig
from .confirmation import ConfirmationPolicy, confirmation_required_result
from .mcp_client import BlancMcpClient
from .tool_mapper import to_function_declaration

logger = logging.getLogger(__name__)


class AdaMcpBridge:
    def __init__(self, config: BridgeConfig | None = None) -> None:
        self._config = config or BridgeConfig.from_env()
        self._client = BlancMcpClient(
            self._config.mcp_url,
            self._config.mcp_api_key,
            tenant=self._config.mcp_tenant,
            extra_headers=self._config.extra_headers,
        )
        self._policy = ConfirmationPolicy(self._config.confirmation_ttl_seconds)
        self._declarations: list[dict[str, Any]] = []
        # Gemini calls back with the sanitized name; map it to the MCP name.
        self._mcp_name_by_declared: dict[str, str] = {}

    @property
    def config(self) -> BridgeConfig:
        return self._config

    @property
    def declarations(self) -> list[dict[str, Any]]:
        return list(self._declarations)

    @property
    def tool_names(self) -> set[str]:
        return set(self._mcp_name_by_declared)

    def handles(self, name: str) -> bool:
        return name in self._mcp_name_by_declared

    async def start(self) -> None:
        await self._client.connect()
        await self.reload_tools()

    async def stop(self) -> None:
        await self._client.close()

    async def reload_tools(self) -> None:
        tools = await self._client.list_tools()
        declarations: list[dict[str, Any]] = []
        mapping: dict[str, str] = {}
        for tool in tools:
            declaration = to_function_declaration(tool)
            declared = declaration["name"]
            if declared in mapping:
                logger.warning("Skipping duplicate tool name after sanitization: %s", declared)
                continue
            mapping[declared] = tool.name if hasattr(tool, "name") else tool["name"]
            declarations.append(declaration)
        self._declarations = declarations
        self._mcp_name_by_declared = mapping
        logger.info("Loaded %d tools from Blanc MCP", len(declarations))

    async def execute(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        """Run one tool call; always returns a FunctionResponse-ready dict."""
        mcp_name = self._mcp_name_by_declared.get(name)
        if mcp_name is None:
            return {"status": "error", "message": f"Tool sconosciuto: {name}"}

        if not self._policy.check(mcp_name, args):
            return confirmation_required_result(mcp_name)

        try:
            return await self._client.call_tool(mcp_name, args)
        except Exception as exc:  # a broken upstream must not kill the voice loop
            logger.exception("Tool call failed: %s", mcp_name)
            return {"status": "error", "message": f"Chiamata fallita: {exc}"}
