# Gemini Tool-Based Mode Switching Fallback

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Vosk is unavailable (macOS/Windows), use a Gemini `switch_mode` tool call as fallback so users can switch modes by voice.

**Architecture:** Add a `switch_mode` FunctionDeclaration injected into any mode's LiveConnectConfig when Vosk is not available. `handle_responses` intercepts the tool call, posts `switch:<name>` to a command_queue, and returns an immediate response. Both orchestrators (`on_device`, `using_bridge`) gain mode-switching capability even without Vosk.

**Tech Stack:** google-genai (existing), Python asyncio

---

### Task 1: Add switch_mode tool injection helper

**Files:**
- Modify: `core/modes/base.py`

- [ ] **Step 1: Add the `inject_switch_tool` function to `base.py`**

Append after the `Mode` class definition:

```python
ALL_MODES = ("live", "rocky", "bumblebee", "vision", "quiz", "code")

SWITCH_PROMPT_SNIPPET = (
    "\n\nYou can switch demo modes. When the user says 'go rocky', 'switch to quiz', "
    "'cambia a bumblebee', or similar, call switch_mode immediately with the target mode name. "
    "Available modes: live, rocky, bumblebee, vision, quiz, code."
)


def inject_switch_tool(config: types.LiveConnectConfig, current_mode: str) -> types.LiveConnectConfig:
    """Add switch_mode tool + prompt snippet to a LiveConnectConfig.

    Called only when Vosk is unavailable (macOS/Windows fallback).
    """
    other_modes = [m for m in ALL_MODES if m != current_mode]

    switch_decl = types.FunctionDeclaration(
        name="switch_mode",
        description="Switch the robot to a different demo mode. Call immediately when the user asks to change mode.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "mode": types.Schema(
                    type="STRING",
                    enum=other_modes,
                    description="Target mode name",
                ),
            },
            required=["mode"],
        ),
    )

    # Append to existing tools (or create new list).
    existing_tools = list(config.tools) if config.tools else []
    existing_tools.append(types.Tool(function_declarations=[switch_decl]))
    config.tools = existing_tools

    # Append prompt snippet to system instruction.
    if config.system_instruction and config.system_instruction.parts:
        original_text = config.system_instruction.parts[0].text
        config.system_instruction = types.Content(
            parts=[types.Part(text=original_text + SWITCH_PROMPT_SNIPPET)]
        )

    return config
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from core.modes.base import inject_switch_tool; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/modes/base.py
git commit -m "feat: add inject_switch_tool helper for Gemini fallback mode switching"
```

---

### Task 2: Make `handle_responses` intercept `switch_mode` tool calls

**Files:**
- Modify: `core/stream.py`

- [ ] **Step 1: Add `command_queue` parameter to `handle_responses`**

Change the signature and add interception logic. The `command_queue` is `None` by default (no fallback needed when Vosk is active).

```python
async def handle_responses(
    session, audio: AudioManager, mode: Mode, client, robot,
    command_queue: asyncio.Queue | None = None,
) -> None:
    """Handle Gemini responses: audio + tool calls dispatched to Mode."""
    pending_tool_responses: list[types.FunctionResponse] = []
    try:
        while True:
            async for response in session.receive():
                has_tool = bool(getattr(response, "tool_call", None))
                server_content = getattr(response, "server_content", None)

                if not has_tool and pending_tool_responses:
                    try:
                        await session.send_tool_response(
                            function_responses=pending_tool_responses
                        )
                    except Exception as exc:
                        logger.error("Error sending tool response: %s", exc)
                    pending_tool_responses = []

                if server_content:
                    if getattr(server_content, "interrupted", False):
                        logger.info("Interrupted — flushing speaker")
                        audio.flush_speaker()

                    input_tx = getattr(server_content, "input_transcription", None)
                    output_tx = getattr(server_content, "output_transcription", None)
                    if input_tx and getattr(input_tx, "text", None):
                        logger.info("USER: %s", input_tx.text)
                    if output_tx and getattr(output_tx, "text", None):
                        logger.info("BOT: %s", output_tx.text)
                        mode.on_output_transcription(output_tx.text)

                if response.data:
                    await audio.play_audio(response.data)

                tool_call = getattr(response, "tool_call", None)
                if tool_call is not None:
                    for fc in getattr(tool_call, "function_calls", []):
                        # Intercept switch_mode — route to command_queue.
                        if fc.name == "switch_mode" and command_queue is not None:
                            target = fc.args.get("mode", "")
                            logger.info("GEMINI SWITCH: switch_mode(%s)", target)
                            command_queue.put_nowait(f"switch:{target}")
                            fc_id = getattr(fc, "id", None)
                            pending_tool_responses.append(
                                types.FunctionResponse(
                                    name="switch_mode",
                                    response={"status": "switching"},
                                    id=fc_id,
                                )
                            )
                            continue

                        fr = await mode.handle_tool_call(fc, client, audio, robot)
                        pending_tool_responses.append(fr)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Response handler error: %s", exc)
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from core.stream import handle_responses; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/stream.py
git commit -m "feat: intercept switch_mode tool calls in handle_responses"
```

---

### Task 3: Wire fallback into `on_device` orchestrator

**Files:**
- Modify: `on_device/__main__.py`

- [ ] **Step 1: Add import for `inject_switch_tool`**

At the top imports, add:

```python
from core.modes.base import inject_switch_tool
```

- [ ] **Step 2: Determine `use_gemini_switch` flag after Vosk init block**

After the existing Vosk try/except block (around line 108), add:

```python
    use_gemini_switch = hotword_detector is None or not hotword_detector.available
    if use_gemini_switch:
        logger.info("Vosk unavailable — using Gemini switch_mode fallback")
```

