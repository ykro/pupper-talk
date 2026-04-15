"""Entry point: pupper-talk via bridge (laptop controls Pi via HTTP)."""

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

from core.audio import AudioManager
from core.modes import create_mode, register_modes
from core.modes.base import inject_switch_tool
from core.stream import handle_responses, stream_microphone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

LIVE_MODEL = "gemini-3.1-flash-live-preview"
VOICE_NAME = "Kore"

MODE_LABELS = {
    "live": "Conversacion", "rocky": "Rocky", "bumblebee": "Bumblebee",
    "vision": "Vision", "quiz": "Quiz", "code": "Codigo",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pupper-talk via bridge")
    parser.add_argument("--mode", choices=["live", "rocky", "bumblebee", "vision", "quiz", "code", "sentiment"],
                        default="live", help="Demo mode (default: live)")
    parser.add_argument("--lang", choices=["es", "en"], default="es",
                        help="Language (default: es)")
    parser.add_argument("--bridge-url", type=str, default=None,
                        help="Override BRIDGE_URL env var")
    parser.add_argument("--no-bridge", action="store_true",
                        help="Skip bridge (audio + Gemini only)")
    return parser.parse_args()


async def _speak_ready(api_key: str, lang: str, audio: AudioManager) -> None:
    text = "Listo." if lang == "es" else "Ready."
    sys_text = "Say the word exactly as given. One word only. Confident tone."

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
            )
        ),
        system_instruction=types.Content(parts=[types.Part(text=sys_text)]),
    )
    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await session.send_realtime_input(text=text)
            async for response in session.receive():
                if response.data:
                    await audio.play_audio(response.data)
                sc = getattr(response, "server_content", None)
                if sc and getattr(sc, "turn_complete", False):
                    break
    except Exception as exc:
        logger.error("TTS ready failed: %s", exc)


async def orchestrator(args: argparse.Namespace) -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        sys.exit(1)

    register_modes()
    audio = AudioManager(mock=True)  # Always laptop mode.

    # Robot backend.
    if args.no_bridge:
        from on_device.robot_motion import RobotMotion
        robot = RobotMotion(mock=True)
        logger.info("Bridge disabled — mock robot")
    else:
        from using_bridge.bridge_client import BridgeClient
        robot = BridgeClient(base_url=args.bridge_url)
        await robot.initialize()

    client = genai.Client(api_key=api_key)

    # Hotword support.
    command_queue: asyncio.Queue[str] = asyncio.Queue()
    hotword_detector = None
    audio_router = None
    try:
        from core.hotword import VoskHotwordDetector
        from core.audio_router import AudioRouter
        hotword_detector = VoskHotwordDetector(command_queue, asyncio.get_event_loop())
        if hotword_detector.available:
            audio_router = AudioRouter(audio, hotword_detector)
            logger.info("Hotword detection enabled")
        else:
            hotword_detector = None
            logger.info("Vosk models not available — hotword detection disabled")
    except ImportError:
        logger.info("Vosk not available — hotword detection disabled")
    except Exception as exc:
        logger.warning("Hotword init failed: %s", exc)

    use_gemini_switch = hotword_detector is None
    if use_gemini_switch:
        logger.info("Using Gemini switch_mode fallback")

    current_mode = create_mode(args.mode)
    await current_mode.on_enter(audio=audio, lang=args.lang)

    await _speak_ready(api_key, args.lang, audio)

    live_config = current_mode.get_live_config(args.lang)
    if use_gemini_switch:
        inject_switch_tool(live_config, current_mode.name)

    session = await client.aio.live.connect(
        model=LIVE_MODEL, config=live_config
    ).__aenter__()

    greeting = current_mode.get_greeting(args.lang)
    if greeting:
        await session.send_realtime_input(text=greeting)

    if audio_router:
        audio_router.set_session(session)

    camera = None
    if args.mode == "vision":
        try:
            from core.camera import CameraManager
            camera = CameraManager(mock=True)
        except ImportError:
            pass

    tasks: list[asyncio.Task] = []
    if audio_router:
        tasks.append(asyncio.create_task(audio_router.run()))
    else:
        tasks.append(asyncio.create_task(stream_microphone(session, audio)))

    handler_task = asyncio.create_task(
        handle_responses(
            session, audio, current_mode, client, robot,
            command_queue=command_queue if use_gemini_switch else None,
        )
    )
    tasks.append(handler_task)

    extra_tasks = await current_mode.extra_tasks(
        session=session, audio=audio, camera=camera, robot=robot,
    )
    tasks.extend(extra_tasks)

    current_mode_name = args.mode

    try:
        while True:
            if not hotword_detector and not use_gemini_switch:
                await asyncio.gather(*tasks)
                break

            cmd_task = asyncio.create_task(command_queue.get())
            done, _ = await asyncio.wait(
                [cmd_task, handler_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cmd_task in done:
                cmd = cmd_task.result()
                logger.info("HOTWORD: %s", cmd)

                if cmd == "pause":
                    if audio_router:
                        audio_router.pause()
                    continue
                elif cmd == "resume":
                    if audio_router:
                        audio_router.resume()
                    continue
                elif cmd.startswith("switch:"):
                    new_name = cmd.split(":")[1]
                    if new_name == current_mode_name:
                        continue

                    handler_task.cancel()
                    for t in extra_tasks:
                        t.cancel()
                    await current_mode.on_exit()
                    try:
                        await session.__aexit__(None, None, None)
                    except Exception:
                        pass
                    audio.flush_speaker()

                    current_mode = create_mode(new_name)
                    current_mode_name = new_name
                    await current_mode.on_enter(audio=audio, lang=args.lang)

                    if new_name == "vision" and camera is None:
                        try:
                            from core.camera import CameraManager
                            camera = CameraManager(mock=True)
                        except ImportError:
                            pass

                    new_config = current_mode.get_live_config(args.lang)
                    if use_gemini_switch:
                        inject_switch_tool(new_config, current_mode.name)

                    session = await client.aio.live.connect(
                        model=LIVE_MODEL, config=new_config,
                    ).__aenter__()

                    greeting = current_mode.get_greeting(args.lang)
                    if greeting:
                        await session.send_realtime_input(text=greeting)

                    if audio_router:
                        audio_router.set_session(session)

                    handler_task = asyncio.create_task(
                        handle_responses(
                            session, audio, current_mode, client, robot,
                            command_queue=command_queue if use_gemini_switch else None,
                        )
                    )
                    extra_tasks = await current_mode.extra_tasks(
                        session=session, audio=audio, camera=camera, robot=robot,
                    )
            else:
                cmd_task.cancel()
                break

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        for t in tasks:
            t.cancel()
        audio.close()
        await robot.close()
        try:
            await session.__aexit__(None, None, None)
        except Exception:
            pass


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(orchestrator(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
