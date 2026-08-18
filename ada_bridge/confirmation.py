"""Two-phase voice confirmation for write actions.

A voice assistant with company-wide tool access must not fire side-effecting
calls off a half-heard sentence. Policy: the first invocation of a write tool
returns `confirmation_required` (the model relays it and asks the user out
loud); repeating the identical call within the TTL executes it. Read tools
pass straight through.

Write/read classification leans on the Blanc MCP naming convention
`<module>_<verb>_<object>` and falls back to treating unknown verbs as writes.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

READ_VERBS = {
    "get",
    "list",
    "search",
    "read",
    "describe",
    "fetch",
    "find",
    "lookup",
    "check",
    "count",
    "preview",
    "status",
}


def is_write_tool(name: str) -> bool:
    """Unknown verbs count as writes: fail closed, not open.

    Tool names follow `<module>_<object>_<verb>` (e.g. `ghl_contacts_list`),
    but the verb position is not fully consistent across modules, so any
    read-verb token after the module prefix marks the tool as read-only.
    """
    tokens = [t.lower() for t in name.split("_")[1:]] or [name.lower()]
    return not any(t in READ_VERBS for t in tokens)


def _fingerprint(name: str, args: dict[str, Any] | None) -> str:
    canonical = json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{name}:{canonical}".encode()).hexdigest()


class ConfirmationPolicy:
    """Tracks pending write calls awaiting a repeated (confirmed) invocation."""

    def __init__(
        self,
        ttl_seconds: float = 120.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._pending: dict[str, float] = {}

    def check(self, name: str, args: dict[str, Any] | None) -> bool:
        """Return True if the call may execute now.

        Returns False the first time a write call is seen; the same call
        repeated within the TTL is treated as confirmed and allowed through.
        """
        if not is_write_tool(name):
            return True

        now = self._clock()
        key = _fingerprint(name, args)
        armed_at = self._pending.pop(key, None)
        if armed_at is not None and now - armed_at <= self._ttl:
            return True

        self._prune(now)
        self._pending[key] = now
        return False

    def reset(self) -> None:
        self._pending.clear()

    def _prune(self, now: float) -> None:
        expired = [k for k, t in self._pending.items() if now - t > self._ttl]
        for key in expired:
            del self._pending[key]


def confirmation_required_result(name: str) -> dict[str, Any]:
    """Payload the model receives instead of executing an unconfirmed write."""
    return {
        "status": "confirmation_required",
        "message": (
            f"Il tool '{name}' modifica dati aziendali. Riassumi ad alta voce "
            "all'utente esattamente cosa stai per fare e chiedi conferma. "
            "Solo dopo un sì esplicito, richiama lo stesso tool con gli "
            "stessi identici argomenti per eseguire l'azione."
        ),
    }
