"""Thin async client for the Blanc MCP gateway (Streamable HTTP + API key)."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 20_000  # keep tool output within a voice-friendly budget


class BlancMcpClient:
    """One authenticated session against the gateway's /mcp endpoint."""

    def __init__(
        self,
        url: str,
        api_key: str,
        tenant: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        if tenant:
            self._headers["X-Blanc-Tenant"] = tenant
        if extra_headers:
            self._headers.update(extra_headers)
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        self._stack = AsyncExitStack()
        try:
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(self._url, headers=self._headers)
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
        except BaseException:
            await self.close()
            raise
        logger.info("Connected to Blanc MCP at %s", self._url)

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("BlancMcpClient not connected: call connect() first")
        return self._session

    async def list_tools(self) -> list[Any]:
        result = await self.session.list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        """Call a tool and flatten the MCP content blocks into a plain dict."""
        result = await self.session.call_tool(name, args or {})

        text_parts: list[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)
        output = "\n".join(text_parts)[:_MAX_RESULT_CHARS]

        if result.isError:
            return {"status": "error", "message": output or "Errore sconosciuto dal gateway."}
        return {"status": "ok", "output": output}
