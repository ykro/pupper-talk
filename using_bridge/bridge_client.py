"""HTTP client for pupper-bridge (FastAPI on Pi, port 9090).

Exposes the same interface as RobotMotion so modes can use either backend.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_URL = "http://localhost:9090"


class BridgeClient:
    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or os.getenv("BRIDGE_URL", DEFAULT_BRIDGE_URL)
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=5.0)
        await self._check_connection()

    async def _check_connection(self) -> bool:
        try:
            resp = await self._client.get("/status")
            resp.raise_for_status()
            self._connected = True
            logger.info("Bridge connected at %s", self._base_url)
            return True
        except Exception as exc:
            self._connected = False
            logger.warning("Bridge unreachable at %s: %s", self._base_url, exc)
            return False

    async def _post(self, endpoint: str, data: dict | None = None) -> None:
        if not self._connected or not self._client:
            return
        try:
            resp = await self._client.post(endpoint, json=data or {})
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Bridge %s error: %s", endpoint, exc)

    # -- Same interface as RobotMotion --------------------------------------

    async def dance(self, style: str = "default") -> None:
        logger.info("BRIDGE: dance style=%s", style)
        await self._post("/dance", {"style": style})

    async def nod(self) -> None:
        logger.info("BRIDGE: nod")
        await self._post("/react", {"mood": "curious"})

    async def shake_head(self) -> None:
        logger.info("BRIDGE: shake_head")
        await self._post("/react", {"mood": "angry"})

    async def look_around(self) -> None:
        logger.info("BRIDGE: look_around")
        await self._post("/pose", {"pose": "greet"})

    async def react_to_mood(self, mood: str) -> None:
        logger.info("BRIDGE: react mood=%s", mood)
        await self._post("/react", {"mood": mood})

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False
