# Skill Creation Prompts

Prompts to replicate the creation of the Mini Pupper 2 and Gemini Live API skills.

---

## Prompt 1: Mini Pupper 2 Skill

```
Create a skill called mini-pupper-2 for the Mini Pupper 2 robot dog by MangDang.

This is a REFERENCE skill for writing Python code that controls the Mini Pupper 2. Research these sources:
- https://github.com/mangdangroboticsclub/mini_pupper (main repo + BSP)
- https://minipupperdocs.readthedocs.io/en/latest/index.html (official docs)
- Search the web for "MangDang Mini Pupper 2 Python API HardwareInterface"

The skill MUST cover:
1. Hardware specs table (servos 12 DOF, LCD ST7789 320x240, I2S audio 48kHz, camera, LiDAR, Python 3.10 only)
2. MangDang HardwareInterface API: `set_actuator_postions()` (note the typo in the API) with 3x4 numpy arrays (radians) for [abduction, hip, knee] x [FL, FR, BL, BR]
3. Pose definitions (stand, sit, greet, excited, sad) as numpy arrays and dance sequences as (pose, duration) tuples
4. LCD display approaches: sidikalamini/eyes-animation, custom Pygame renderer, MangDang Display API
5. Audio resampling: Pi I2S runs at 48kHz, must resample to 16kHz (mic input) and from 24kHz (speaker output) for Gemini Live API
6. Threading model: macOS mock = Pygame main thread + asyncio background; Pi = asyncio main + Pygame background with SDL_VIDEODRIVER=dummy
7. Pi deployment: SSH to Pi, uv venv with --system-site-packages, Python 3.10
8. Mock mode pattern: --mock flag, no hardware needed, Pygame window, direct audio rates
9. Control approach comparison: HardwareInterface (direct, <1ms, recommended) vs HTTP Bridge (FastAPI on Pi :9090, 50-100ms latency, deprecated) vs ROS2 Humble (SLAM/nav/LiDAR, heavy setup, conflicts with HardwareInterface on servo bus). Include decision rule: SLAM? -> ROS2. App on laptop? -> Bridge. Everything else? -> HardwareInterface.
10. ROS2 commands: bringup, teleop, SLAM, navigation, with ROS_DOMAIN_ID=42
11. Common mistakes table (bridge vs direct control, Python version, system-site-packages, SDL threading, audio resampling, API typo)

Key constraint: prefer HardwareInterface for robot control. Use Bridge only when app cannot run on Pi. Use ROS2 only for SLAM/navigation.
Keep it concise. Use tables and code blocks for scannability.
```

---

## Prompt 2: Gemini Live API Skill

```
Create a skill called gemini-live-api for the Gemini 3.1 Live API (real-time voice and vision).

This is a REFERENCE skill for building real-time voice/vision apps with Google's Gemini Live API using the google-genai Python SDK. Research these sources:
- https://ai.google.dev/gemini-api/docs/live-api (official docs)
- https://ai.google.dev/gemini-api/docs/live-api/get-started-sdk (Python tutorial)
- https://ai.google.dev/gemini-api/docs/live-api/tools (tool calling in Live API)
- Search the web for "Gemini 3.1 Flash Live API Python tool calling"

The skill MUST cover:
1. Complete session setup with LiveConnectConfig: response_modalities=["AUDIO"], tools, system_instruction, speech_config (voice selection), input/output audio transcription, realtime_input_config with activity detection
2. The CRITICAL multi-turn fix: session.receive() exits after turn_complete, MUST wrap in `while True`
3. Sending input: audio (16kHz 16-bit PCM via types.Blob), text, video (JPEG max 1 FPS)
4. Receiving responses: audio data (24kHz), transcriptions (input + output), interruption handling
5. Tool calling: FunctionDeclaration with types.Schema, the accumulate-and-flush pattern (collect FunctionResponses, flush when non-tool response arrives), Google Search tool
6. Echo suppression pattern: send silence during speaker playback, but pass audio through if RMS > threshold (user wants to interrupt via barge-in)
7. Activity detection config table (start/end sensitivity, silence_duration_ms, activity_handling, turn_coverage)
8. Available voices list and supported tools matrix (3.1 Flash Live vs 2.5)
9. Common mistakes table (TEXT vs AUDIO modality, missing while True, tool response flushing, fc.id, interrupted handling, echo suppression, prompt language)

Model: gemini-3.1-flash-live-preview
Protocol: WSS (stateful WebSocket), supports 70+ languages, barge-in, affective dialog.
Keep it concise. Use tables and code blocks for scannability.
```
