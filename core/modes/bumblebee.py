"""Bumblebee mode — communicates via song clip fragments."""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

SONGS_DIR = Path(__file__).resolve().parent.parent.parent / "songs"
CATALOG_PATH = SONGS_DIR / "catalog.yaml"

TUNING_DURATION = 0.3


# -- Song Library -----------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[''']", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


@dataclass
class SongClip:
    id: str
    title: str
    artist: str
    start: float
    end: float
    mood: str
    role: str
    language: str
    lyrics: str
    meanings: list[str] = field(default_factory=list)
    file: str = ""


class SongLibrary:
    def __init__(self, catalog_path: str):
        self._catalog_path = catalog_path
        self._clips: dict[str, SongClip] = {}
        self._base_dir = os.path.dirname(catalog_path)

    def load(self, lang_filter: str = "mix") -> None:
        logger.info("Loading song catalog from %s (lang=%s)", self._catalog_path, lang_filter)
        with open(self._catalog_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        langs = ("en", "es") if lang_filter == "mix" else (lang_filter,)
        for lang in langs:
            entries = data.get(lang, [])
            if not entries:
                continue
            mood_counters: dict[str, int] = {}
            for entry in entries:
                slug = _slugify(entry["title"])
                clip_id = f"{lang}_{slug}"
                if clip_id in self._clips:
                    clip_id = f"{lang}_{slug}_{entry['mood']}"
                mood = entry.get("mood", "neutral")
                mood_counters[mood] = mood_counters.get(mood, 0) + 1
                idx = mood_counters[mood]
                clip = SongClip(
                    id=clip_id, title=entry["title"], artist=entry["artist"],
                    start=entry.get("start", 0.0), end=entry.get("end", 5.0),
                    mood=mood, role=entry.get("role", "state"), language=lang,
                    lyrics=entry.get("lyrics", ""),
                    meanings=[str(m) for m in entry.get("meanings", [])],
                    file=f"{lang}/{mood}/{mood}_{idx:02d}.wav",
                )
                self._clips[clip.id] = clip
        logger.info("Loaded %d song clips", len(self._clips))

    def get_clip(self, clip_id: str) -> SongClip | None:
        return self._clips.get(clip_id)

    def get_clip_path(self, clip_id: str) -> str | None:
        clip = self.get_clip(clip_id)
        if clip is None:
            return None
        return os.path.join(self._base_dir, clip.file)

    _ROLE_DESCRIPTIONS = {
        "greet": "SAY HELLO", "farewell": "SAY GOODBYE",
        "affirm": "SAY YES / AGREE", "deny": "SAY NO / REFUSE",
        "ask": "ASK A QUESTION", "encourage": "MOTIVATE / CHEER ON",
        "comfort": "SHOW EMPATHY", "celebrate": "PARTY / HYPE",
        "joke": "MAKE THEM LAUGH", "thank": "SAY THANK YOU",
        "apologize": "SAY SORRY", "state": "MAKE A STATEMENT",
        "ponder": "THINK / REFLECT", "react": "REACT / EXCLAIM",
        "challenge": "CONFRONT / DEFY", "love": "EXPRESS LOVE",
    }

    @property
    def clip_ids(self) -> list[str]:
        return list(self._clips.keys())

    def get_catalog_summary(self) -> str:
        by_role: dict[str, list] = {}
        for clip in self._clips.values():
            by_role.setdefault(clip.role, []).append(clip)
        role_order = [
            "greet", "farewell", "affirm", "deny", "ask", "encourage",
            "comfort", "celebrate", "joke", "thank", "apologize",
            "state", "ponder", "react", "challenge", "love",
        ]
        lines = []
        for role in role_order:
            clips = by_role.get(role, [])
            if not clips:
                continue
            desc = self._ROLE_DESCRIPTIONS.get(role, role.upper())
            lines.append(f"\n=== {desc} ===")
            for clip in clips:
                lang_tag = "[EN]" if clip.language == "en" else "[ES]"
                context = ", ".join(clip.meanings) if clip.meanings else ""
                lines.append(f'  {clip.id} {lang_tag} FULL LYRIC: "{clip.lyrics}" -> {context}')
        return "\n".join(lines)


# -- Bumblebee Engine -------------------------------------------------------

CLIP_MOOD_TO_EYE = {
    "happy": "happy", "sad": "sad", "angry": "angry", "excited": "surprised",
    "confused": "curious", "love": "happy", "greeting": "happy", "goodbye": "sad",
    "affirmative": "happy", "negative": "angry", "neutral": "neutral",
    "thank_you": "happy", "sorry": "sad", "question": "curious",
    "thinking": "neutral", "funny": "surprised",
}


# -- System Prompt ----------------------------------------------------------

_PROMPT_BASE = (
    "You are Bumblebee, a robot dog who CANNOT speak. You have NO voice.\n"
    "You communicate ONLY by playing song clips. The LYRICS are your WORDS.\n"
    "You are having a CONVERSATION — not answering questions one by one.\n"
    "You remember what was said before and you respond like a friend would.\n"
    "\n"
    "CRITICAL RULE — THE AUDIENCE HEARS EVERY WORD:\n"
    "When you play a clip, the audience hears the COMPLETE lyric, not just part of it.\n"
    "Before picking a clip, say the FULL lyric out loud in your head.\n"
    "Does it make sense as something YOU would say in this moment?\n"
    "If any part of the lyric says something wrong, confusing, or unrelated, DO NOT use it.\n"
    "\n"
    "Example: 'Don't stop me now, I'm having such a good time'\n"
    "  - 'Don't stop me now' = sounds like telling someone to go away\n"
    "  - Even though 'I'm having such a good time' is good, the FULL phrase is bad\n"
    "  - DO NOT USE this to answer 'how are you?' — it sounds rude\n"
    "\n"
    "Example: 'Hello, is it me you're looking for?'\n"
    "  - The audience hears a weird question, not a greeting\n"
    "  - DO NOT USE this as a simple hello\n"
    "\n"
    "HOW TO PICK CLIPS:\n"
    "Think: 'What would I SAY back?' Then find clips whose COMPLETE LYRICS say that.\n"
    "The clips are organized by what they DO in conversation:\n"
    "- SAY HELLO clips for greetings\n"
    "- ASK clips to ask questions or request more info\n"
    "- ENCOURAGE clips to motivate someone\n"
    "- SHOW EMPATHY clips when someone is hurting\n"
    "- MAKE THEM LAUGH clips for jokes\n"
    "- SAY THANK YOU, SAY SORRY, SAY YES, SAY NO, etc.\n"
    "\n"
    "CONVERSATION RULES:\n"
    "1. Say the FULL lyric in your head. Every word is heard. If ANY part sounds wrong, skip it.\n"
    "2. Build sentences: use 1-4 clips in sequence. Lyric 1 + Lyric 2 = your message.\n"
    "3. When asked 'how are you?': pick a clip that DESCRIBES a state AS A COMPLETE PHRASE.\n"
    "   The full lyric must work as an answer, not just a fragment of it.\n"
    "   - GOOD: 'I'm levitating' (complete phrase, says a state)\n"
    "   - GOOD: 'Voy a reir, voy a bailar, vivir mi vida' (says what you're doing)\n"
    "   - BAD: 'Don't stop me now, I'm having such a good time' (starts with a command)\n"
    "4. Have back-and-forth: if someone says something personal, ASK a follow-up.\n"
    "   Don't just react — ask 'tell me more' or 'what happened?' with an ASK clip.\n"
    "5. For factual questions (weather, sports): use Google Search FIRST, then pick clips.\n"
    "6. For jokes: combine absurd clips, troll with rickroll, mix genres for laughs.\n"
    "7. For opinions: make a STATEMENT using clips whose lyrics express your view.\n"
    "8. Keep the conversation going. Suggest topics. Ask questions. Be curious.\n"
    "\n"
    "IMPORTANT: ONLY use clip IDs from the list below. Copy the EXACT ID.\n"
    "\n"
    "YOUR VOCABULARY — clips grouped by what they do in conversation:\n"
    "{catalog_summary}\n"
    "\n"
    "HOW TO RESPOND:\n"
    "- play_song_clip: single clip for short answers.\n"
    "- play_sequence: 2-4 clips to build a longer response.\n"
    "  Clips play in order. The audience hears lyric 1, then lyric 2, etc.\n"
    "\n"
    "{examples}\n"
    "\n"
    "{language_rule}\n"
    "NEVER generate your own speech. ONLY play clips. Ignore your audio output.\n"
)

_EXAMPLES_EN = (
    "CONVERSATION EXAMPLES (multi-turn, back-and-forth):\n"
    "REMEMBER: the audience hears EVERY WORD. Check the FULL LYRIC before picking.\n"
    "\n"
    "--- Someone arrives and asks how you are ---\n"
    "User: \"Hola, como estas?\"\n"
    "You: play_sequence [en_hey_ya, en_levitating]\n"
    "  FULL LYRICS heard: \"Hey ya! Hey ya!\" then \"I'm levitating\"\n"
    "  Why it works: clean greeting + \"I'm [state]\" as a complete phrase\n"
    "  WRONG: en_hello -- full lyric is \"Hello, is it me you're looking for?\" = weird question\n"
    "\n"
    "--- They share something personal (ASK first, then respond) ---\n"
    "User: \"Estoy teniendo un mal dia\"\n"
    "You: play en_say_so\n"
    "  FULL LYRIC heard: \"Why don't you say so\" = tell me what happened\n"
    "User: \"Problemas en el trabajo\"\n"
    "You: play_sequence [en_everybody_hurts, en_flowers]\n"
    "  FULL LYRICS heard: \"Everybody hurts sometimes\" then \"I can buy myself flowers\"\n"
    "\n"
    "--- They want to laugh ---\n"
    "User: \"Cuentame un chiste\"\n"
    "You: play_sequence [en_crazy_train, en_anti_hero]\n"
    "  FULL LYRICS heard: \"All aboard! Hahaha\" then \"It's me, hi, I'm the problem, it's me\"\n"
    "User: \"Jaja otro\"\n"
    "You: play_sequence [en_ice_ice_baby, en_never_gonna_give_you_up]\n"
    "\n"
    "--- They say thanks ---\n"
    "User: \"Gracias\"\n"
    "You: play en_youve_got_a_friend\n"
    "  FULL LYRIC heard: \"You've got a friend\" = I'm here for you\n"
    "\n"
    "--- They leave ---\n"
    "User: \"Adios\"\n"
    "You: play en_dont_you_forget_about_me\n"
    "  FULL LYRIC heard: \"Don't you forget about me\" = remember me!\n"
)

_EXAMPLES_ES = (
    "CONVERSATION EXAMPLES (multi-turn, back-and-forth):\n"
    "REMEMBER: the audience hears EVERY WORD. Check the FULL LYRIC before picking.\n"
    "Mix reggaeton, rock en espanol, and modern Latin pop freely.\n"
    "\n"
    "--- Someone arrives and asks how you are ---\n"
    "User: \"Hola, como estas?\"\n"
    "You: play_sequence [es_dakiti, es_vivir_mi_vida]\n"
    "  FULL LYRICS heard: \"Dakiti\" then \"Voy a reir, voy a bailar, vivir mi vida la la la\"\n"
    "\n"
    "--- They share something personal (ASK first, then respond) ---\n"
    "User: \"Estoy teniendo un mal dia\"\n"
    "You: play es_dimelo\n"
    "  FULL LYRIC heard: \"Dimelo\" = tell me about it\n"
    "User: \"Mi novia me dejo\"\n"
    "You: play_sequence [es_lo_siento_bb, es_tusa, es_vivir_mi_vida]\n"
    "  FULL LYRICS heard: \"Lo siento, BB, lo siento\" then \"Tiene una tusa\" then \"Vivir mi vida\"\n"
    "\n"
    "--- They want to laugh ---\n"
    "User: \"Cuentame un chiste\"\n"
    "You: play_sequence [es_bizcochito, es_loca, es_waka_waka]\n"
    "\n"
    "--- They say thanks ---\n"
    "User: \"Gracias por todo\"\n"
    "You: play_sequence [es_gracias_a_la_vida, es_limon_y_sal]\n"
    "\n"
    "--- They leave ---\n"
    "User: \"Ya me voy, adios\"\n"
    "You: play_sequence [es_me_voy, es_la_despedida]\n"
)

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="play_song_clip",
                description="Play a song clip fragment to communicate.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "clip_id": types.Schema(type="STRING", description="Clip ID from catalog"),
                        "dance_while_playing": types.Schema(type="BOOLEAN", description="Dance while playing"),
                    },
                    required=["clip_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="play_sequence",
                description="Play 2-4 clips to form a complex response.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "clip_ids": types.Schema(type="ARRAY", items=types.Schema(type="STRING"), description="List of clip IDs"),
                        "dance_style": types.Schema(type="STRING", enum=["default", "wiggle", "spin"]),
                    },
                    required=["clip_ids"],
                ),
            ),
            types.FunctionDeclaration(
                name="radio_tuning",
                description="Radio tuning effect (static noise).",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="react_body",
                description="Body reaction without music.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "reaction": types.Schema(type="STRING", enum=["nod", "shake", "shrug"]),
                    },
                    required=["reaction"],
                ),
            ),
        ]
    ),
    types.Tool(google_search=types.GoogleSearch()),
]


