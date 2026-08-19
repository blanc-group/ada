"""Web voice interface: talk to the company brain from any browser.

Serves a single page with a mic button; the browser streams 16 kHz PCM over a
WebSocket, this server relays it to a Gemini Live session and pipes the
24 kHz audio replies (plus transcripts) back. Tool calls go through the shared
AdaMcpBridge, so the two-phase write confirmation applies here too.

Resilience: Gemini Live sessions die on their own (duration limits, quota,
network). The server transparently opens a new session and keeps the browser
connection alive; the page just shows a brief "reconnecting" note.

Run with `python -m ada_bridge.webapp`. Browsers only expose the microphone
on HTTPS (or localhost), so put a TLS reverse proxy (Caddy) in front in prod.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .bridge import AdaMcpBridge
from .config import BridgeConfig, ConfigError
from .persona import system_instruction

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SEND_MIME = "audio/pcm;rate=16000"
MAX_CONSECUTIVE_FAILURES = 3

# In-memory diagnostic trace of the real WS session, readable via /debugevents.
_EVENTS: "collections.deque[str]" = collections.deque(maxlen=300)


def _ev(msg: str) -> None:
    _EVENTS.append(f"{time.strftime('%H:%M:%S')} {msg}")


class _SessionClosed(Exception):
    """Gemini closed the Live session (duration limit, quota, network)."""


def create_app(config: BridgeConfig | None = None) -> FastAPI:
    # Demo mode: with no BLANC_MCP_API_KEY set, ADA runs voice-only (no company
    # tools) so the voice/persona can be tried before the gateway is wired up.
    config = config or BridgeConfig.from_env(require_gemini=True, require_mcp=False)
    password = os.environ.get("ADA_WEB_PASSWORD", "").strip()
    if not password:
        raise ConfigError(
            "Missing required environment variable ADA_WEB_PASSWORD "
            "(the shared password that protects the web page)."
        )

    bridge = AdaMcpBridge(config) if config.mcp_api_key else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if bridge is not None:
            await bridge.start()
            logger.info("ADA web ready: %d tools loaded", len(bridge.declarations))
        else:
            logger.warning(
                "BLANC_MCP_API_KEY not set: running in DEMO mode (voice only, "
                "no company tools)"
            )
        try:
            yield
        finally:
            if bridge is not None:
                await bridge.stop()

    app = FastAPI(title="ADA Voice Web", lifespan=lifespan)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "ok": True,
            "demo": bridge is None,
            "tools": len(bridge.declarations) if bridge else 0,
        }

    @app.get("/debugevents")
    async def debugevents(key: str = "", clear: int = 0) -> dict:
        if not hmac.compare_digest(key.encode(), password.encode()):
            return {"error": "unauthorized"}
        events = list(_EVENTS)
        if clear:
            _EVENTS.clear()
        return {"events": events}

    @app.get("/selftest")
    async def selftest(key: str = "", prompt: str = "", mode: str = "") -> dict:
        # Password-gated one-shot probe of the Gemini Live connection so the
        # exact failure (bad key, wrong model, rejected config, no audio) is
        # visible directly, without digging through logs.
        if not hmac.compare_digest(key.encode(), password.encode()):
            return {"ok": False, "error": "unauthorized"}
        from google import genai
        from google.genai import types

        info: dict = {"model": config.model, "voice": config.voice, "connected": False}
        try:
            live_config = _build_live_config(config, [], types)
            client = genai.Client(api_key=config.gemini_api_key)
            audio_bytes = 0
            transcript = ""
            async with client.aio.live.connect(
                model=config.model, config=live_config
            ) as session:
                info["connected"] = True
                text = prompt or "Rispondi dicendo solo: ciao."
                errors: list = []

                async def _drain(single_turn: bool) -> None:
                    nonlocal audio_bytes, transcript
                    while True:
                        async for response in session.receive():
                            sc = response.server_content
                            if not sc:
                                continue
                            if sc.model_turn:
                                for part in sc.model_turn.parts or []:
                                    if part.inline_data and part.inline_data.data:
                                        audio_bytes += len(part.inline_data.data)
                            if sc.output_transcription and sc.output_transcription.text:
                                transcript += sc.output_transcription.text
                            if sc.turn_complete and single_turn:
                                return
                        if single_turn:
                            return

                async def _send() -> None:
                    await session.send_client_content(
                        turns=types.Content(
                            role="user", parts=[types.Part(text=text)]
                        ),
                        turn_complete=True,
                    )

                if mode == "pump":
                    # Reproduce the real WS flow: a downlink task loops on
                    # session.receive() while a separate coroutine sends the turn
                    # (exactly what _pump_session does).
                    async def _down() -> None:
                        try:
                            await _drain(single_turn=False)
                        except Exception as exc:  # noqa: BLE001
                            errors.append(f"down: {type(exc).__name__}: {exc}")

                    dtask = asyncio.create_task(_down())
                    await asyncio.sleep(0.5)
                    try:
                        await _send()
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"send: {type(exc).__name__}: {exc}")
                    await asyncio.sleep(12)
                    dtask.cancel()
                    try:
                        await dtask
                    except (asyncio.CancelledError, Exception):
                        pass
                    info["errors"] = errors
                else:
                    await _send()
                    try:
                        await asyncio.wait_for(_drain(single_turn=True), timeout=20)
                    except asyncio.TimeoutError:
                        info["timeout"] = True
            info["ok"] = True
            info["audio_bytes"] = audio_bytes
            info["transcript"] = transcript
        except Exception as exc:  # noqa: BLE001 - report any failure verbatim
            info["ok"] = False
            info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    @app.websocket("/wsdebug")
    async def wsdebug(ws: WebSocket) -> None:
        # Isolation probe: replies to any client message with a fixed binary
        # blob, to check whether binary WebSocket frames survive the path
        # (e.g. an intermediary proxy) independent of Gemini.
        key = ws.query_params.get("key", "")
        if not hmac.compare_digest(key.encode(), password.encode()):
            await ws.accept()
            await ws.close(code=4401)
            return
        await ws.accept()
        await ws.send_text(json.dumps({"type": "ready"}))
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                await ws.send_bytes(b"\x5a" * 4096)
                await ws.send_text(json.dumps({"type": "sent_bin", "n": 4096}))
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await ws.close()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        key = ws.query_params.get("key", "")
        if not hmac.compare_digest(key.encode(), password.encode()):
            # Accept then close with an app code the page can distinguish
            # from a network failure.
            await ws.accept()
            await ws.close(code=4401, reason="password errata")
            return
        await ws.accept()
        try:
            await _run_session(ws, bridge, config)
        except* (WebSocketDisconnect, _SessionClosed):
            pass
        except* Exception:
            logger.exception("Voice session crashed")
            with contextlib.suppress(Exception):
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Errore interno della sessione vocale.",
                        }
                    )
                )
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    return app


def _build_live_config(config: BridgeConfig, declarations: list, types):
    speech_config = types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.voice)
        ),
        **({"language_code": config.language_code} if config.language_code else {}),
    )

    # Noise barrier: make start-of-speech detection less trigger-happy so
    # background noise doesn't open bogus turns. Fail open if the installed
    # SDK doesn't expose these knobs.
    extra: dict = {}
    try:
        extra["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                prefix_padding_ms=120,
                silence_duration_ms=700,
            )
        )
    except Exception:  # pragma: no cover - depends on SDK version
        logger.info("SDK without VAD tuning support; using defaults")

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
        system_instruction=system_instruction(
            config.user_title, demo=not declarations
        ),
        **({"tools": [{"function_declarations": declarations}]} if declarations else {}),
        output_audio_transcription={},
        input_audio_transcription={},
        **extra,
    )


async def _run_session(
    ws: WebSocket, bridge: AdaMcpBridge | None, config: BridgeConfig
) -> None:
    # Lazy import: everything else in this module works without google-genai.
    from google import genai
    from google.genai import types

    declarations = bridge.declarations if bridge else []
    live_config = _build_live_config(config, declarations, types)
    client = genai.Client(api_key=config.gemini_api_key)

    hello = {
        "tools": len(declarations),
        "tool_names": [d["name"] for d in declarations][:300],
        "demo": bridge is None,
        "model": config.model.rsplit("/", 1)[-1],
        "voice": config.voice,
    }

    first = True
    failures = 0
    while True:
        try:
            async with client.aio.live.connect(
                model=config.model, config=live_config
            ) as session:
                logger.info(
                    "Gemini Live connected (model=%s, voice=%s, tools=%d, demo=%s)",
                    config.model,
                    config.voice,
                    len(declarations),
                    bridge is None,
                )
                await ws.send_text(
                    json.dumps({"type": "ready" if first else "reconnected", **hello})
                )
                _ev(f"run: connected + {'ready' if first else 'reconnected'} sent")
                first = False
                failures = 0
                await _pump_session(ws, session, bridge, types)
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            _ev(f"run: live error {type(exc).__name__}: {exc}")
            logger.warning("Live session error: %s", exc)

        # Gemini side ended: reconnect transparently, with a cap so a broken
        # API key doesn't loop forever.
        failures += 1
        if failures > MAX_CONSECUTIVE_FAILURES:
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"type": "closed"}))
            raise _SessionClosed
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({"type": "reconnecting"}))
        await asyncio.sleep(min(1.5 * failures, 5.0))


async def _pump_session(
    ws: WebSocket, session, bridge: AdaMcpBridge | None, types
) -> None:
    """Relay audio both ways for ONE Gemini session; returns when it dies."""

    async def uplink() -> None:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code") or 1000)
            data = message.get("bytes")
            if data:
                try:
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type=SEND_MIME)
                    )
                except Exception as exc:
                    raise _SessionClosed from exc
            text = message.get("text")
            if text:
                # Control messages from the page (e.g. wake-word activation).
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = {}
                if payload.get("type") == "activate":
                    _ev("uplink: activate received")
                    logger.info("Activation received from browser (wake word)")
                    try:
                        await session.send_client_content(
                            turns=types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        text=(
                                            "[Attivazione vocale: l'utente ti ha "
                                            "appena chiamata con 'Ehi Ada'. "
                                            "Rispondi SOLO con un brevissimo "
                                            "saluto di disponibilita, ad esempio "
                                            "'Si, Signore?']"
                                        )
                                    )
                                ],
                            ),
                            turn_complete=True,
                        )
                        _ev("uplink: send_client_content OK")
                    except Exception as exc:
                        _ev(f"uplink: send ERROR {type(exc).__name__}: {exc}")
                        logger.warning("activate send failed: %s", exc)

    async def downlink() -> None:
        _ev("downlink: receive loop start")
        try:
            # session.receive() completes at every turn boundary; loop so the
            # Live session survives across turns.
            while True:
                async for response in session.receive():
                    await _handle_response(ws, session, bridge, types, response)
                _ev("downlink: turn iterator ended, looping")
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            _ev(f"downlink: error {type(exc).__name__}: {exc}")
            raise _SessionClosed from exc

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(uplink())
            tg.create_task(downlink())
    except BaseExceptionGroup as eg:
        if eg.subgroup(WebSocketDisconnect):
            raise WebSocketDisconnect(1000)
        if eg.subgroup(_SessionClosed):
            return  # caller reconnects
        raise


async def _handle_response(ws, session, bridge, types, response) -> None:
    content = response.server_content
    if content is not None:
        if content.interrupted:
            logger.info("Gemini: turn interrupted (barge-in)")
            await ws.send_text(json.dumps({"type": "interrupted"}))
        if content.model_turn:
            audio_bytes = 0
            for part in content.model_turn.parts or []:
                if part.inline_data and part.inline_data.data:
                    audio_bytes += len(part.inline_data.data)
                    await ws.send_bytes(part.inline_data.data)
            if audio_bytes:
                _ev(f"downlink: relayed {audio_bytes} audio bytes to ws")
                logger.info("Gemini -> browser: %d audio bytes", audio_bytes)
        for role, transcript in (
            ("ada", content.output_transcription),
            ("user", content.input_transcription),
        ):
            if transcript and transcript.text:
                if role == "ada":
                    logger.info("Gemini transcript: %s", transcript.text)
                await ws.send_text(
                    json.dumps(
                        {"type": "transcript", "role": role, "text": transcript.text}
                    )
                )
        if content.turn_complete:
            logger.info("Gemini: turn complete")
            await ws.send_text(json.dumps({"type": "turn_complete"}))

    if response.tool_call and bridge is not None:
        function_responses = []
        for fc in response.tool_call.function_calls:
            logger.info("Tool call: %s", fc.name)
            result = await bridge.execute(fc.name, dict(fc.args or {}))
            function_responses.append(
                types.FunctionResponse(id=fc.id, name=fc.name, response=result)
            )
        await session.send_tool_response(function_responses=function_responses)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Port precedence: ADA_WEB_PORT (explicit) > PORT (injected by PaaS hosts
    # like Render/Railway) > 8000 (local/Docker default).
    port = os.environ.get("ADA_WEB_PORT") or os.environ.get("PORT") or "8000"
    uvicorn.run(
        create_app(),
        host=os.environ.get("ADA_WEB_HOST", "0.0.0.0"),
        port=int(port),
    )


if __name__ == "__main__":
    main()
