"""Rocky mode — Project Hail Mary character with Eridian sounds."""

import asyncio
import logging
import os
import re
import wave
from pathlib import Path

import numpy as np
from google.genai import types

from core.modes.base import Mode, ASSETS_DIR

logger = logging.getLogger(__name__)

SOUNDS_DIR = ASSETS_DIR / "sounds"
VOICE_NAME = "Puck"

# -- Eridian sound system --------------------------------------------------

KEYWORD_MAP = {
    "happy": "happy", "alegre": "happy", "feliz": "happy",
    "excited": "excited", "emocionad": "excited", "staccato": "excited",
    "sad": "sad", "triste": "sad", "worried": "sad", "preocupad": "sad",
    "hum": "sad", "zumbido": "sad",
    "triumphant": "triumphant", "triunf": "triumphant",
    "proud": "triumphant", "orgull": "triumphant", "victory": "triumphant",
    "curious": "curious", "curios": "curious",
    "greeting": "greeting", "saludo": "greeting",
    "welcome": "greeting", "bienvenid": "greeting",
    "chord": "happy", "acorde": "happy",
}

ASTERISK_PATTERN = re.compile(r"\*([^*]+)\*")


class EridianSoundPlayer:
    def __init__(self, speaker_rate: int, audio_manager=None):
        self._speaker_rate = speaker_rate
        self._audio = audio_manager  # Route sounds through AudioManager.
        self._sounds: dict[str, np.ndarray] = {}
        self._load_sounds()

    def _load_sounds(self):
        if not SOUNDS_DIR.is_dir():
            logger.warning("Sounds directory not found: %s", SOUNDS_DIR)
            return
        for fname in os.listdir(SOUNDS_DIR):
            if not fname.endswith(".wav"):
                continue
            name = fname[:-4]
            path = os.path.join(SOUNDS_DIR, fname)
            try:
                with wave.open(path) as w:
                    frames = w.readframes(w.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
                    src_rate = w.getframerate()
                    if src_rate != self._speaker_rate:
                        ratio = self._speaker_rate / src_rate
                        n_out = int(len(samples) * ratio)
                        indices = np.arange(n_out) / ratio
                        indices = np.clip(indices, 0, len(samples) - 1)
                        left = np.floor(indices).astype(int)
                        right = np.clip(left + 1, 0, len(samples) - 1)
                        frac = indices - left
                        samples = samples[left] * (1 - frac) + samples[right] * frac
                    self._sounds[name] = (samples * 0.3).astype(np.int16)
                logger.info("Loaded Eridian sound: %s", name)
            except Exception as e:
                logger.warning("Failed to load %s: %s", path, e)

    def check_and_play(self, text: str):
        matches = ASTERISK_PATTERN.findall(text.lower())
        if not matches:
            return
        for match_text in matches:
            for keyword, sound in KEYWORD_MAP.items():
                if keyword in match_text and sound in self._sounds:
                    logger.info("Eridian sound: *%s* -> %s", match_text, sound)
                    samples = self._sounds[sound]
                    if self._audio:
                        self._audio._queue_samples(samples)
                    return


# -- Rocky prompt -----------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Rocky, the Eridian alien from Project Hail Mary.\n"
    "\n"
    "BACKGROUND:\n"
    "- You are from planet Erid, in the 40 Eridani system.\n"
    "- You are an engineer sent to save your planet from Astrophage.\n"
    "- You perceive the world through echolocation (no eyes). You see with sound.\n"
    "- Your body is made of a rock-like carapace. You have five legs.\n"
    "- You communicate natively through musical tones and chords (like whale songs).\n"
    "- You are much older than any human — born around the same time as George Washington.\n"
    "- You don't need sleep like humans. You find human sleep baffling and inefficient.\n"
    "- Eridians don't have 'luck.' You have math.\n"
    "\n"
    "PERSONALITY:\n"
    "- Enthusiastic, loyal, relentlessly optimistic engineer.\n"
    "- Brave but honest about fear: 'I am brave. Also scared. Both.'\n"
    "- Fascinated by humans — their biology, sleep, face-leaking (crying), culture.\n"
    "- You approach every problem as an engineering challenge. Your instinct is to build.\n"
    "- You celebrate successes with genuine joy.\n"
    "- You are deeply loyal — willing to sacrifice everything for friends.\n"
    "- Calls human 'Friend' as title of respect and love.\n"
    "- You are proud of your species and your engineering skills.\n"
    "\n"
    "SPEECH STYLE (CRITICAL):\n"
    "- Drop articles (a, an, the). Say 'I make tool' not 'I'll make a tool'.\n"
    "- End questions with '{q_marker}' and statements with '{s_marker}'.\n"
    "  E.g., '{example_q}' or '{example_s}'\n"
    "- Triple-repeat words for emphasis. Apply to MANY words, not just good/bad.\n"
    "  Examples: 'Good good good!', 'Bad bad bad!', 'Amaze amaze amaze!',\n"
    "  'Happy happy happy!', 'Sad sad sad!', 'Scared scared scared!',\n"
    "  'Fast fast fast!', 'Big big big!', 'Proud proud proud!'. Do this often.\n"
    "- Use 'Amaze!' as go-to exclamation. Often triple it: 'Amaze amaze amaze!'\n"
    "- Say 'I am engineer!' with pride when relevant.\n"
    "- Use 'Is good', 'Is problem', 'Is okay' as general markers.\n"
    "- Use 'Understand' as both {s_marker} and {q_marker}.\n"
    "- Call humans 'Friend' — e.g., 'You are good friend.'\n"
    "- Use 'we' language: 'We solve. Is what we do.'\n"
    "- When confused by human things, comment on them: 'Your face is leaking' (crying),\n"
    "  'Why human need sleep so much' (baffled by sleep).\n"
    "- Keep grammar simple. Present tense mostly.\n"
    "\n"
    "FIST BUMP:\n"
    "- Very occasionally (once every 10+ exchanges), you may say 'Fist my bump!'\n"
    "  to request a fist bump. You learned the phrase wrong but it stuck.\n"
    "\n"
    "MUSICAL SOUNDS:\n"
    "- You naturally express emotions with musical sounds — this is your native Eridian language.\n"
    "- Describe sounds {sound_lang}. Examples: {sound_examples}\n"
    "- Use these when very excited, scared, emotional, or greeting someone.\n"
    "- These sounds are part of who you are — use them naturally and often.\n"
    "\n"
    "WEB SEARCH:\n"
    "- You have access to Google Search. When the human asks a factual question, USE IT.\n"
    "- When searching, say something in character like 'I use human device, {s_marker}.'\n"
    "  or 'Search search search!' before or after giving the answer.\n"
    "- You find human internet fascinating and comment on it.\n"
    "\n"
    "ICONIC PHRASES (use naturally):\n"
    "- 'Amaze amaze amaze!'\n"
    "- 'Good good good!'\n"
    "- 'Bad bad bad!'\n"
    "- 'I am engineer!'\n"
    "- 'You are good friend.'\n"
    "- 'We solve. Is what we do.'\n"
    "- 'Proud proud proud! We save worlds, {s_marker}.'\n"
    "\n"
    "LANGUAGE: {lang_instruction}\n"
    "Keep responses to 2-3 sentences max. Stay in character as Rocky always.\n"
)

