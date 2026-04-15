"""Vosk-based hotword detector — runs in background, bilingual (EN + ES)."""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

KEYWORDS = {
    "pausa": "pause",
    "pause": "pause",
    "activo": "resume",
    "active": "resume",
    "go rocky": "switch:rocky",
    "go bumblebee": "switch:bumblebee",
    "go vision": "switch:vision",
    "go quiz": "switch:quiz",
    "go code": "switch:code",
    "go live": "switch:live",
    "go sentiment": "switch:sentiment",
    "go pixel": "switch:sentiment",
}

# Vosk models directory (downloaded once).
MODELS_DIR = Path(__file__).resolve().parent.parent / "vosk-models"


def _find_model(lang_prefix: str) -> str | None:
    """Find a Vosk model directory matching lang prefix."""
    if not MODELS_DIR.exists():
        return None
    for d in sorted(MODELS_DIR.iterdir()):
        if d.is_dir() and lang_prefix in d.name:
            return str(d)
    return None


class VoskHotwordDetector:
    """Bilingual hotword detector using Vosk small models."""

    def __init__(self, command_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self._queue = command_queue
        self._loop = loop
        self._recognizers = []
        self._last_command: str | None = None

        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)  # Suppress Vosk logs.

            for prefix in ("en", "es"):
                model_path = _find_model(prefix)
                if model_path:
                    model = Model(model_path)
                    rec = KaldiRecognizer(model, 16000)
                    rec.SetWords(True)
                    self._recognizers.append((prefix, rec))
                    logger.info("Vosk %s model loaded: %s", prefix, model_path)
                else:
                    logger.warning("Vosk model not found for %s in %s", prefix, MODELS_DIR)

        except ImportError:
            logger.warning("vosk not installed — hotword detection unavailable")
        except Exception as exc:
            logger.warning("Vosk init error: %s", exc)

    @property
    def available(self) -> bool:
        return len(self._recognizers) > 0

    def feed_audio(self, pcm_bytes: bytes) -> None:
        """Feed 16kHz PCM to all recognizers. Called from mic thread."""
        for lang, rec in self._recognizers:
            if rec.AcceptWaveform(pcm_bytes):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip().lower()
                self._check_keywords(text)
            else:
                partial = json.loads(rec.PartialResult())
                text = partial.get("partial", "").strip().lower()
                self._check_keywords(text, partial=True)

    def _check_keywords(self, text: str, partial: bool = False) -> None:
        if not text:
            return

        for keyword, command in KEYWORDS.items():
            if keyword in text:
                # Avoid duplicate commands from partial + final.
                if command == self._last_command and partial:
                    continue
                self._last_command = command
                logger.info("HOTWORD detected: '%s' -> %s (partial=%s)", keyword, command, partial)
                try:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, command)
                except Exception:
                    pass
                return

        # Reset last command if no keyword found in final result.
        if not partial:
            self._last_command = None
