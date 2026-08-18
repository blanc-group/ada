"""ADA <-> Blanc MCP voice bridge.

Lazy exports keep `mcp`/`google-genai` optional at import time, so the pure
modules (tool_mapper, confirmation, persona, config) stay usable in tests and
in environments without the runtime dependencies installed.
"""

from __future__ import annotations

from .config import BridgeConfig, ConfigError
from .persona import system_instruction

__all__ = ["AdaMcpBridge", "BridgeConfig", "ConfigError", "system_instruction"]


def __getattr__(name: str):
    if name == "AdaMcpBridge":
        from .bridge import AdaMcpBridge

        return AdaMcpBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