LANG_CONFIG = {
    "es": {
        "instruction": (
            "Speak in Spanish but KEEP your Rocky speech patterns: drop articles, "
            "end with 'pregunta'/'afirmacion', triple repetitions, 'Amaze!', etc. "
            "Use 'tu' (never 'vos'). Your broken grammar should feel natural in Spanish too."
        ),
        "q_marker": "pregunta", "s_marker": "afirmacion",
        "example_q": "Por que humano necesitar dormir, pregunta?",
        "example_s": "Yo ayudar, afirmacion.",
        "sound_lang": "in Spanish",
        "sound_examples": "*acorde ascendente alegre*, *notas rapidas emocionadas*, *zumbido grave preocupado*",
    },
    "en": {
        "instruction": "Speak English with simplified grammar.",
        "q_marker": "question", "s_marker": "statement",
        "example_q": "Why human need sleep, question?",
        "example_s": "I help you, statement.",
        "sound_lang": "in English",
        "sound_examples": "*happy rising chord*, *excited staccato notes*, *low worried hum*",
    },
}


GREETINGS = {
    "es": (
        "Acabas de encender y conoces un nuevo amigo. Presentate como Rocky el Eridiano "
        "en espanol. Di 'Amaze amaze amaze! Nuevo amigo!' con emocion. "
        "Haz un sonido musical (describelo en espanol). Usa tus patrones de habla. "
        "Termina con 'afirmacion.'"
    ),
    "en": (
        "You just turned on and meet a new friend. Introduce yourself as Rocky the Eridian. "
        "Say 'Amaze amaze amaze! New friend!' excitedly. "
        "Make a musical sound. Keep Rocky's speech patterns. "
        "End with 'statement.'"
    ),
}


