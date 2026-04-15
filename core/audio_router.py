"""AudioRouter — routes mic audio to both Vosk and Gemini with pause/resume."""

import asyncio
import logging

import numpy as np
from google.genai import types

from core.audio import AudioManager

logger = logging.getLogger(__name__)

INTERRUPT_RMS = 800


class AudioRouter:
    """Consumes mic stream once, feeds to Vosk (always) and Gemini (with controls)."""

    def __init__(self, audio: AudioManager, hotword):
        self._audio = audio
        self._hotword = hotword
        self._session = None
        self._paused = False

    def set_session(self, session) -> None:
        """Redirect audio to a new Gemini session (on mode switch)."""
        self._session = session

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def run(self) -> None:
        """Main loop: read mic, feed to Vosk + Gemini."""
        async for chunk in self._audio.start_mic_stream():
            # Always feed Vosk (hotword detection).
            if self._hotword and self._hotword.available:
                try:
                    self._hotword.feed_audio(chunk)
                except Exception:
                    pass

            # Send to Gemini (with pause and echo suppression).
            if self._paused or self._session is None:
                continue

            try:
                if self._audio.suppressing:
                    data = self._audio._silence
                elif self._audio.speaking:
                    samples = np.frombuffer(chunk, dtype=np.int16)
                    rms = int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                    data = chunk if rms > INTERRUPT_RMS else self._audio._silence
                else:
                    data = chunk

                await self._session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Error sending mic audio: %s", exc)
