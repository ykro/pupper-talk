"""Vision mode — I Spy (Veo Veo) game with camera frames sent to Live API."""

import asyncio
import logging

from google.genai import types

from core.modes.base import Mode

logger = logging.getLogger(__name__)

VOICE_NAME = "Kore"
FRAME_INTERVAL = 5  # seconds between camera frames

SYSTEM_PROMPTS = {
    "es": (
        "You are playing 'Veo Veo' (I Spy). You can see through a camera.\n"
        "Pick ONE object from what you see. Give a clue: its color and first letter.\n"
        "Format: 'Veo veo... algo de color [color] que empieza con la letra [letra]'.\n"
        "Wait for guesses. Give hints if wrong. Celebrate if correct. Then pick a new object.\n"
        "Speak Guatemalan Spanish using 'tu' (never 'vos'). Keep it fun and brief.\n"
        "Call look_around to scan the environment for more objects.\n"
    ),
    "en": (
        "You are playing 'I Spy'. You can see through a camera.\n"
        "Pick ONE object from what you see. Give a clue: its color and first letter.\n"
        "Format: 'I spy with my little eye... something [color] that starts with [letter]'.\n"
        "Wait for guesses. Give hints if wrong. Celebrate if correct. Then pick a new object.\n"
        "Speak English. Keep it fun and brief.\n"
        "Call look_around to scan the environment for more objects.\n"
    ),
}

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="look_around",
                description="Make the robot look around to scan the environment.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
        ]
    )
]


VISION_GREETINGS = {
    "es": "Mira a tu alrededor con la camara y empieza a jugar Veo Veo. Escoge un objeto que veas y da la primera pista.",
    "en": "Look around with the camera and start playing I Spy. Pick an object you can see and give the first clue.",
}


class VisionMode(Mode):
    name = "vision"
    gif_name = "vision.gif"

    def get_greeting(self, lang: str) -> str:
        return VISION_GREETINGS.get(lang, VISION_GREETINGS["es"])

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
        fc_id = getattr(fc, "id", None)

        if fn_name == "look_around":
            logger.info("ACTION: look_around")
            asyncio.create_task(robot.look_around())

        return types.FunctionResponse(name=fn_name, response={"status": "ok"}, id=fc_id)

    async def extra_tasks(self, **kwargs) -> list[asyncio.Task]:
        session = kwargs.get("session")
        camera = kwargs.get("camera")
        audio = kwargs.get("audio")
        if session and camera:
            return [asyncio.create_task(self._stream_camera(session, camera, audio))]
        return []

    async def _stream_camera(self, session, camera, audio=None) -> None:
        """Send camera frames to Gemini at regular intervals.

        Skips sending while Gemini is speaking to avoid mid-sentence
        re-evaluation of the scene.
        """
        try:
            while True:
                await asyncio.sleep(FRAME_INTERVAL)
                # Don't inject frames while Gemini is actively speaking.
                if audio and audio.speaking:
                    continue
                frame = camera.capture_frame()
                if frame:
                    await session.send_realtime_input(
                        video=types.Blob(data=frame, mime_type="image/jpeg")
                    )
                    logger.info("Camera frame sent (%d bytes)", len(frame))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Camera stream error: %s", exc)
