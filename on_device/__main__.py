"""Entry point: on-device pupper-talk (runs on Pi or mock on laptop)."""

import argparse
import asyncio
import logging
import os
import sys
import threading

from dotenv import load_dotenv
from google import genai
from google.genai import types

from core.audio import AudioManager
from core.modes import create_mode, register_modes
from core.modes.base import inject_switch_tool
from core.stream import handle_responses, stream_microphone
from on_device.gif_display import GifDisplay
from on_device.robot_motion import RobotMotion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

LIVE_MODEL = "gemini-3.1-flash-live-preview"
VOICE_NAME = "Kore"

MODE_LABELS = {
    "live": "Conversacion", "rocky": "Rocky", "bumblebee": "Bumblebee",
    "vision": "Vision", "quiz": "Quiz", "code": "Codigo", "sentiment": "Pixel",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pupper-talk on-device")
    parser.add_argument("--mode", choices=["live", "rocky", "bumblebee", "vision", "quiz", "code", "sentiment"],
                        default="live", help="Demo mode (default: live)")
    parser.add_argument("--lang", choices=["es", "en"], default="es",
                        help="Language (default: es)")
    parser.add_argument("--mock", action="store_true",
                        help="Pygame window, no LCD/servos")
    parser.add_argument("--no-motion", action="store_true",
                        help="Disable body movements")
    return parser.parse_args()


async def _speak_ready(api_key: str, lang: str, audio: AudioManager) -> None:
    """Speak a short 'ready' announcement via a short-lived TTS session."""
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
    """Main orchestrator: manages mode lifecycle, hotwords, and streaming."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        sys.exit(1)

    register_modes()

    audio = AudioManager(mock=args.mock)
    robot = RobotMotion(mock=True) if args.no_motion else RobotMotion(mock=args.mock)
    client = genai.Client(api_key=api_key)

    # Hotword support — only when Vosk is fully functional.
    command_queue: asyncio.Queue[str] = asyncio.Queue()
    hotword_detector = None
    audio_router = None
    try:
        from core.hotword import VoskHotwordDetector
        from core.audio_router import AudioRouter
        hwd = VoskHotwordDetector(command_queue, asyncio.get_event_loop())
        if hwd.available:
            hotword_detector = hwd
            audio_router = AudioRouter(audio, hotword_detector)
            logger.info("Hotword detection enabled (Vosk)")
        else:
            logger.info("Vosk not functional — using Gemini fallback")
    except ImportError:
        logger.info("Vosk not installed — using Gemini fallback")
    except Exception as exc:
        logger.warning("Hotword init failed: %s", exc)

    use_gemini_switch = audio_router is None

    current_mode = create_mode(args.mode)
    await current_mode.on_enter(audio=audio, lang=args.lang)

    display = getattr(_thread_local, "display", None)
    if display:
        if current_mode.name in ("bumblebee", "sentiment"):
            display.switch_to_eyes("sentiment" if current_mode.name == "sentiment" else "bumblebee")
            current_mode._eye_display = display
        else:
            display.switch_gif(current_mode.gif_path)

    await _speak_ready(api_key, args.lang, audio)

    live_config = current_mode.get_live_config(args.lang)
    if use_gemini_switch:
        inject_switch_tool(live_config, current_mode.name)

    async with client.aio.live.connect(model=LIVE_MODEL, config=live_config) as session:
        # Send greeting to kick off the mode (Rocky introduces himself, Quiz starts, etc.)
        greeting = current_mode.get_greeting(args.lang)
        if greeting:
            await session.send_realtime_input(text=greeting)

        if audio_router:
            audio_router.set_session(session)

        camera = None
        if args.mode == "vision":
            try:
                from core.camera import CameraManager
                camera = CameraManager(mock=args.mock)
            except ImportError:
                pass

        mic_coro = audio_router.run() if audio_router else stream_microphone(session, audio)
        handler_coro = handle_responses(
            session, audio, current_mode, client, robot,
            command_queue=command_queue if use_gemini_switch else None,
        )

        extra_tasks = await current_mode.extra_tasks(
            session=session, audio=audio, camera=camera, robot=robot
        )

        all_coros = [mic_coro, handler_coro] + [t for t in extra_tasks]

        if not use_gemini_switch:
            # Vosk handles switching — just run everything.
            await asyncio.gather(*all_coros)
        else:
            # Gemini fallback — need to monitor command_queue for switch commands.
            mic_task = asyncio.create_task(mic_coro) if not extra_tasks else None
            handler_task = asyncio.create_task(handler_coro)
            extra_task_list = list(extra_tasks)

            # If mic_coro wasn't turned into a task yet, do it now.
            if mic_task is None:
                mic_task = asyncio.create_task(
                    audio_router.run() if audio_router else stream_microphone(session, audio)
                )

            current_mode_name = args.mode

            try:
                while True:
                    cmd_task = asyncio.create_task(command_queue.get())
                    done, _ = await asyncio.wait(
                        [cmd_task, handler_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if cmd_task in done:
                        cmd = cmd_task.result()
                        logger.info("SWITCH CMD: %s", cmd)

                        if not cmd.startswith("switch:"):
                            continue

                        new_name = cmd.split(":")[1]
                        if new_name == current_mode_name:
                            continue

                        # Teardown.
                        handler_task.cancel()
                        mic_task.cancel()
                        for t in extra_task_list:
                            t.cancel()
                        await current_mode.on_exit()
                        audio.flush_speaker()
                        break  # Exit while to reconnect below.
                    else:
                        cmd_task.cancel()
                        break  # handler died, exit.

            except asyncio.CancelledError:
                pass

    # If we broke out of the session for a mode switch, handle reconnection loop.
    if use_gemini_switch and cmd_task in done and cmd_task.result().startswith("switch:"):
        new_name = cmd_task.result().split(":")[1]
        await _run_mode_switch_loop(
            client, api_key, audio, robot, args, new_name, command_queue, display,
        )


async def _run_mode_switch_loop(
    client, api_key, audio, robot, args, initial_mode_name, command_queue, display,
) -> None:
    """Reconnection loop for Gemini-based mode switching."""
    current_mode_name = initial_mode_name

    while True:
        current_mode = create_mode(current_mode_name)
        await current_mode.on_enter(audio=audio, lang=args.lang)

        if display:
            if current_mode_name in ("bumblebee", "sentiment"):
                display.switch_to_eyes("sentiment" if current_mode_name == "sentiment" else "bumblebee")
                current_mode._eye_display = display
            else:
                display.switch_to_gif(current_mode.gif_path)

        live_config = current_mode.get_live_config(args.lang)
        inject_switch_tool(live_config, current_mode.name)

        camera = None
        if current_mode_name == "vision":
            try:
                from core.camera import CameraManager
                camera = CameraManager(mock=args.mock)
            except ImportError:
                pass

        async with client.aio.live.connect(model=LIVE_MODEL, config=live_config) as session:
            greeting = current_mode.get_greeting(args.lang)
            if greeting:
                await session.send_realtime_input(text=greeting)

            mic_task = asyncio.create_task(stream_microphone(session, audio))
            handler_task = asyncio.create_task(
                handle_responses(session, audio, current_mode, client, robot, command_queue=command_queue)
            )
            extra_tasks = await current_mode.extra_tasks(
                session=session, audio=audio, camera=camera, robot=robot,
            )

            switch_to = None
            try:
                while True:
                    cmd_task = asyncio.create_task(command_queue.get())
                    done, _ = await asyncio.wait(
                        [cmd_task, handler_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cmd_task in done:
                        cmd = cmd_task.result()
                        if cmd.startswith("switch:"):
                            switch_to = cmd.split(":")[1]
                            if switch_to == current_mode_name:
                                continue
                            handler_task.cancel()
                            mic_task.cancel()
                            for t in extra_tasks:
                                t.cancel()
                            await current_mode.on_exit()
                            audio.flush_speaker()
                            break
                    else:
                        cmd_task.cancel()
                        return  # handler died, stop.
            except asyncio.CancelledError:
                return

        if switch_to:
            current_mode_name = switch_to
        else:
            return


_thread_local = threading.local()


def main() -> None:
    args = parse_args()
    register_modes()

    if args.mock:
        logger.info("Running in MOCK mode")

    initial_mode = create_mode(args.mode)
    display = GifDisplay(initial_mode.gif_path, mock=args.mock)

    if args.mock:
        def _run_async():
            _thread_local.display = display
            asyncio.run(orchestrator(args))

        async_thread = threading.Thread(target=_run_async, daemon=True)
        async_thread.start()
        display.run_blocking()
        async_thread.join(timeout=3.0)
    else:
        display.start()
        _thread_local.display = display
        try:
            asyncio.run(orchestrator(args))
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            display.stop()


if __name__ == "__main__":
    main()
