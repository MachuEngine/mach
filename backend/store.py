"""
Shared in-memory state: character store and WebSocket connection manager.
Kept in a separate module so both main.py and agent.py can import without
circular dependencies.
"""
import logging
from typing import Dict, List

from fastapi import WebSocket

from backend.models import Character

logger = logging.getLogger(__name__)

# character_id -> Character
characters: Dict[str, Character] = {}


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, character_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(character_id, []).append(ws)
        logger.info(f"WebSocket connected: character={character_id}")

    def disconnect(self, character_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(character_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, character_id: str, data: dict) -> None:
        dead: List[WebSocket] = []
        for ws in self._connections.get(character_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(character_id, ws)


manager = ConnectionManager()
