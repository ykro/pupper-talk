"""Robot motion via MangDang HardwareInterface — direct servo control."""

import asyncio
import logging

import numpy as np

logger = logging.getLogger(__name__)

POSES = {
    "stand": np.array([
        [0.0, 0.0, 0.0, 0.0],
        [0.88, 0.88, 0.88, 0.88],
        [-0.70, -0.70, -0.70, -0.70],
    ]),
    "sit": np.array([
        [0.0, 0.0, 0.0, 0.0],
        [0.5, 0.5, 1.2, 1.2],
        [-0.3, -0.3, -1.4, -1.4],
    ]),
    "greet": np.array([
        [0.0, 0.0, 0.0, 0.0],
        [1.5, 0.88, 0.88, 0.88],
        [0.0, -0.70, -0.70, -0.70],
    ]),
    "excited": np.array([
        [0.15, -0.15, 0.15, -0.15],
        [1.0, 1.0, 1.0, 1.0],
        [-0.5, -0.5, -0.5, -0.5],
    ]),
    "sad": np.array([
        [0.0, 0.0, 0.0, 0.0],
        [0.4, 0.4, 0.4, 0.4],
        [-0.2, -0.2, -0.2, -0.2],
    ]),
}

DANCES = {
    "default": [("stand", 0.6), ("sit", 0.6), ("stand", 0.6), ("greet", 0.6), ("stand", 0.6)],
    "wiggle": [("stand", 0.4), ("excited", 0.4), ("stand", 0.4), ("excited", 0.4), ("stand", 0.4)],
}


class RobotMotion:
    """Control Mini Pupper 2 servos via MangDang HardwareInterface."""

    def __init__(self, mock: bool = False):
        self._mock = mock
        self._last_pose: str | None = None
        self._hw = None
        self._busy = False

        if not mock:
            self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            from MangDang.mini_pupper.HardwareInterface import HardwareInterface
            self._hw = HardwareInterface()
            self._hw.set_actuator_postions(POSES["stand"])
            logger.info("HardwareInterface initialized")
        except ImportError:
            logger.warning("MangDang HardwareInterface not available — motion disabled")
        except Exception as exc:
            logger.warning("HardwareInterface init failed: %s", exc)

    def _set_pose(self, pose_name: str) -> None:
        if self._hw is None:
            return
        pose = POSES.get(pose_name)
        if pose is not None:
            self._hw.set_actuator_postions(pose)

    async def _run_dance(self, style: str) -> None:
        sequence = DANCES.get(style)
        if not sequence:
            return
        self._busy = True
        try:
            for pose_name, duration in sequence:
                self._set_pose(pose_name)
                await asyncio.sleep(duration)
        finally:
            self._busy = False

    async def dance(self, style: str = "default") -> None:
        if self._busy:
            return
        if self._mock:
            logger.info("MOTION: dance=%s (mock)", style)
            return
        await self._run_dance(style)

    async def nod(self) -> None:
        if self._busy:
            return
        if self._mock:
            logger.info("MOTION: nod (mock)")
            return
        self._busy = True
        try:
            self._set_pose("greet")
            await asyncio.sleep(0.3)
            self._set_pose("stand")
            await asyncio.sleep(0.3)
            self._set_pose("greet")
            await asyncio.sleep(0.3)
            self._set_pose("stand")
        finally:
            self._busy = False

    async def shake_head(self) -> None:
        if self._mock:
            logger.info("MOTION: shake_head (mock)")
            return

    async def look_around(self) -> None:
        if self._busy:
            return
        if self._mock:
            logger.info("MOTION: look_around (mock)")
            return
        self._busy = True
        try:
            self._set_pose("greet")
            await asyncio.sleep(0.8)
            self._set_pose("stand")
        finally:
            self._busy = False

    async def react_to_mood(self, mood: str) -> None:
        """Trigger movement based on mood (for modes that use sentiment)."""
        if self._busy:
            return
        mood_actions = {
            "happy": ("excited", "wiggle"),
            "sad": ("sad", None),
            "angry": ("stand", None),
            "surprised": ("greet", "default"),
            "neutral": ("stand", None),
            "curious": ("greet", None),
        }
        pose, dance_style = mood_actions.get(mood, ("stand", None))
        if pose == self._last_pose and not dance_style:
            return
        self._last_pose = pose
        if self._mock:
            logger.info("MOTION: mood=%s pose=%s dance=%s (mock)", mood, pose, dance_style)
            return
        if dance_style:
            await self._run_dance(dance_style)
        else:
            self._set_pose(pose)

    async def close(self) -> None:
        if self._hw:
            self._set_pose("stand")
