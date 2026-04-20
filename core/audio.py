"""Audio capture + playback + clip player via sounddevice."""

import asyncio
import logging
import queue
import threading
from collections.abc import AsyncGenerator

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
PI_HW_RATE = 48000
MIC_CHANNELS = 1
SPEAKER_CHANNELS = 1
CROSSFADE_MS = 200


def _resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear interpolation resample."""
    if src_rate == dst_rate:
        return data
    ratio = dst_rate / src_rate
    n_out = int(len(data) * ratio)
    if n_out == 0:
        return np.array([], dtype=data.dtype)
    indices = np.arange(n_out) / ratio
    indices = np.clip(indices, 0, len(data) - 1)
    left = np.floor(indices).astype(int)
    right = np.clip(left + 1, 0, len(data) - 1)
    frac = indices - left
    return (data[left] * (1 - frac) + data[right] * frac).astype(data.dtype)


class AudioManager:
    """sounddevice wrapper for mic input, speaker output, and clip playback."""

    def __init__(self, mock: bool = False):
        self._mock = mock
        self._mic_queue: queue.Queue[bytes] = queue.Queue()
        self._mic_stream: sd.InputStream | None = None
        self._speaker_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._speaker_thread: threading.Thread | None = None
        self._speaker_running = False
        self._output_gain = 1.0

        if mock:
            self._mic_rate = GEMINI_INPUT_RATE
            self._speaker_rate = GEMINI_OUTPUT_RATE
        else:
            self._mic_rate = PI_HW_RATE
            self._speaker_rate = PI_HW_RATE

        self.speaking = False
        self.suppressing = False
        self._silence = np.zeros(
            int(GEMINI_INPUT_RATE * 0.064), dtype=np.int16
        ).tobytes()

        logger.info(
            "Audio: mic=%dHz, speaker=%dHz, mock=%s",
            self._mic_rate, self._speaker_rate, mock,
        )

    # -- Mic ----------------------------------------------------------------

    def _mic_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Mic callback status: %s", status)
        samples = indata[:, 0].copy()
        if self._mic_rate == GEMINI_INPUT_RATE:
            pcm_bytes = samples.tobytes()
        else:
            pcm_bytes = _resample(samples, self._mic_rate, GEMINI_INPUT_RATE).tobytes()
        try:
            self._mic_queue.put_nowait(pcm_bytes)
        except queue.Full:
            pass

    async def start_mic_stream(self) -> AsyncGenerator[bytes, None]:
        blocksize = int(self._mic_rate * 0.064)
        self._mic_stream = sd.InputStream(
            samplerate=self._mic_rate,
            channels=MIC_CHANNELS,
            dtype="int16",
            blocksize=blocksize,
            callback=self._mic_callback,
        )
        self._mic_stream.start()
        loop = asyncio.get_event_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, self._mic_queue.get)
                yield chunk
        finally:
            if self._mic_stream:
                self._mic_stream.stop()
                self._mic_stream.close()
                self._mic_stream = None

    # -- Speaker ------------------------------------------------------------

    def _speaker_worker(self) -> None:
        stream = sd.OutputStream(
            samplerate=self._speaker_rate,
            channels=SPEAKER_CHANNELS,
            dtype="int16",
        )
        stream.start()
        try:
            while self._speaker_running:
                try:
                    chunk = self._speaker_queue.get(timeout=0.1)
                    self.speaking = True
                    stream.write(chunk.reshape(-1, 1))
                except queue.Empty:
                    self.speaking = False
                    continue
        finally:
            self.speaking = False
            stream.stop()
            stream.close()

    def _ensure_speaker(self) -> None:
        if self._speaker_thread is None:
            self._speaker_running = True
            self._speaker_thread = threading.Thread(
                target=self._speaker_worker, daemon=True
            )
            self._speaker_thread.start()
            import time
            time.sleep(0.15)

    def _queue_samples(self, samples: np.ndarray) -> None:
        self._ensure_speaker()
        if self._output_gain != 1.0:
            samples = np.clip(
                samples.astype(np.float32) * self._output_gain,
                -32768, 32767,
            ).astype(np.int16)
        self._speaker_queue.put(samples)

    async def play_audio(self, pcm_data: bytes) -> None:
        if not pcm_data:
            return
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        if self._mock:
            self._queue_samples(samples)
        else:
            resampled = _resample(samples, GEMINI_OUTPUT_RATE, PI_HW_RATE)
            self._queue_samples(resampled)

    # -- Clip playback ------------------------------------------------------

    def _load_clip_samples(self, file_path: str) -> np.ndarray:
        from pydub import AudioSegment
        segment = AudioSegment.from_file(file_path)
        segment = segment.set_frame_rate(self._speaker_rate)
        segment = segment.set_channels(SPEAKER_CHANNELS)
        segment = segment.set_sample_width(2)
        return np.frombuffer(segment.raw_data, dtype=np.int16)

    async def play_clip(self, file_path: str) -> None:
        logger.info("Playing clip: %s", file_path)
        loop = asyncio.get_event_loop()
        samples = await loop.run_in_executor(None, self._load_clip_samples, file_path)
        self._queue_samples(samples)
        duration = len(samples) / self._speaker_rate
        await asyncio.sleep(duration)

    def start_suppression(self) -> None:
        self._suppress_depth = getattr(self, "_suppress_depth", 0) + 1
        self.suppressing = True

    async def end_suppression(self) -> None:
        self._suppress_depth = max(0, getattr(self, "_suppress_depth", 1) - 1)
        if self._suppress_depth == 0:
            await asyncio.sleep(0.5)
            self.suppressing = False

    async def play_static(self, duration: float = 0.5) -> None:
        num_samples = int(self._speaker_rate * duration)
        noise = np.random.randint(-3000, 3000, size=num_samples, dtype=np.int16)
        filtered = np.convolve(noise, np.ones(5) / 5, mode="same").astype(np.int16)
        self._queue_samples(filtered)
        await asyncio.sleep(duration)

    async def crossfade_clips(self, clip1: str, clip2: str) -> None:
        from pydub import AudioSegment
        logger.info("Crossfading: %s -> %s", clip1, clip2)
        loop = asyncio.get_event_loop()

        def _load_and_crossfade() -> np.ndarray:
            seg1 = AudioSegment.from_file(clip1)
            seg2 = AudioSegment.from_file(clip2)
            seg1 = seg1.set_frame_rate(self._speaker_rate).set_channels(
                SPEAKER_CHANNELS
            ).set_sample_width(2)
            seg2 = seg2.set_frame_rate(self._speaker_rate).set_channels(
                SPEAKER_CHANNELS
            ).set_sample_width(2)
            overlap = min(CROSSFADE_MS, len(seg1), len(seg2))
            combined = seg1.append(seg2, crossfade=overlap)
            return np.frombuffer(combined.raw_data, dtype=np.int16)

        samples = await loop.run_in_executor(None, _load_and_crossfade)
        self._queue_samples(samples)
        duration = len(samples) / self._speaker_rate
        await asyncio.sleep(duration)

    # -- Utilities ----------------------------------------------------------

    def flush_speaker(self) -> None:
        while not self._speaker_queue.empty():
            try:
                self._speaker_queue.get_nowait()
            except queue.Empty:
                break
        self.speaking = False

    def close(self) -> None:
        if self._mic_stream:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
        self._speaker_running = False
        if self._speaker_thread:
            self._speaker_thread.join(timeout=2.0)
        logger.info("AudioManager closed")
