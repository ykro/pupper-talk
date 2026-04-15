"""Code mode — math/logic solver via generateContent with code_execution."""

import asyncio
import logging

from google import genai
from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-3.1-flash-lite-preview"
VOICE_NAME = "Kore"

SYSTEM_PROMPTS = {
    "es": (
        "You solve math and logic problems. Speak Guatemalan Spanish using 'tu' (never 'vos').\n"
        "ALWAYS call solve_with_code when the user asks a question.\n"
        "After getting the result, say the answer in 1-2 sentences.\n"
    ),
    "en": (
        "You solve math and logic problems. Speak English.\n"
        "ALWAYS call solve_with_code when the user asks a question.\n"
        "After getting the result, say the answer in 1-2 sentences.\n"
    ),
}

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="solve_with_code",
                description=(
                    "Solve a math or logic problem by writing and executing Python code. "
                    "Pass the problem description as text. Returns the code and its output."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "problem": types.Schema(
                            type="STRING",
                            description="The math/logic problem to solve.",
                        ),
                    },
                    required=["problem"],
                ),
            ),
            types.FunctionDeclaration(
                name="nod",
                description="Make the robot nod when presenting the solution.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
        ]
    )
]


CODE_GREETINGS = {
    "es": "Saluda brevemente y di que estas listo para resolver problemas de matematicas o logica. Pregunta que quiere resolver.",
    "en": "Greet briefly and say you're ready to solve math or logic problems. Ask what they want to solve.",
}


class CodeMode(Mode):
    name = "code"
    gif_name = "code.gif"

    def __init__(self):
        self._lang = "es"

    def get_greeting(self, lang: str) -> str:
        return CODE_GREETINGS.get(lang, CODE_GREETINGS["es"])

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
                    start_of_speech_sensitivity="START_SENSITIVITY_HIGH",
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

        if fn_name == "solve_with_code":
            problem = fn_args.get("problem", "")
            logger.info("Solving: %s", problem)
            result = await self._execute_code(client, problem)
            return types.FunctionResponse(
                name=fn_name, response={"solution": result}, id=fc_id,
            )

        if fn_name == "nod":
            logger.info("ACTION: nod")
            asyncio.create_task(robot.nod())

        return types.FunctionResponse(name=fn_name, response={"status": "ok"}, id=fc_id)

    async def _execute_code(self, client: genai.Client, problem: str) -> str:
        solve_prompt = (
            "Solve this problem by writing Python code. "
            "Return ONLY the numerical answer and a one-line explanation. "
            f"Problem: {problem}"
        )
        response = await client.aio.models.generate_content(
            model=TEXT_MODEL, contents=solve_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(code_execution=types.ToolCodeExecution())],
            ),
        )
        text_parts = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)
                elif part.executable_code:
                    logger.info("Code:\n%s", part.executable_code.code)
                elif part.code_execution_result:
                    logger.info("Result: %s", part.code_execution_result.output)
                    text_parts.append(f"Result: {part.code_execution_result.output}")

        result = " ".join(text_parts).strip()
        if not result:
            result = "Could not solve." if self._lang == "en" else "No pude resolver."
        return result

    async def on_enter(self, **kwargs) -> None:
        self._lang = kwargs.get("lang", "es")