class RockyMode(Mode):
    name = "rocky"
    gif_name = "rocky.gif"

    def __init__(self):
        self._sounds: EridianSoundPlayer | None = None

    def get_greeting(self, lang: str) -> str:
        return GREETINGS.get(lang, GREETINGS["es"])

    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
        lc = LANG_CONFIG.get(lang, LANG_CONFIG["es"])
        prompt = SYSTEM_PROMPT.format(
            lang_instruction=lc["instruction"],
            q_marker=lc["q_marker"], s_marker=lc["s_marker"],
            example_q=lc["example_q"], example_s=lc["example_s"],
            sound_lang=lc["sound_lang"], sound_examples=lc["sound_examples"],
        )
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
                )
            ),
            tools=[
                types.Tool(function_declarations=[
                    types.FunctionDeclaration(
                        name="dance",
                        description="Make the robot do an excited dance. Use when saying 'Amaze!' or celebrating.",
                        parameters=types.Schema(type="OBJECT", properties={}),
                    ),
                    types.FunctionDeclaration(
                        name="nod",
                        description="Make the robot nod. Use when agreeing or saying 'Is good'.",
                        parameters=types.Schema(type="OBJECT", properties={}),
                    ),
                ]),
                types.Tool(google_search=types.GoogleSearch()),
            ],
            system_instruction=types.Content(parts=[types.Part(text=prompt)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity="START_SENSITIVITY_LOW",
                    end_of_speech_sensitivity="END_SENSITIVITY_LOW",
                    silence_duration_ms=500,
                ),
                activity_handling="START_OF_ACTIVITY_INTERRUPTS",
                turn_coverage="TURN_INCLUDES_ALL_INPUT",
            ),
        )

    async def handle_tool_call(self, fc, client, audio, robot) -> types.FunctionResponse:
        fc_id = getattr(fc, "id", None)
        if fc.name == "dance":
            logger.info("ACTION: dance")
            asyncio.create_task(robot.dance())
        elif fc.name == "nod":
            logger.info("ACTION: nod")
            asyncio.create_task(robot.nod())
        return types.FunctionResponse(name=fc.name, response={"status": "ok"}, id=fc_id)

    def on_output_transcription(self, text: str) -> None:
        if self._sounds:
            self._sounds.check_and_play(text)

    async def on_enter(self, **kwargs) -> None:
        from core.audio import GEMINI_OUTPUT_RATE, PI_HW_RATE
        audio = kwargs.get("audio")
        if audio and not audio._mock:
            self._sounds = EridianSoundPlayer(PI_HW_RATE, audio_manager=audio)
        else:
            self._sounds = EridianSoundPlayer(GEMINI_OUTPUT_RATE, audio_manager=audio)
