# pupper-talk

[Español](README.md) · **English**

Unified Mini Pupper 2 demo with 7 voice-driven interaction modes, hotword-based mode switching, and two control backends (direct on the Pi or over an HTTP bridge).

> **Note:** This is a translation. The [Spanish README](README.md) is canonical — if something drifts, the Spanish version is the source of truth.

**Talk slides:** [GDE Summit 2026 — pupper-talk](https://docs.google.com/presentation/d/1scd2uwQbCOYL3UUnDrJSRUVo4u01OACLcjSv0aeEBcc/present) *(slides in Spanish)*

## Table of contents

- [Modes](#modes)
  - [live (default)](#live-default)
  - [rocky](#rocky)
  - [bumblebee](#bumblebee)
  - [vision](#vision)
  - [quiz](#quiz)
  - [code](#code)
  - [sentiment](#sentiment)
- [Setup](#setup)
- [Usage](#usage)
- [Voice mode switching](#voice-mode-switching)
- [Architecture](#architecture)
  - [Module diagram](#module-diagram)
  - [Mode ABC pattern](#mode-abc-pattern)
  - [Streaming loop (`core/stream.py`)](#streaming-loop-corestreampy)
  - [Audio suppression layers](#audio-suppression-layers)
  - [Threading model](#threading-model)
  - [Audio resampling (Pi)](#audio-resampling-pi)
  - [Motion per mode](#motion-per-mode)
  - [Display per mode](#display-per-mode)
  - [on_device vs using_bridge](#on_device-vs-using_bridge)
  - [Tech stack](#tech-stack)
- [Skills](#skills)
- [Skill creation](#skill-creation)
- [Known issues](#known-issues)

## Modes

### live (default)
Free-form conversation. Talk about anything — science, philosophy, the weather, advice. Has Google Search for factual questions. Dances when excited, nods when it agrees.

**Examples:**
- "What's the weather like in Guatemala?"
- "Explain the theory of relativity"
- "What do you think about artificial intelligence?"

### rocky
Rocky, the Eridian alien from Project Hail Mary. Speaks without articles, repeats words three times ("Amaze amaze amaze!"), ends with "question"/"statement" markers. Produces Eridian musical sounds when emotional. Has Google Search ("I use human device, statement!").

**Examples:**
- "Rocky, where do you come from?"
- "What is Astrophage?"
- "What's the population of Guatemala?" (uses Google Search)
- Listen for the sounds when he says things like *happy chord*

### bumblebee
Bumblebee cannot speak — he communicates ONLY through song fragments. The lyrics are his words. Maintains back-and-forth conversation: answers, asks, opines, jokes. 158 clips in EN and ES. Mechanical Autobot face with golden eyes and animated mouth. Google Search for factual questions (searches and answers with clips).

**Examples:**
- "Hi, how are you?" → responds with greeting clips + state
- "I'm sad" → asks what happened (ASK clip), then consoles
- "Tell me a joke" → combines absurd clips
- "What do you think about reggaeton?" → opines with clips

### vision
"I Spy" game (Veo Veo). Uses the camera to see its surroundings, picks an object, and gives color and first-letter hints. Guess — if you miss it gives more hints, if you get it it celebrates and picks another. In mock it shows a webcam preview.

**Examples:**
- Starts automatically when entering the mode
- "Is it a cup?" → "No, but it's something you use in the kitchen..."
- "Give me another hint" → adds a hint
- "I don't know, tell me" → reveals and picks a new object

### quiz
Trivia. Generates questions with 4 options (a,b,c,d) using Gemini with structured JSON. Tracks score. Dances when you get one right. Shares a fun fact after each answer.

**Examples:**
- Starts automatically when entering the mode
- "b" → verifies, says whether it's correct, shares fun fact
- "Another question" → generates a new one on a different topic
- Topics: science, geography, history, pop culture, Guatemala, technology

### code
Solves math and logic problems by running Python in Gemini's sandbox. Speaks the result in 1-2 sentences.

**Examples:**
- "What's 347 times 892?"
- "What's the square root of 1764?"
- "If I have 5 apples and give 2 to each of 3 friends, how many do I have left?"
- "How many primes are there between 1 and 1000?"

### sentiment
Pixel — emotional robot dog. Detects the sentiment in your voice (tone + content) and changes its facial expression in real time. Animated eyes change COLOR based on mood: green (happy), ice blue (sad), red (angry), teal (surprised), cyan (neutral), amber (curious). Also moves its body (poses and dances per mood). Google Search for factual questions.

**Examples:**
- "I'm so happy today!" → green eyes, excited pose, wiggle dance
- "I feel bad..." → ice-blue eyes, sad pose
- "That makes me so angry" → red eyes, firm pose
- "What?! Really?!" → big teal eyes, greet pose + dance
- "How much is a flight to Madrid?" → uses Google Search

## Setup

### Dependencies

```bash
# Laptop (macOS)
brew install portaudio ffmpeg
uv sync

# Pi (Ubuntu 22.04)
sudo apt install -y libportaudio2 python3.10-venv ffmpeg
uv venv --python 3.10 --system-site-packages
uv sync
```

### Environment variables

```bash
cp .env.example .env
# Add:
# GEMINI_API_KEY — required
# BRIDGE_URL     — optional, pupper-bridge URL (default: http://localhost:9090)
```

### Vosk models (optional, only for hotwords on Pi)

```bash
mkdir -p vosk-models && cd vosk-models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip '*.zip'
```

## Usage

Without `--mode`, starts in **live** (free conversation).

```bash
# Laptop (mock) — simulates display + robot in a Pygame window
uv run python -m on_device --lang en --mock
uv run python -m on_device --mode sentiment --lang en --mock
uv run python -m on_device --mode bumblebee --lang en --mock

# Pi (direct) — real LCD + servos
uv run python -m on_device --mode rocky --lang en
uv run python -m on_device --mode vision --lang en

# Laptop + HTTP bridge — voice on laptop, motion on Pi
uv run python -m using_bridge --mode quiz --lang en --bridge-url http://192.168.86.20:9090
```

To test without hardware, use `on_device --mock`.

## Voice mode switching

Say **"go {mode}"** to switch. Works everywhere:

- **On Pi (with Vosk):** Vosk detects the hotword locally, without going through Gemini
- **On laptop / without Vosk:** Gemini hears "go rocky" and calls `switch_mode` as a tool call

| Command | Action |
|---------|--------|
| "go live" | Free conversation |
| "go rocky" | Rocky (Project Hail Mary) |
| "go bumblebee" | Bumblebee (song clips) |
| "go vision" | I Spy (Veo Veo) |
| "go quiz" | Trivia |
| "go code" | Math solver |
| "go sentiment" / "go pixel" | Pixel (emotional) |
| "pausa" / "pause" | Mute mic (Vosk only) |
| "activo" / "active" | Resume mic (Vosk only) |

## Architecture

### Module diagram

```
                 +-----------------+
                 |  Gemini Live API |
                 | (gemini-3.1-flash|
                 |  -live-preview)  |
                 +--------+--------+
                          |
               WebSocket (audio + tools)
                          |
          +---------------+----------------+
          |                                |
   +------+------+                  +------+------+
   | on_device/  |                  | using_bridge|
   | __main__.py |                  | __main__.py |
   +------+------+                  +------+------+
          |                                |
   +------+------+                  +------+------+
   | GifDisplay  |                  | BridgeClient|
   | + EyeRender |                  | (HTTP POST) |
   +------+------+                  +------+------+
          |                                |
   +------+------+                  +------+------+
   | RobotMotion |                  | pupper-bridge|
   | (servos)    |                  | (FastAPI Pi) |
   +-------------+                  +--------------+

core/                    Shared between on_device and using_bridge
  audio.py               AudioManager (sounddevice, mic+speaker, echo suppression)
  stream.py              Bidirectional Gemini streaming (mic -> API -> audio/tools)
  audio_router.py        Dual-stream to Vosk + Gemini, pause/resume
  hotword.py             VoskHotwordDetector (bilingual EN+ES, background)
  camera.py              CameraManager (OpenCV, preview in mock)
  modes/
    base.py              Mode ABC + inject_switch_tool
    live.py              Free conversation + dance/nod + Google Search
    rocky.py             Rocky character + Eridian sounds + Google Search
    bumblebee.py         Song clips + catalog + crossfade + Google Search
    vision.py            I Spy + camera frames every 5s
    quiz.py              Trivia + JSON schema + generateContent
    code.py              Math solver + code_execution sandbox
    sentiment.py         Pixel emotional + set_expression + Google Search

on_device/               Pi direct (MangDang HardwareInterface)
  __main__.py            Entry point + orchestrator + mode switching
  gif_display.py         GIF renderer + eye renderer (Bumblebee yellow / Sentiment colors)
  robot_motion.py        Servo control: 5 poses, 2 dances, mood reactions

using_bridge/            Laptop + HTTP bridge
  __main__.py            Entry point + orchestrator
  bridge_client.py       httpx POST to pupper-bridge :9090
```

### Mode ABC pattern

All modes inherit from `Mode` (`core/modes/base.py`) and implement:

| Method / Attribute | Purpose |
|--------------------|---------|
| `get_live_config(lang)` | Returns `LiveConnectConfig` (prompt, voice, tools, activity detection) |
| `handle_tool_call(fc, client, audio, robot)` | Executes function calls (dance, search, set_expression, etc.) |
| `get_greeting(lang)` (optional) | Initial text Gemini speaks when entering the mode |
| `on_enter(audio, robot, display)` (optional) | Side effects on entry (e.g. radio-tuning sound in Bumblebee) |
| `on_output_transcription(text)` (optional) | Intercepts transcriptions for effect triggers (Rocky `*happy*` -> WAV) |
| `extra_tasks(session, audio, camera)` (optional) | Coroutines running alongside the main loop (Vision sends frames every 5s) |
| `suppress_voice` (optional) | If `True`, ignore Gemini audio (Bumblebee uses clips only) |

`inject_switch_tool()` adds the `switch_mode` tool while preserving existing tools (Google Search, function declarations). Important fix: it doesn't replace tools, it combines them.

### Streaming loop (`core/stream.py`)

A single unified handler manages all modes:

1. **Mic -> Gemini:** `send_audio()` sends PCM 16kHz with echo suppression (silence during playback, pass-through if RMS > threshold to allow barge-in)
2. **Gemini -> speaker:** `handle_responses()` plays audio (skipped if `suppress_voice=True`), handles transcriptions, executes tool calls
3. **Tool mic suppression:** during function-call execution, the mic is silenced (`audio.start_suppression()`) to prevent ambient noise from interrupting the bot mid-call
4. **Switch mode:** if `switch_mode` is called, the handler sets `switching=True` and drains pending responses without playing them (prevents overlapping voice)

### Audio suppression layers

Two independent mechanisms prevent echo and self-interrupts:

| Layer | Flag | Level | Use |
|-------|------|-------|-----|
| Clip-level | `audio.suppressing` | Absolute (full silence) | During WAV/clip playback, tool execution. Nestable via `_suppress_depth` counter |
| Chunk-level | `audio.speaking` | RMS gate | While Gemini speaks, silence mic unless RMS > 1500 (allows interruption) |

### Threading model

```
macOS (mock):  Pygame MAIN thread    |  asyncio BACKGROUND thread
Pi:            asyncio MAIN thread   |  Pygame BACKGROUND thread (SDL_VIDEODRIVER=dummy)
```

Mandatory: SDL requires the main thread on macOS; asyncio needs the main thread on Pi for signal handling.

### Audio resampling (Pi)

Pi I2S hardware runs at 48kHz. Gemini expects 16kHz in / 24kHz out. `AudioManager` does linear resampling in-line (simple interpolation, sufficient for voice).

### Motion per mode

| Mode | Actions | When |
|------|---------|------|
| **live** | dance, nod | Celebrate, agree |
| **rocky** | dance, nod | "Amaze!" = dance, "Is good" = nod |
| **bumblebee** | dance, nod, shake | Depending on the clip it plays |
| **vision** | look_around | When searching for new objects |
| **quiz** | dance | When you get a question right |
| **code** | nod | When presenting the solution |
| **sentiment** | react_to_mood (5 poses + 2 dances) | On every sentiment change |

### Display per mode

| Mode | Display |
|------|---------|
| **live** | Animated GIF |
| **rocky** | Animated GIF |
| **bumblebee** | Autobot mechanical eyes (fixed yellow, shape changes by mood, animated mouth) |
| **vision** | Animated GIF + camera preview (mock) |
| **quiz** | Animated GIF |
| **code** | Animated GIF |
| **sentiment** | Animated eyes (COLOR changes by mood: green/blue/red/teal/cyan/amber) |

### on_device vs using_bridge

| | on_device | using_bridge |
|---|-----------|-------------|
| **Where it runs** | On the Pi directly | Laptop (audio+Gemini) + Pi (servos via HTTP) |
| **Servos** | MangDang HardwareInterface directly | HTTP POST to pupper-bridge (FastAPI) |
| **LCD/Display** | ST7789 SPI (GIF or EyeRenderer) | No display (process runs on laptop, LCD is on the Pi) |
| **Audio** | Pi I2S (48kHz resample) | Native laptop audio (24kHz) |
| **Mock mode** | `--mock` simulates everything on laptop (Pygame + mock servos) | N/A (always runs on laptop) |
| **Mode switch** | Vosk hotwords (Pi) or Gemini fallback | Gemini fallback (say "go rocky") |
| **Camera (vision)** | Pi camera or USB | Laptop webcam |

**on_device limitations:** requires a Pi with Ubuntu 22.04 + ROS2 Humble + MangDang BSP, Python 3.10 (BSP), I2S audio at 48kHz needs resampling.

**using_bridge limitations:** no display (the LCD is on the Pi), requires `pupper-bridge` (FastAPI :9090) running on the Pi.

### Tech stack

- Python 3.10 (required by the MangDang BSP)
- `uv` as package manager
- Gemini Live API (`gemini-3.1-flash-live-preview`) for voice
- Gemini API (`gemini-3.1-flash-lite-preview`) for quiz JSON and code execution
- `sounddevice` (PortAudio), `opencv-python`, `vosk` (Linux only), `pydub`, `pyyaml`, `httpx`, `pygame` + `Pillow`

## Skills

This repo ships two reference skills under `skills/` that any agent (Claude Code, Cursor, etc.) can load as context when working on this kind of project:

| Skill | When to use it |
|-------|----------------|
| [`skills/mini-pupper-2/SKILL.md`](skills/mini-pupper-2/SKILL.md) | Code for Mini Pupper 2 — servos, LCD, I2S, MangDang HardwareInterface, Pi deployment, mock mode |
| [`skills/gemini-live-api/SKILL.md`](skills/gemini-live-api/SKILL.md) | Real-time voice/vision apps with Gemini Live API — session setup, streaming, tool calling, activity detection, transcription |

Each skill is a concise document with:
- Overview and key specs
- Canonical patterns (ready-to-copy code)
- Comparison and decision tables
- Common mistakes and their fixes

## Skill creation

The skills above were generated with structured prompts, documented in [`skill-creation-prompts.md`](skill-creation-prompts.md). Those prompts are used with agents (Claude Code, Cursor, ChatGPT) that have web search access to investigate official docs and public repos before consolidating the skill.

The idea: instead of copy-pasting documentation, the agent researches official sources (ai.google.dev, minipupperdocs, mangdangroboticsclub/mini_pupper) and produces a concise, practical skill. Each prompt defines:

- The sources it must consult (specific URLs + web search queries)
- The topics the skill MUST cover (numbered)
- Constraints and format (tables, code blocks, brevity)

To reproduce the skills:

```bash
# In Claude Code or Cursor with a web-search-enabled agent
# Copy the relevant prompt from skill-creation-prompts.md
# Paste and run — the agent researches and generates skills/<name>/SKILL.md
```

## Known issues

| Issue | Severity | Description |
|-------|----------|-------------|
| Session leak (bridge) | Medium | `using_bridge` uses manual `__aenter__` instead of `async with`. Can leak WebSocket connections after many mode switches. Future refactor. |
| Thread leak (mic) | Low | `queue.Queue.get()` without timeout in the executor thread. After many switches it can exhaust the thread pool. Workaround: restart the app. |
| Audio device index (Pi) | Medium | Device index hardcoded to `1` for I2S. If the Pi enumerates devices differently after reboot, audio fails silently. Verify with `sd.query_devices()`. |
| Race condition (motion) | Low | `react_to_mood` doesn't set `_busy=True` before delegating to `_run_dance`. Two concurrent calls could fight over the servos. In practice tool calls are serialized. |
| Partial crossfade (bumblebee) | Low | `play_sequence` only crossfades the first 2 clips. From the 3rd onward it uses static+individual clip. |
