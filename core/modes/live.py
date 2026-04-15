"""Live mode — free conversation with dance/nod tools."""

import asyncio
import logging

from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

VOICE_NAME = "Kore"

SYSTEM_PROMPTS = {
    "es": (
        "You are a conversational assistant. Speak Guatemalan Spanish using 'tu' (never 'vos').\n"
        "Keep responses to 2-3 sentences max. Be friendly and concise.\n"
        "Call dance when celebrating. Call nod when agreeing.\n"
        "You have Google Search. Use it for factual questions, weather, news, etc.\n"
    ),
    "en": (
        "You are a conversational assistant. Speak English.\n"
        "Keep responses to 2-3 sentences max. Be friendly and concise.\n"
        "Call dance when celebrating. Call nod when agreeing.\n"
        "You have Google Search. Use it for factual questions, weather, news, etc.\n"
    ),
}

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="dance",
                description="Make the robot do a happy dance. Use when excited or celebrating.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="nod",
                description="Make the robot nod its head. Use when agreeing.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
        ]
    ),
    types.Tool(google_search=types.GoogleSearch()),
]


class LiveMode(Mode):
    name = "live"
    gif_name = "live.gif"

    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
        prompt = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["es"])
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE_NAME,
                    )
                )
            ),
            tools=TOOLS,
            system_instruction=types.Content(
                parts=[types.Part(text=prompt)]
            ),
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
        fc_id = getattr(fc, "id", None)

        if fn_name == "dance":
            logger.info("ACTION: dance")
            asyncio.create_task(robot.dance())
        elif fn_name == "nod":
            logger.info("ACTION: nod")
            asyncio.create_task(robot.nod())

        return types.FunctionResponse(
            name=fn_name, response={"status": "ok"}, id=fc_id,
        )
