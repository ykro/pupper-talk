"""Generalized streaming logic for Gemini Live API — works with any Mode."""

import asyncio
import logging

import numpy as np
from google.genai import types

from core.audio import AudioManager
from core.modes.base import Mode

logger = logging.getLogger(__name__)

INTERRUPT_RMS = 1500


async def stream_microphone(session, audio: AudioManager) -> None:
    """Stream mic audio to Gemini Live API with echo suppression."""
    async for chunk in audio.start_mic_stream():
        try:
            if audio.suppressing:
                data = audio._silence
            elif audio.speaking:
                samples = np.frombuffer(chunk, dtype=np.int16)
                rms = int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                data = chunk if rms > INTERRUPT_RMS else audio._silence
            else:
                data = chunk
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error sending mic audio: %s", exc)


async def handle_responses(
    session, audio: AudioManager, mode: Mode, client, robot,
    command_queue: asyncio.Queue | None = None,
) -> None:
    """Handle Gemini responses: audio + tool calls dispatched to Mode."""
    pending_tool_responses: list[types.FunctionResponse] = []
    switching = False
    try:
        while True:
            async for response in session.receive():
                # After a switch command, ignore everything until cancelled.
                if switching:
                    continue

                has_tool = bool(getattr(response, "tool_call", None))
                server_content = getattr(response, "server_content", None)

                if not has_tool and pending_tool_responses:
                    try:
                        await session.send_tool_response(
                            function_responses=pending_tool_responses
                        )
                    except Exception as exc:
                        logger.error("Error sending tool response: %s", exc)
                    pending_tool_responses = []

                if server_content:
                    if getattr(server_content, "interrupted", False):
                        logger.info("Interrupted — flushing speaker")
                        audio.flush_speaker()

                    input_tx = getattr(server_content, "input_transcription", None)
                    output_tx = getattr(server_content, "output_transcription", None)
                    if input_tx and getattr(input_tx, "text", None):
                        logger.info("USER: %s", input_tx.text)
                    if output_tx and getattr(output_tx, "text", None):
                        logger.info("BOT: %s", output_tx.text)
                        mode.on_output_transcription(output_tx.text)

                if response.data and not mode.suppress_voice:
                    await audio.play_audio(response.data)

                tool_call = getattr(response, "tool_call", None)
                if tool_call is not None:
                    for fc in getattr(tool_call, "function_calls", []):
                        # Intercept switch_mode — route to command_queue.
                        if fc.name == "switch_mode" and command_queue is not None:
                            target = fc.args.get("mode", "")
                            logger.info("GEMINI SWITCH: switch_mode(%s)", target)
                            command_queue.put_nowait(f"switch:{target}")
                            audio.flush_speaker()
                            switching = True
                            break

                        # Suppress mic during tool execution to prevent
                        # ambient noise from interrupting (code, quiz).
                        audio.start_suppression()
                        try:
                            fr = await mode.handle_tool_call(fc, client, audio, robot)
                        finally:
                            await audio.end_suppression()
                        pending_tool_responses.append(fr)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Response handler error: %s", exc)
