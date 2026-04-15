"""Mode ABC — interface that all 6 modes implement."""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from google.genai import types

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


class Mode(ABC):
    """Base class for pupper-talk demo modes."""

    name: str = ""
    gif_name: str = ""  # filename inside assets/
    suppress_voice: bool = False  # True = ignore Gemini audio output (Bumblebee)

    @property
    def gif_path(self) -> str:
        return str(ASSETS_DIR / self.gif_name)

    @abstractmethod
    def get_live_config(self, lang: str) -> types.LiveConnectConfig:
        """Return Gemini Live API config (prompt, voice, tools)."""

    @abstractmethod
    async def handle_tool_call(
        self, fc, client, audio, robot,
    ) -> types.FunctionResponse:
        """Handle a single function call. Return FunctionResponse."""

    def on_output_transcription(self, text: str) -> None:
        """Hook called with output transcription text.

        Rocky uses this for Eridian sound matching.
        """

    async def extra_tasks(self, **kwargs) -> list[asyncio.Task]:
        """Return additional async tasks to run alongside the response handler.

        Vision uses this for camera frame streaming.
        """
        return []

    def get_greeting(self, lang: str) -> str | None:
        """Return a text to send to Gemini when this mode starts.

        Kicks off modes that need Gemini to speak first (quiz, vision, rocky).
        Return None if the mode should just listen silently.
        """
        return None

    async def on_enter(self, **kwargs) -> None:
        """Called when this mode becomes active."""

    async def on_exit(self) -> None:
        """Called when this mode is being replaced."""


ALL_MODES = ("live", "rocky", "bumblebee", "vision", "quiz", "code", "sentiment")

SWITCH_PROMPT_SNIPPET = (
    "\n\nYou can switch demo modes. When the user says 'go rocky', 'switch to quiz', "
    "'cambia a bumblebee', or similar, call switch_mode immediately with the target mode name. "
    "Available modes: live, rocky, bumblebee, vision, quiz, code, sentiment."
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

    # Find a Tool with function_declarations to merge into, or create one.
    merged = False
    if config.tools:
        for tool in config.tools:
            if tool.function_declarations:
                tool.function_declarations.append(switch_decl)
                merged = True
                break
    if not merged:
        # Add as new Tool alongside existing ones (preserves GoogleSearch, etc.)
        switch_tool = types.Tool(function_declarations=[switch_decl])
        if config.tools:
            config.tools.append(switch_tool)
        else:
            config.tools = [switch_tool]

    # Append prompt snippet to system instruction.
    if config.system_instruction and config.system_instruction.parts:
        original_text = config.system_instruction.parts[0].text
        config.system_instruction = types.Content(
            parts=[types.Part(text=original_text + SWITCH_PROMPT_SNIPPET)]
        )

    return config
