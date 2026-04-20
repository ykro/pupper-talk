# pupper-talk -- CLAUDE.md

## What it does
Unified Mini Pupper 2 demo with 7 modes, voice hotword switching, and two robot control backends. Combines Live (conversation), Rocky (character), Bumblebee (song clips), Vision (I Spy), Quiz (trivia), Code (math solver), and Sentiment (emotional).

Public repo: github.com/ykro/pupper-talk

## How to run

### On-device (Pi direct)
```bash
uv run python -m on_device --mode live --lang es
uv run python -m on_device --mode rocky --lang en
```

### On-device mock (laptop) — default for testing
```bash
uv run python -m on_device --lang es --mock               # defaults to live
uv run python -m on_device --mode sentiment --lang es --mock
uv run python -m on_device --mode bumblebee --lang es --mock
```

### Via bridge (laptop + Pi HTTP)
```bash
uv run python -m using_bridge --mode bumblebee --lang es --bridge-url http://192.168.86.20:9090
```

## CLI Flags

### on_device
| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode` | live, rocky, bumblebee, vision, quiz, code, sentiment | live | Demo mode |
| `--lang` | es, en | es | Spoken language |
| `--mock` | flag | off | Pygame window, no LCD/servos |
| `--no-motion` | flag | off | Disable body movements |

### using_bridge
| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode` | live, rocky, bumblebee, vision, quiz, code, sentiment | live | Demo mode |
| `--lang` | es, en | es | Spoken language |
| `--bridge-url` | URL | BRIDGE_URL env or localhost:9090 | Bridge endpoint |

## 7 Modes

### live (default)
Free conversation. Kore voice. Tools: dance, nod, Google Search.

### rocky
Rocky from Project Hail Mary. Puck voice. Drops articles, triple repetitions, "pregunta"/"afirmacion" markers. Eridian musical sounds (WAV on asterisk text, routed through AudioManager). Tools: dance, nod, Google Search. Full prompt from pupper-characters with Fist Bump, Iconic Phrases.

### bumblebee
Communicates via song clips. 158 clips in catalog.yaml. Crossfade playback, radio tuning effect. Google Search. `suppress_voice=True` — Gemini audio ignored. Eye display: mechanical Autobot yellow. Full conversation prompt with multi-turn examples and ASK clips for back-and-forth. react_body supports nod/shake/shrug.

### vision
I Spy (Veo Veo) game. Camera frames sent to Live API every 5s (gated on `not audio.speaking` to prevent self-interruption). Kore voice. Tool: look_around. Mock shows OpenCV preview window.

### quiz
Trivia. Kore voice. Live API + function calls: generate_question (Gemini JSON schema), check_answer (with guard for missing question). Dances on correct answers.

### code
Math/logic solver. Kore voice. Live API + function calls: solve_with_code (generateContent with code_execution), nod when presenting solution.

### sentiment
Pixel — emotional robot dog. Detects voice sentiment (tone + content), calls set_expression to change eye COLOR in real time. 6 moods (happy=green, sad=ice, angry=red, surprised=teal, neutral=cyan, curious=amber). react_to_mood triggers pose + dance via RobotMotion MOOD_ACTIONS. Tools: set_expression, dance, nod, Google Search.

## Voice Hotwords

Works everywhere — Vosk on Pi (Linux), Gemini switch_mode tool on laptop (macOS, no Vosk wheels).

| Keyword | Action |
|---------|--------|
| "pausa" / "pause" | Stop sending audio (Vosk only) |
| "activo" / "active" | Resume sending audio (Vosk only) |
| "go live" / "go rocky" / "go bumblebee" / "go vision" / "go quiz" / "go code" / "go sentiment" / "go pixel" | Switch mode |

## Architecture

```
core/                    Shared between on_device and using_bridge
  audio.py               AudioManager (sounddevice, mic+speaker, nestable suppression, Pi output gain)
  stream.py              Generalized response handler with suppress_voice + tool mic suppression
  audio_router.py        Dual-stream mic to Vosk + Gemini, pause/resume
  hotword.py             VoskHotwordDetector (bilingual EN+ES, background)
  camera.py              CameraManager (OpenCV, webcam preview in mock)
  modes/
    base.py              Mode ABC + inject_switch_tool (preserves GoogleSearch)
    live.py              Free conversation + dance/nod + Google Search
    rocky.py             Rocky character + Eridian sounds (via AudioManager) + Google Search
    bumblebee.py         Song clips + catalog + crossfade + Google Search + suppress_voice
    vision.py            I Spy + camera frames gated on not speaking
    quiz.py              Trivia + structured JSON + guard against missing question
    code.py              Math solver + code_execution + nod
    sentiment.py         Pixel emotional + set_expression + react_to_mood + Google Search

on_device/               Pi direct (MangDang HardwareInterface)
  __main__.py            Entry point + orchestrator + mode switching loop
  gif_display.py         GIF renderer + Bumblebee/Sentiment eye renderers + ready text + switch_to_ready
  robot_motion.py        Servo control: 5 poses, 2 dances, mood reactions

using_bridge/            Laptop + HTTP bridge — laptop mirrors Pi display in Pygame window
  __main__.py            Entry point + _run_session (async with) + DualDisplay fan-out + heartbeat
  bridge_client.py       httpx POST to pupper-bridge :9090 (robot + display + heartbeat + disconnect)

songs/                   Bumblebee clips (gitignored, 6.4GB) + catalog.yaml (tracked)
assets/                  GIFs + Eridian WAVs + ready_{en,es}.wav (pre-rendered TTS for ready cue)
scripts/                 gen_ready_wavs.py — regenerate ready clips via Gemini Live (Kore)
```

