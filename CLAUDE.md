# pupper-talk -- CLAUDE.md

## What it does
Unified Mini Pupper 2 demo with 6 modes, voice hotword switching, and two robot control backends. Combines Rocky (character), Bumblebee (song clips), Vision (I Spy), Quiz (trivia), Code (math solver), and Live (conversation).

## How to run

### On-device (Pi direct)
```bash
uv run python -m on_device --mode live --lang es
uv run python -m on_device --mode rocky --lang en
```

### On-device mock (laptop)
```bash
uv run python -m on_device --mode live --lang es --mock
uv run python -m on_device --mode quiz --lang en --mock
```

### Via bridge (laptop + Pi HTTP)
```bash
uv run python -m using_bridge --mode bumblebee --lang es --bridge-url http://192.168.86.20:9090
```

### Voice only (no robot)
```bash
uv run python -m using_bridge --mode code --lang es --no-bridge
```

## CLI Flags

### on_device
| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode` | live, rocky, bumblebee, vision, quiz, code | live | Demo mode |
| `--lang` | es, en | es | Spoken language |
| `--mock` | flag | off | Pygame window, no LCD/servos |
| `--no-motion` | flag | off | Disable body movements |

### using_bridge
| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode` | live, rocky, bumblebee, vision, quiz, code | live | Demo mode |
| `--lang` | es, en | es | Spoken language |
| `--bridge-url` | URL | BRIDGE_URL env or localhost:9090 | Bridge endpoint |
| `--no-bridge` | flag | off | Skip bridge, voice only |

## 6 Modes

### live (default)
Free conversation. Fenrir voice. Tools: dance, nod.

### rocky
Rocky from Project Hail Mary. Puck voice. Drops articles, triple repetitions, "question"/"statement" markers. Eridian musical sounds (WAV on asterisk text). Google Search.

### bumblebee
Communicates via song clips. Gemini selects clips from catalog.yaml (158 clips). Crossfade playback, radio tuning effect. Google Search. Gemini audio output is ignored.

### vision
I Spy (Veo Veo) game. Camera frames sent to Live API every 5s. Fenrir voice. Tool: look_around. Mock uses laptop webcam.

### quiz
Trivia. Fenrir voice. Live API + function calls: generate_question dispatches to generateContent with response_schema JSON, check_answer validates. Dances on correct answers.

### code
Math/logic solver. Fenrir voice. Live API + function call: solve_with_code dispatches to generateContent with code_execution.

## Voice Hotwords (Vosk)

Vosk runs in parallel, bilingual (EN + ES). Available on Pi (Linux). Not on macOS (no Vosk wheels).

| Keyword | Action |
|---------|--------|
| "pausa" / "pause" | Stop sending audio to Gemini |
| "activo" / "active" | Resume sending audio |
| "go rocky" | Switch to Rocky mode |
| "go bumblebee" | Switch to Bumblebee mode |
| "go vision" | Switch to Vision mode |
| "go quiz" | Switch to Quiz mode |
| "go code" | Switch to Code mode |
| "go live" | Switch to Live mode |

## Architecture

```
core/                    Shared between on_device and using_bridge
  audio.py               AudioManager (sounddevice, mic+speaker, echo suppression, clips)
  stream.py              Generalized response handler (works with any Mode)
  audio_router.py        Routes mic to Vosk + Gemini, pause/resume
  hotword.py             VoskHotwordDetector (bilingual, background)
  camera.py              CameraManager (OpenCV, webcam in mock)
  modes/
    base.py              Mode ABC
    live.py              Free conversation + dance/nod
    rocky.py             Rocky character + Eridian sounds
    bumblebee.py         Song clips + catalog + engine
    vision.py            I Spy + camera frames
    quiz.py              Trivia + structured JSON
    code.py              Math solver + code_execution

on_device/               Pi direct (MangDang HardwareInterface)
  __main__.py            Entry point + orchestrator
  gif_display.py         GIF renderer with hot-swap (ST7789 SPI)
  robot_motion.py        Servo control + poses + dances

using_bridge/            Laptop + HTTP bridge
  __main__.py            Entry point + orchestrator
  bridge_client.py       httpx POST to pupper-bridge :9090
```

## Key Technical Decisions

### All voice via Gemini Live API
Model: gemini-3.1-flash-live-preview. Text AI: gemini-3.1-flash-lite-preview.

### Mode ABC
All modes implement get_live_config(), handle_tool_call(), and optional hooks (on_output_transcription for Rocky sounds, extra_tasks for Vision camera).

### Unified response handler
core/stream.py handle_responses() works with any Mode. Eliminates duplicated response handling.

### Echo suppression (two-layer)
1. audio.suppressing (clip-level): absolute silence during clip/sequence playback + cooldown.
2. audio.speaking (chunk-level): silence unless RMS > threshold (allows interrupts).

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
- sounddevice (PortAudio) for audio
- OpenCV for camera
- Vosk for hotword detection (Linux only)
- pydub for clip loading (Bumblebee)
- pyyaml for catalog parsing
- httpx for bridge
- Pygame + Pillow for GIF display

## Environment variables
- `GEMINI_API_KEY` -- required
- `BRIDGE_URL` -- pupper-bridge URL (default: http://localhost:9090)

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