- [ ] **Step 3: Inject switch tool into initial session config**

Replace the session creation (around line 121):

```python
    live_config = current_mode.get_live_config(args.lang)
    if use_gemini_switch:
        inject_switch_tool(live_config, current_mode.name)

    session = await client.aio.live.connect(
        model=LIVE_MODEL, config=live_config
    ).__aenter__()
```

- [ ] **Step 4: Pass `command_queue` to `handle_responses` when using Gemini fallback**

Replace the handler_task creation (around line 145):

```python
    handler_task = asyncio.create_task(
        handle_responses(
            session, audio, current_mode, client, robot,
            command_queue=command_queue if use_gemini_switch else None,
        )
    )
```

- [ ] **Step 5: Replace the `if not hotword_detector` early-exit with unified loop**

The current while-loop exits immediately when `hotword_detector` is None. Change the condition so the loop runs whenever *either* Vosk or Gemini fallback can produce commands:

Replace:

```python
            if not hotword_detector:
                # No hotword — just wait for tasks.
                await asyncio.gather(*tasks)
                break
```

With:

```python
            if not hotword_detector and not use_gemini_switch:
                # No switching at all — just wait for tasks.
                await asyncio.gather(*tasks)
                break
```

- [ ] **Step 6: Inject switch tool on mode switch reconnect**

In the `switch:` handler block, after creating the new mode and before connecting the new session (around line 221), inject the tool:

Replace:

```python
                    session = await client.aio.live.connect(
                        model=LIVE_MODEL,
                        config=current_mode.get_live_config(args.lang),
                    ).__aenter__()
```

With:

```python
                    new_config = current_mode.get_live_config(args.lang)
                    if use_gemini_switch:
                        inject_switch_tool(new_config, current_mode.name)

                    session = await client.aio.live.connect(
                        model=LIVE_MODEL, config=new_config,
                    ).__aenter__()
```

- [ ] **Step 7: Pass `command_queue` to new handler_task on reconnect**

Replace the handler_task recreation (around line 229):

```python
                    handler_task = asyncio.create_task(
                        handle_responses(
                            session, audio, current_mode, client, robot,
                            command_queue=command_queue if use_gemini_switch else None,
                        )
                    )
```

- [ ] **Step 8: Verify syntax**

Run: `uv run python -c "from on_device.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add on_device/__main__.py
git commit -m "feat: wire Gemini switch_mode fallback into on_device orchestrator"
```

---

### Task 4: Wire fallback into `using_bridge` orchestrator

**Files:**
- Modify: `using_bridge/__main__.py`

Same changes as Task 3 but in the bridge orchestrator. The logic is identical.

- [ ] **Step 1: Add import for `inject_switch_tool`**

At the top imports, add:

```python
from core.modes.base import inject_switch_tool
```

- [ ] **Step 2: Add `use_gemini_switch` flag after Vosk init block**

After the existing Vosk try/except block (around line 112), add:

```python
    use_gemini_switch = hotword_detector is None or not hotword_detector.available
    if use_gemini_switch:
        logger.info("Vosk unavailable — using Gemini switch_mode fallback")
```

- [ ] **Step 3: Inject switch tool into initial session config**

Replace the session creation (around line 119):

```python
    live_config = current_mode.get_live_config(args.lang)
    if use_gemini_switch:
        inject_switch_tool(live_config, current_mode.name)

    session = await client.aio.live.connect(
        model=LIVE_MODEL, config=live_config
    ).__aenter__()
```

- [ ] **Step 4: Pass `command_queue` to `handle_responses`**

Replace handler_task creation (around line 140):

```python
    handler_task = asyncio.create_task(
        handle_responses(
            session, audio, current_mode, client, robot,
            command_queue=command_queue if use_gemini_switch else None,
        )
    )
```

- [ ] **Step 5: Replace early-exit condition**

Replace:

```python
            if not hotword_detector:
                await asyncio.gather(*tasks)
                break
```

With:

```python
            if not hotword_detector and not use_gemini_switch:
                await asyncio.gather(*tasks)
                break
```

- [ ] **Step 6: Inject switch tool on mode switch reconnect**

In the `switch:` handler, replace session creation (around line 203):

```python
                    new_config = current_mode.get_live_config(args.lang)
                    if use_gemini_switch:
                        inject_switch_tool(new_config, current_mode.name)

                    session = await client.aio.live.connect(
                        model=LIVE_MODEL, config=new_config,
                    ).__aenter__()
```

- [ ] **Step 7: Pass `command_queue` to new handler_task on reconnect**

Replace handler_task recreation (around line 209):

```python
                    handler_task = asyncio.create_task(
                        handle_responses(
                            session, audio, current_mode, client, robot,
                            command_queue=command_queue if use_gemini_switch else None,
                        )
                    )
```

- [ ] **Step 8: Verify syntax**

Run: `uv run python -c "from using_bridge.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add using_bridge/__main__.py
git commit -m "feat: wire Gemini switch_mode fallback into using_bridge orchestrator"
```

---

### Task 5: Smoke test on macOS mock

- [ ] **Step 1: Run on_device mock and test voice switching**

Run: `uv run python -m on_device --mode live --lang es --mock`

Expected log output: `Vosk unavailable — using Gemini switch_mode fallback`

Test: Say "cambia a rocky" or "go quiz". Verify:
1. Log shows `GEMINI SWITCH: switch_mode(rocky)`
2. Log shows `Listo. Modo: Rocky.` TTS
3. New session starts in Rocky mode

- [ ] **Step 2: Run using_bridge no-bridge and test voice switching**

Run: `uv run python -m using_bridge --mode live --lang es --no-bridge`

Same verification as Step 1.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: Gemini switch_mode fallback for mode switching without Vosk"
```
