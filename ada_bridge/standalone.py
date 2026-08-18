"""Standalone voice loop: talk to the company brain without the ADA v2 UI.

Minimal counterpart of ada_v2's AudioLoop — microphone in, speaker out,
Gemini Live native audio in the middle, every Blanc MCP tool available.
Run with `python -m ada_bridge.standalone` on a machine with mic + speakers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback

from .bridge import AdaMcpBridge
from .config import BridgeConfig
from .persona import system_instruction

logger = logging.getLogger(__name__)

SEND_SAMPLE_RATE = 16_000
RECEIVE_SAMPLE_RATE = 24_000
CHUNK_SIZE = 1_024
AUDIO_FORMAT_BYTES = 2  # 16-bit PCM


def _load_audio_deps():
    try:
        import pyaudio  # noqa: PLC0415
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            f"Dipendenza mancante: {exc.name}. "
            "Installa con: pip install -r requirements.txt "
            "(pyaudio richiede portaudio: `brew install portaudio` su macOS, "
            "`apt install portaudio19-dev` su Debian/Ubuntu)."
        ) from exc
    return pyaudio, genai, types


class VoiceLoop:
    def __init__(self, config: BridgeConfig) -> None:
        self._config = config
        self._bridge = AdaMcpBridge(config)
        self._audio_out: asyncio.Queue[bytes] = asyncio.Queue()
        self._session = None

    async def run(self) -> None:
        pyaudio, genai, types = _load_audio_deps()
        await self._bridge.start()
        logger.info(
            "Bridge pronto: %d tool aziendali disponibili a voce",
            len(self._bridge.declarations),
        )

        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self._config.voice
                )
            ),
            **(
                {"language_code": self._config.language_code}
                if self._config.language_code
                else {}
            ),
        )
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
            system_instruction=system_instruction(self._config.user_title),
            tools=[{"function_declarations": self._bridge.declarations}],
            output_audio_transcription={},
            input_audio_transcription={},
        )

        client = genai.Client(api_key=self._config.gemini_api_key)
        pa = pyaudio.PyAudio()
        try:
            async with client.aio.live.connect(
                model=self._config.model, config=live_config
            ) as session:
                self._session = session
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._listen(pa, pyaudio.paInt16))
                    tg.create_task(self._receive())
                    tg.create_task(self._play(pa, pyaudio.paInt16))
        finally:
            pa.terminate()
            await self._bridge.stop()

    async def _listen(self, pa, sample_format) -> None:
        from google.genai import types  # noqa: PLC0415

        stream = await asyncio.to_thread(
            pa.open,
            format=sample_format,
            channels=1,
            rate=SEND_SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False
                )
                await self._session.send_realtime_input(
                    audio=types.Blob(
                        data=data, mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}"
                    )
                )
        finally:
            stream.close()

    async def _receive(self) -> None:
        from google.genai import types  # noqa: PLC0415

        while True:
            async for response in self._session.receive():
                server_content = response.server_content
                if server_content is not None:
                    if server_content.interrupted:
                        # Drop queued audio so barge-in feels instant.
                        while not self._audio_out.empty():
                            self._audio_out.get_nowait()
                    for part in (
                        server_content.model_turn.parts
                        if server_content.model_turn
                        else []
                    ):
                        if part.inline_data and part.inline_data.data:
                            self._audio_out.put_nowait(part.inline_data.data)
                    transcript = server_content.output_transcription
                    if transcript and transcript.text:
                        print(f"ADA: {transcript.text}", end="", flush=True)

                if response.tool_call:
                    responses = []
                    for fc in response.tool_call.function_calls:
                        logger.info("Tool call: %s(%s)", fc.name, fc.args)
                        result = await self._bridge.execute(fc.name, dict(fc.args or {}))
                        responses.append(
                            types.FunctionResponse(
                                id=fc.id, name=fc.name, response=result
                            )
                        )
                    await self._session.send_tool_response(
                        function_responses=responses
                    )

    async def _play(self, pa, sample_format) -> None:
        stream = await asyncio.to_thread(
            pa.open,
            format=sample_format,
            channels=1,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            while True:
                chunk = await self._audio_out.get()
                await asyncio.to_thread(stream.write, chunk)
        finally:
            stream.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = BridgeConfig.from_env(require_gemini=True)
    print(
        f"ADA in ascolto (voce: {config.voice}, modello: {config.model}).\n"
        "Parla in italiano; Ctrl+C per uscire."
    )
    try:
        asyncio.run(VoiceLoop(config).run())
    except KeyboardInterrupt:
        print("\nArrivederci.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
