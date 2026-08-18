"""Environment-driven configuration for the ADA <-> Blanc MCP bridge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
DEFAULT_VOICE = "Charon"  # deep, calm prebuilt voice — closest to a "Jarvis" tone
DEFAULT_MCP_URL = "http://localhost:3000/mcp"
DEFAULT_CONFIRMATION_TTL_SECONDS = 120.0


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            f"See agents/ada-voice-bridge/.env.example"
        )
    return value


@dataclass(frozen=True)
class BridgeConfig:
    """All knobs for the bridge. Build via `BridgeConfig.from_env()`."""

    mcp_url: str = DEFAULT_MCP_URL
    mcp_api_key: str = ""
    mcp_tenant: str | None = None
    gemini_api_key: str | None = None
    model: str = DEFAULT_MODEL
    voice: str = DEFAULT_VOICE
    user_title: str = "Signore"
    language_code: str | None = None  # native-audio models auto-detect language
    confirmation_ttl_seconds: float = DEFAULT_CONFIRMATION_TTL_SECONDS
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls, *, require_gemini: bool = False, require_mcp: bool = True
    ) -> "BridgeConfig":
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or None
        if require_gemini and not gemini_key:
            raise ConfigError(
                "Missing required environment variable GEMINI_API_KEY "
                "(needed to run the voice interface)."
            )
        mcp_api_key = (
            _require("BLANC_MCP_API_KEY")
            if require_mcp
            else os.environ.get("BLANC_MCP_API_KEY", "").strip()
        )
        return cls(
            mcp_url=os.environ.get("BLANC_MCP_URL", DEFAULT_MCP_URL).strip(),
            mcp_api_key=mcp_api_key,
            mcp_tenant=os.environ.get("BLANC_MCP_TENANT", "").strip() or None,
            gemini_api_key=gemini_key,
            model=os.environ.get("ADA_MODEL", DEFAULT_MODEL).strip(),
            voice=os.environ.get("ADA_VOICE", DEFAULT_VOICE).strip(),
            user_title=os.environ.get("ADA_USER_TITLE", "Signore").strip(),
            language_code=os.environ.get("ADA_LANGUAGE_CODE", "").strip() or None,
            confirmation_ttl_seconds=float(
                os.environ.get(
                    "ADA_CONFIRMATION_TTL", str(DEFAULT_CONFIRMATION_TTL_SECONDS)
                )
            ),
        )