## Key Technical Decisions

### All voice via Gemini Live API
Model: gemini-3.1-flash-live-preview. Text AI: gemini-3.1-flash-lite-preview (quiz JSON, code execution).

### Mode ABC with suppress_voice
All modes implement get_live_config(), handle_tool_call(), optional get_greeting(), on_output_transcription, extra_tasks, on_enter. Bumblebee sets `suppress_voice=True` to ignore Gemini audio.

### Unified response handler with tool mic suppression
core/stream.py handle_responses() suppresses mic during tool execution to prevent ambient noise from interrupting (fixes code/vision self-interrupt).

### Echo suppression (nestable counter)
1. `audio.suppressing` (clip-level): absolute silence during clip/sequence playback + cooldown. Uses `_suppress_depth` counter to handle nested calls from Bumblebee + stream handler.
2. `audio.speaking` (chunk-level): silence unless RMS > `INTERRUPT_RMS` (default 1500 — lets normal-volume user interrupts through, rejects most speaker echo).

### Gemini VAD sensitivity
All modes use `START_SENSITIVITY_LOW` + `END_SENSITIVITY_LOW` so Gemini needs a clearer signal before deciding "user started talking" — mitigates self-interrupts when laptop speaker echo leaks into the mic. Tune in each mode's `get_live_config`.

### Pi speaker gain
`AudioManager._output_gain = 4.0` on Pi (I2S speaker is quiet), `1.0` in mock. Applied in `_queue_samples` with int16 clipping.

### Ready cue is a pre-rendered WAV
`assets/ready_{en,es}.wav` generated once via `scripts/gen_ready_wavs.py` (Gemini Live, voice Kore). `_speak_ready` just `audio.play_clip()`s the file — zero TTS variance, zero network latency on startup.

### Threading model
Mock (macOS): Pygame main thread, asyncio background thread.
Pi: asyncio main thread, Pygame background thread (SDL_VIDEODRIVER=dummy).

### System prompts in English
--lang controls spoken language, not prompt language.

### Positive-only prompts
No "DO NOT", "Never", "Stay silent" in Gemini prompts.

## Stack
- Python 3.10 (Pi BSP requirement), uv
- Gemini Live API (gemini-3.1-flash-live-preview)
- Gemini API (gemini-3.1-flash-lite-preview) for quiz JSON + code execution
- sounddevice (PortAudio), OpenCV, Vosk (Linux), pydub, pyyaml, httpx, Pygame + Pillow

## Environment variables
- `GEMINI_API_KEY` -- required
- `BRIDGE_URL` -- pupper-bridge URL (default: http://localhost:9090)

## Using_bridge specifics
- `GifDisplay` runs on laptop main thread (Pygame window), shows same content as Pi LCD.
- `DualDisplay` wrapper fans `set_mood` / `set_speaking` (called by sentiment/bumblebee) to local display + bridge.
- `_heartbeat_loop` pings `/heartbeat` every 3s; on clean shutdown sends `/disconnect`. Pi reverts LCD to "bridge ready" text if no heartbeat for 8s.
- Session lifecycle: `_run_session` opens `async with client.aio.live.connect(...)` per mode; returns next mode name on `switch:X` command to reopen.

## Known Issues
- Thread leak on mic stream cancel (`queue.Queue.get()` without timeout)
- Hardcoded audio device index 1 on Pi (fragile if USB audio reorders)
- Race condition in RobotMotion.react_to_mood (no _busy guard before dance)
- Partial crossfade in bumblebee play_sequence (only first 2 clips)

## Pi Deployment
```bash
sudo apt install -y libportaudio2 python3.10-venv ffmpeg
uv venv --python 3.10 --system-site-packages
uv sync
cp .env.example .env  # add GEMINI_API_KEY
uv run python -m on_device --mode live --lang es
```

## Vosk Models (Pi only)
```bash
mkdir -p vosk-models && cd vosk-models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip '*.zip'
```
