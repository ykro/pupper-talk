"""Quiz mode — trivia with structured JSON generation via generateContent."""

import asyncio
import json
import logging

from google import genai
from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-3.1-flash-lite-preview"
VOICE_NAME = "Kore"

SYSTEM_PROMPTS = {
    "es": (
        "You are a quiz master. Speak Guatemalan Spanish using 'tu' (never 'vos').\n"
        "Call generate_question to get a trivia question. Read it with the options.\n"
        "When the user answers, call check_answer with their letter.\n"
        "Say if correct, share the fun fact, say the score. Then generate next question.\n"
        "Be brief. Start the quiz immediately.\n"
    ),
    "en": (
        "You are a quiz master. Speak English.\n"
        "Call generate_question to get a trivia question. Read it with the options.\n"
        "When the user answers, call check_answer with their letter.\n"
        "Say if correct, share the fun fact, say the score. Then generate next question.\n"
        "Be brief. Start the quiz immediately.\n"
    ),
}

QUIZ_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "question": types.Schema(type="STRING", description="The trivia question."),
        "options": types.Schema(
            type="ARRAY", items=types.Schema(type="STRING"),
            description="Four answer options labeled a, b, c, d.",
        ),
        "correct": types.Schema(
            type="STRING", enum=["a", "b", "c", "d"],
            description="The correct answer letter.",
        ),
        "fun_fact": types.Schema(
            type="STRING", description="A fun fact related to the answer.",
        ),
    },
    required=["question", "options", "correct", "fun_fact"],
)

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="generate_question",
                description="Generate a new trivia question.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="check_answer",
                description="Check if the user's answer is correct.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "user_answer": types.Schema(
                            type="STRING",
                            description="The letter the user chose (a, b, c, or d).",
                        ),
                    },
                    required=["user_answer"],
                ),
            ),
        ]
    )
]


class QuizState:
    def __init__(self):
        self.current_question: dict | None = None
        self.score = 0
        self.total = 0
        self.previous_topics: list[str] = []


QUIZ_GREETINGS = {
    "es": "Empieza el quiz. Genera la primera pregunta de trivia y leela con las opciones.",
    "en": "Start the quiz. Generate the first trivia question and read it with the options.",
}


class QuizMode(Mode):
    name = "quiz"
    gif_name = "quiz.gif"

    def __init__(self):
        self._state = QuizState()
        self._lang = "es"

    def get_greeting(self, lang: str) -> str:
        return QUIZ_GREETINGS.get(lang, QUIZ_GREETINGS["es"])

    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
        self._lang = lang
        prompt = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["es"])
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
                )
            ),
            tools=TOOLS,
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
        fn_name = fc.name
        fn_args = dict(fc.args) if fc.args else {}
        fc_id = getattr(fc, "id", None)

        if fn_name == "generate_question":
            q = await self._generate_question(client)
            options_str = "; ".join(q["options"])
            return types.FunctionResponse(
                name=fn_name,
                response={"question": q["question"], "options": options_str, "number": self._state.total + 1},
                id=fc_id,
            )

        elif fn_name == "check_answer":
            q = self._state.current_question
            if q is None:
                return types.FunctionResponse(
                    name=fn_name, response={"error": "No question generated yet. Call generate_question first."},
                    id=fc_id,
                )
            user_answer = fn_args.get("user_answer", "?").strip().lower()
            self._state.total += 1
            correct = q["correct"]
            is_correct = user_answer == correct

            if is_correct:
                self._state.score += 1
                asyncio.create_task(robot.dance())

            logger.info("Answer: %s (correct: %s) — %s", user_answer, correct,
                        "CORRECT" if is_correct else "WRONG")
            return types.FunctionResponse(
                name=fn_name,
                response={
                    "is_correct": is_correct, "correct_answer": correct,
                    "fun_fact": q["fun_fact"] if q else "",
                    "score": self._state.score, "total": self._state.total,
                },
                id=fc_id,
            )

        return types.FunctionResponse(name=fn_name, response={"status": "ok"}, id=fc_id)

    async def _generate_question(self, client: genai.Client) -> dict:
        state = self._state
        avoid = ", ".join(state.previous_topics[-5:]) if state.previous_topics else "none"
        if self._lang == "es":
            prompt = f"Genera una pregunta de trivia. Evita estos temas: {avoid}. Responde en espanol."
            sys_prompt = "Generate trivia questions in Spanish. Topics: science, geography, history, pop culture, Guatemala, technology."
        else:
            prompt = f"Generate a trivia question. Avoid these topics: {avoid}. Respond in English."
            sys_prompt = "Generate trivia questions in English. Topics: science, geography, history, pop culture, technology, space."

        response = await client.aio.models.generate_content(
            model=TEXT_MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=sys_prompt,
                response_mime_type="application/json",
                response_schema=QUIZ_SCHEMA,
            ),
        )
        try:
            q = json.loads(response.text)
            state.current_question = q
            state.previous_topics.append(q["question"][:30])
            logger.info("Generated question: %s", q["question"])
            return q
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to parse question: %s", exc)
            fallback = {
                "question": "What is 2 + 2?" if self._lang == "en" else "Cuanto es 2 + 2?",
                "options": ["a) 3", "b) 4", "c) 5", "d) 6"],
                "correct": "b",
                "fun_fact": "Math is fun!" if self._lang == "en" else "Las mates son divertidas!",
            }
            state.current_question = fallback
            return fallback

    async def on_enter(self, **kwargs) -> None:
        self._state = QuizState()
        self._lang = kwargs.get("lang", "es")