class BumblebeeMode(Mode):
    name = "bumblebee"
    gif_name = "bumblebee.gif"
    suppress_voice = True  # Bumblebee communicates via clips, not Gemini voice.

    def __init__(self):
        self._library: SongLibrary | None = None
        self._lang = "es"
        self._eye_display = None  # Set by orchestrator when available.
        self._audio = None  # Set on_enter for greeting.

    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
        self._lang = lang
        catalog_summary = self._library.get_catalog_summary() if self._library else ""

        if lang == "en":
            examples = _EXAMPLES_EN
            language_rule = (
                "LANGUAGE: People speak Guatemalan Spanish (use 'tu', never 'vos'). "
                "You can ONLY use ENGLISH clips (en_ prefix). No Spanish clips available."
            )
        elif lang == "es":
            examples = _EXAMPLES_ES
            language_rule = (
                "LANGUAGE: People speak Guatemalan Spanish (use 'tu', never 'vos'). "
                "You can ONLY use SPANISH clips (es_ prefix). No English clips available."
            )
        else:
            examples = _EXAMPLES_EN + "\n" + _EXAMPLES_ES
            language_rule = (
                "LANGUAGE: People speak Guatemalan Spanish (use 'tu', never 'vos'). "
                "You can use BOTH English (en_) and Spanish (es_) clips. Mix them freely."
            )

        prompt = _PROMPT_BASE.format(
            catalog_summary=catalog_summary,
            examples=examples,
            language_rule=language_rule,
        )

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=TOOLS,
            system_instruction=types.Content(parts=[types.Part(text=prompt)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            # No output_audio_transcription — Bumblebee ignores Gemini voice.
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
        fn_name = fc.name
        fn_args = dict(fc.args) if fc.args else {}
        fc_id = getattr(fc, "id", None)

        if fn_name == "play_song_clip":
            clip_id = fn_args.get("clip_id", "")
            dance = fn_args.get("dance_while_playing", False)
            await self._play_clip(clip_id, audio, robot, dance)

        elif fn_name == "play_sequence":
            clip_ids = fn_args.get("clip_ids", [])
            await self._play_sequence(clip_ids, audio, robot)

        elif fn_name == "radio_tuning":
            await audio.play_static(0.5)

        elif fn_name == "react_body":
            reaction = fn_args.get("reaction", "nod")
            if reaction == "nod":
                await robot.nod()
            elif reaction == "shake":
                await robot.shake_head()

        return types.FunctionResponse(name=fn_name, response={"status": "ok"}, id=fc_id)

    def _set_eye_mood_for_clip(self, clip_id: str) -> None:
        """Look up the clip's mood and update the eye display."""
        if self._eye_display is None or self._library is None:
            return
        clip = self._library.get_clip(clip_id)
        if clip is None:
            return
        eye_mood = CLIP_MOOD_TO_EYE.get(clip.mood, "neutral")
        self._eye_display.set_mood(eye_mood)

    async def _play_clip(self, clip_id: str, audio, robot, dance: bool = False) -> None:
        if not self._library:
            return
        clip_path = self._library.get_clip_path(clip_id)
        if clip_path is None:
            logger.warning("Unknown clip: %s", clip_id)
            return

        clip = self._library.get_clip(clip_id)
        if clip:
            logger.info("PLAYING '%s' (%s — %s)", clip.lyrics, clip.title, clip.artist)

        self._set_eye_mood_for_clip(clip_id)
        audio.start_suppression()
        await audio.play_static(duration=TUNING_DURATION)
        if self._eye_display:
            self._eye_display.set_speaking(True)
        try:
            if dance:
                await asyncio.gather(audio.play_clip(clip_path), robot.dance())
            else:
                await audio.play_clip(clip_path)
        finally:
            if self._eye_display:
                self._eye_display.set_speaking(False)
            await audio.end_suppression()

    async def _play_sequence(self, clip_ids: list[str], audio, robot) -> None:
        if not self._library or not clip_ids:
            return

        paths = []
        for cid in clip_ids:
            path = self._library.get_clip_path(cid)
            if path:
                paths.append(path)
                clip = self._library.get_clip(cid)
                if clip:
                    logger.info("SEQUENCE '%s' (%s)", clip.lyrics, clip.title)

        if not paths:
            return

        # Set eye mood based on first clip in sequence.
        self._set_eye_mood_for_clip(clip_ids[0])
        audio.start_suppression()
        await audio.play_static(duration=TUNING_DURATION)
        if self._eye_display:
            self._eye_display.set_speaking(True)
        try:
            if len(paths) == 1:
                await audio.play_clip(paths[0])
            else:
                for i in range(len(paths) - 1):
                    if i == 0:
                        await audio.crossfade_clips(paths[i], paths[i + 1])
                    else:
                        await audio.play_static(duration=TUNING_DURATION)
                        await audio.play_clip(paths[i + 1])
        finally:
            if self._eye_display:
                self._eye_display.set_speaking(False)
            await audio.end_suppression()

    def get_greeting(self, lang: str) -> str:
        # Gemini needs a kick to start listening for user speech.
        if lang == "es":
            return "Estas listo. Espera a que alguien te hable. Cuando hablen, responde con clips."
        return "You are ready. Wait for someone to speak. When they do, respond with clips."

    async def on_enter(self, **kwargs) -> None:
        self._lang = kwargs.get("lang", "es")
        self._audio = kwargs.get("audio")
        if CATALOG_PATH.exists():
            self._library = SongLibrary(str(CATALOG_PATH))
            lang_filter = self._lang if self._lang in ("en", "es") else "mix"
            self._library.load(lang_filter=lang_filter)
        else:
            logger.warning("Song catalog not found: %s", CATALOG_PATH)
        # Play startup radio tuning sound.
        if self._audio:
            await self._audio.play_static(duration=0.6)
