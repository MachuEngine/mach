import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.memory import init_collections
from backend.models import (
    Character,
    CharacterStats,
    ChatRequest,
    ChatResponse,
    CreateCharacterRequest,
)
from backend.store import characters, manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_collections()
    except Exception as exc:
        logger.warning(f"Qdrant unavailable at startup (will retry on first use): {exc}")
    yield


app = FastAPI(title="Mach AI Character Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "characters": len(characters)}


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

@app.post("/api/characters", response_model=Character, status_code=201)
async def create_character(req: CreateCharacterRequest):
    char = Character(
        name=req.name,
        persona=req.persona,
        stats=req.initial_stats or CharacterStats(),
    )
    characters[char.id] = char
    logger.info(f"Created character: {char.name} ({char.id})")
    return char


@app.get("/api/characters", response_model=list[Character])
async def list_characters():
    return list(characters.values())


@app.get("/api/characters/{character_id}", response_model=Character)
async def get_character(character_id: str):
    char = characters.get(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    return char


# ---------------------------------------------------------------------------
# Chat  (full Claude logic wired in Step 3)
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    char = characters.get(req.character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    # Placeholder replaced in Step 3 with Claude + RAG response
    return ChatResponse(
        character_id=char.id,
        response="[ SYSTEM: Claude integration coming in Step 3 ]",
        current_action=char.current_action,
        stats=char.stats,
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/character/{character_id}")
async def websocket_endpoint(websocket: WebSocket, character_id: str):
    if character_id not in characters:
        await websocket.close(code=4004)
        return

    await manager.connect(character_id, websocket)
    try:
        char = characters[character_id]
        # Send initial state on connect
        await websocket.send_json({
            "type": "state",
            "character_id": character_id,
            "name": char.name,
            "current_action": char.current_action,
            "stats": char.stats.model_dump(),
        })
        # Keep connection alive; agent loop pushes updates via manager.broadcast
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(character_id, websocket)
        logger.info(f"WebSocket disconnected: character={character_id}")


# ---------------------------------------------------------------------------
# Static frontend  (must be last — catches all unmatched routes)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
