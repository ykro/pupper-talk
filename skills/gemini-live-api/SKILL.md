---
name: gemini-live-api
description: Use when building real-time voice/vision apps with Gemini Live API — session setup, audio streaming, tool calling, activity detection, transcription, or multi-turn conversations
---

# Gemini Live API — Real-Time Voice & Vision Reference

## Overview

Gemini Live API provides bidirectional real-time voice and vision via WebSocket. Use `google-genai` Python SDK. Model: `gemini-3.1-flash-live-preview`. Audio in at 16kHz, audio out at 24kHz, video at max 1 FPS JPEG.

## Session Setup (Complete Pattern)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],  # MUST be AUDIO for voice (TEXT causes 1011 error)
    tools=TOOLS,
    system_instruction=types.Content(
        parts=[types.Part(text=SYSTEM_PROMPT)]
    ),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Kore",  # see voices table below
            )
        ),
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

async with client.aio.live.connect(
    model="gemini-3.1-flash-live-preview", config=config
) as session:
    # session is ready
```

## Multi-Turn Fix (CRITICAL)

`session.receive()` exits after each `turn_complete`. You MUST wrap in `while True`:

```python
while True:
    async for response in session.receive():
        # handle response
```

Without this, the session processes only one turn then stops receiving.

## Sending Input

```python
# Audio (16kHz, 16-bit PCM, mono, little-endian)
await session.send_realtime_input(
    audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
)

# Text (triggers voice response)
await session.send_realtime_input(text="Hello!")

# Video (JPEG, max 1 FPS)
await session.send_realtime_input(
    video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
)
```

## Receiving Responses

```python
async for response in session.receive():
    # Audio data
    if response.data:
        play_audio(response.data)  # 24kHz 16-bit PCM

    # Transcriptions
    content = response.server_content
    if content:
        if content.input_transcription and content.input_transcription.text:
            print(f"User: {content.input_transcription.text}")
        if content.output_transcription and content.output_transcription.text:
            print(f"Bot: {content.output_transcription.text}")
        if content.interrupted:
            flush_speaker_queue()  # user interrupted

    # Tool calls (see below)
    if response.tool_call:
        handle_tools(response.tool_call)
```

## Tool Calling (Function Declarations)

### Define Tools

```python
TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="set_expression",
                description="Change robot facial expression based on detected sentiment.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "mood": types.Schema(
                            type="STRING",
                            enum=["happy", "sad", "angry", "surprised", "neutral", "curious"],
                            description="The detected sentiment.",
                        ),
                    },
                    required=["mood"],
                ),
            ),
        ]
    )
]
```

### Handle Tool Calls (Accumulate + Flush Pattern)

```python
pending_tool_responses: list[types.FunctionResponse] = []

while True:
    async for response in session.receive():
        has_tool = bool(getattr(response, "tool_call", None))

        # Flush pending responses when non-tool response arrives
        if not has_tool and pending_tool_responses:
            await session.send_tool_response(function_responses=pending_tool_responses)
            pending_tool_responses = []

        # Accumulate tool calls
        if response.tool_call:
            for fc in response.tool_call.function_calls:
                result = execute_function(fc.name, dict(fc.args))
                pending_tool_responses.append(
                    types.FunctionResponse(
                        name=fc.name,
                        response={"status": "ok", **result},
                        id=fc.id,
                    )
                )
```

### Google Search Tool

```python
tools = [{"google_search": {}}]
# Can combine with function declarations
tools = [{"google_search": {}}, types.Tool(function_declarations=[...])]
```

## Echo Suppression Pattern

During speaker playback, send silence to Gemini unless user is loud enough to interrupt:

```python
INTERRUPT_RMS = 1500

async for chunk in audio.start_mic_stream():
    if audio.speaking:
        samples = np.frombuffer(chunk, dtype=np.int16)
        rms = int(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        data = chunk if rms > INTERRUPT_RMS else silence_chunk
    else:
        data = chunk
    await session.send_realtime_input(
        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
    )
```

## Activity Detection Config

| Parameter | Values | Description |
|-----------|--------|-------------|
| `start_of_speech_sensitivity` | `START_SENSITIVITY_HIGH`, `_LOW` | How easily speech is detected |
| `end_of_speech_sensitivity` | `END_SENSITIVITY_HIGH`, `_LOW` | How quickly silence ends a turn |
| `silence_duration_ms` | integer (e.g., 500) | Ms of silence before turn ends |
| `activity_handling` | `START_OF_ACTIVITY_INTERRUPTS` | User speech interrupts model |
| `turn_coverage` | `TURN_INCLUDES_ALL_INPUT` | All input included in turn context |

## Available Voices

Kore, Puck, Charon, Fenrir, Leda, Orus, Perseus, Zephyr, and others. Each has different tone/personality. Use `voice_name` in `PrebuiltVoiceConfig`.

## Supported Tools (3.1 Flash Live)

| Tool | Supported |
|------|-----------|
| Function Calling | Synchronous only |
| Google Search | Yes |
| Code Execution | No |
| Google Maps | No |
| URL Context | No |
| Async Function Calling | No (2.5 Flash only) |

## Key Specs

- Protocol: WSS (stateful WebSocket)
- Languages: 70+ supported
- Barge-in: native (user can interrupt model)
- Affective dialog: adapts to user emotion
- Input: 16kHz 16-bit PCM mono + JPEG frames + text
- Output: 24kHz 16-bit PCM mono + transcriptions + tool calls

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `response_modalities=["TEXT"]` | Use `["AUDIO"]` for voice apps (TEXT causes 1011 Internal Error) |
| Single `async for` without `while True` | `session.receive()` exits per turn, must loop |
| Not flushing tool responses | Accumulate, then flush when non-tool response arrives |
| Forgetting `fc.id` in FunctionResponse | Must include `id` to match request |
| Not handling `content.interrupted` | Flush speaker queue on interruption |
| Sending raw mic during speaker playback | Echo suppression: send silence unless RMS > threshold |
| System prompt in Spanish | Write prompts in English; use `--lang` / voice for output language |
