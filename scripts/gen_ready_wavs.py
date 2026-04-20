"""Generate assets/ready_en.wav and assets/ready_es.wav using Gemini Live (Kore)."""

import asyncio
import os
import sys
import wave
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

LIVE_MODEL = "gemini-3.1-flash-live-preview"
VOICE_NAME = "Kore"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SAMPLE_RATE = 24000  # Gemini Live output rate

TARGETS = [
    ("en", "Ready.", ASSETS_DIR / "ready_en.wav"),
    ("es", "Listo.", ASSETS_DIR / "ready_es.wav"),
]


async def render(text: str, out_path: Path) -> None:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
            )
        ),
        system_instruction=types.Content(parts=[types.Part(
            text=(
                "You are a text-to-speech system. Repeat the user's text VERBATIM, "
                "character by character. Do not paraphrase, translate, or substitute. "
                "Output ONLY the spoken audio of the exact word provided."
            )
        )]),
    )
    pcm_chunks: list[bytes] = []
    async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
        await session.send_realtime_input(text=text)
        async for response in session.receive():
            if response.data:
                pcm_chunks.append(response.data)
            sc = getattr(response, "server_content", None)
            if sc and getattr(sc, "turn_complete", False):
                break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(pcm_chunks))
    print(f"Wrote {out_path} ({sum(len(c) for c in pcm_chunks)} bytes)")


async def main() -> None:
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not set")
    for lang, text, out in TARGETS:
        await render(text, out)


if __name__ == "__main__":
    asyncio.run(main())
