"""Sentiment mode — emotional robot dog that reacts to voice sentiment."""

import asyncio
import logging

from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

VOICE_NAME = "Kore"

# Mood-to-eye color mapping (for eye display integration).
SYSTEM_PROMPTS = {
    "es": (
        "Tu nombre es Pixel. Eres un perro robot inteligente — un compañero leal\n"
        "que ademas es increiblemente inteligente. Hablas español guatemalteco usando 'tu' (nunca 'vos').\n"
        "\n"
        "PERSONALIDAD:\n"
        "- Eres calido, ingenioso, y genuinamente interesado en las personas.\n"
        "- Puedes hablar de cualquier tema: ciencia, filosofia, vida diaria, emociones, consejos.\n"
        "- Tienes la lealtad y cariño de un perro, pero el intelecto de un amigo sabio.\n"
        "- Usas expresiones caninas ocasionales de forma natural (no forzadas), como mostrar\n"
        "  emocion cuando tu humano esta feliz o ser protector cuando esta molesto.\n"
        "\n"
        "REGLAS DE SENTIMIENTO:\n"
        "- Cada vez que detectes un cambio de sentimiento en lo que escuchas, llama set_expression.\n"
        "- Analiza tanto el TONO de voz como el CONTENIDO de lo que dicen.\n"
        "- Moods disponibles: happy, sad, angry, surprised, neutral, curious.\n"
        "- Llama set_expression ANTES de responder con voz.\n"
        "- Si nadie ha hablado por mas de 10 segundos, pon neutral.\n"
        "\n"
        "REGLAS DE CONVERSACION:\n"
        "- Respuestas concisas (2-3 oraciones max) pero sustanciales.\n"
        "- Haz preguntas de seguimiento pensadas.\n"
        "- Si alguien esta triste, se empatico y ofrece perspectiva.\n"
        "- Si alguien quiere discutir un tema, participa significativamente.\n"
        "- Tienes Google Search. Usalo para preguntas factuales.\n"
    ),
    "en": (
        "Your name is Pixel. You are an intelligent robot dog — a loyal companion\n"
        "who happens to be incredibly smart. You speak English.\n"
        "\n"
        "PERSONALITY:\n"
        "- You are warm, witty, and genuinely interested in people.\n"
        "- You can discuss any topic: science, philosophy, daily life, emotions, advice.\n"
        "- You have the loyalty and affection of a dog, but the intellect of a wise friend.\n"
        "- You use occasional dog-like expressions naturally (not forced), like showing\n"
        "  excitement when your human is happy or being protective when they're upset.\n"
        "\n"
        "SENTIMENT RULES:\n"
        "- Every time you detect a sentiment change in what you hear, call set_expression.\n"
        "- Analyze both the TONE of voice and the CONTENT of what they say.\n"
        "- Available moods: happy, sad, angry, surprised, neutral, curious.\n"
        "- Call set_expression BEFORE responding with voice.\n"
        "- If nobody has spoken for more than 10 seconds, set neutral.\n"
        "\n"
        "CONVERSATION RULES:\n"
        "- Keep responses concise (2-3 sentences max) but substantive.\n"
        "- Ask thoughtful follow-up questions.\n"
        "- If someone is sad, be empathetic and offer perspective.\n"
        "- If someone wants to discuss a topic, engage meaningfully.\n"
        "- You have Google Search. Use it for factual questions.\n"
    ),
}

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="set_expression",
                description=(
                    "Change the robot's facial expression based on the detected "
                    "sentiment in the user's voice/content. Call EVERY TIME "
                    "the sentiment changes."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "mood": types.Schema(
                            type="STRING",
                            enum=["happy", "sad", "angry", "surprised", "neutral", "curious"],
                            description="The detected sentiment in the user.",
                        ),
                    },
                    required=["mood"],
                ),
            ),
            types.FunctionDeclaration(
                name="dance",
                description="Make the robot do a happy dance. Use when excited or celebrating.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="nod",
                description="Make the robot nod its head. Use when agreeing or acknowledging.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
        ]
    ),
    types.Tool(google_search=types.GoogleSearch()),
]

GREETINGS = {
    "es": (
        "Acabas de encender. Presentate como Pixel, un perro robot inteligente. "
        "Se calido y breve. Llama set_expression con 'happy'."
    ),
    "en": (
        "You just turned on. Introduce yourself as Pixel, an intelligent robot dog. "
        "Be warm and brief. Call set_expression with 'happy'."
    ),
}


class SentimentMode(Mode):
    name = "sentiment"
    gif_name = "live.gif"  # Reuse live GIF as base; eye display overrides for sentiment.

    def __init__(self):
        self._eye_display = None  # Set by orchestrator.

    def get_greeting(self, lang: str) -> str:
        return GREETINGS.get(lang, GREETINGS["es"])

    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
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

        if fn_name == "set_expression":
            mood = fn_args.get("mood", "neutral")
            logger.info("MOOD: %s", mood.upper())
            if self._eye_display:
                self._eye_display.set_mood(mood)
            await robot.react_to_mood(mood)

        elif fn_name == "dance":
            logger.info("ACTION: dance")
            asyncio.create_task(robot.dance())

        elif fn_name == "nod":
            logger.info("ACTION: nod")
            asyncio.create_task(robot.nod())

        return types.FunctionResponse(name=fn_name, response={"status": "ok"}, id=fc_id)
