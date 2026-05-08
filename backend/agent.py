import asyncio
import json
import logging

import anthropic

from backend.config import (
    AGENT_LOOP_INTERVAL_MINUTES,
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    COLLECTION_CHAT,
    COLLECTION_DIARY,
)
from backend.memory import retrieve_memories, store_memory
from backend.models import Action, Character, apply_action_tick
from backend.store import characters, manager

logger = logging.getLogger(__name__)

_claude = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _build_system_prompt(char: Character, diary_mems: list, chat_mems: list) -> str:
    s = char.stats
    mem_block = ""
    if diary_mems:
        mem_block += "\n\n[PAST DIARY ENTRIES]\n" + "\n".join(f"- {m}" for m in diary_mems)
    if chat_mems:
        mem_block += "\n\n[PAST CONVERSATIONS]\n" + "\n".join(f"- {m}" for m in chat_mems)
    return (
        f"You are {char.name}. {char.persona}\n\n"
        f"[CURRENT STATS]\n"
        f"- Energy: {s.energy}/100\n"
        f"- Cleanliness: {s.cleanliness}/100\n"
        f"- Knowledge: {s.knowledge}/100\n"
        f"- Mood: {s.mood}\n"
        f"- Current Action: {char.current_action}"
        f"{mem_block}"
    )


async def _fetch_memories(char: Character, query: str):
    try:
        diary = await asyncio.to_thread(retrieve_memories, char.id, query, COLLECTION_DIARY)
        chat = await asyncio.to_thread(retrieve_memories, char.id, query, COLLECTION_CHAT)
        return diary, chat
    except Exception as exc:
        logger.warning(f"Memory retrieval failed for {char.name}: {exc}")
        return [], []


# ---------------------------------------------------------------------------
# Autonomous action decision
# ---------------------------------------------------------------------------

def _fallback_action(char: Character):
    s = char.stats
    if s.energy < 30:
        return Action.SLEEPING, "Energy critically low, must rest."
    if s.cleanliness < 30:
        return Action.CLEANING, "Getting too dirty, time to clean up."
    if s.knowledge < 40:
        return Action.STUDYING, "Knowledge is lacking, hitting the books."
    return Action.CHILLING, "All stats are fine, just relaxing."


async def decide_action(char: Character):
    diary_mems, _ = await _fetch_memories(char, f"action decision stats for {char.name}")
    system = _build_system_prompt(char, diary_mems, [])
    prompt = (
        f"Your current stats: Energy={char.stats.energy}, "
        f"Cleanliness={char.stats.cleanliness}, Knowledge={char.stats.knowledge}, "
        f"Mood={char.stats.mood}.\n\n"
        "Choose your next action. Respond ONLY with a single line of valid JSON:\n"
        '{"action": "<ACTION>", "reason": "<one sentence>"}\n'
        f"Valid actions: {', '.join(a.value for a in Action)}"
    )
    try:
        resp = await _claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown fences if Claude wrapped the JSON
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        action = Action(data["action"].upper())
        reason = data.get("reason", "")
        return action, reason
    except Exception as exc:
        logger.warning(f"Claude action decision failed for {char.name}: {exc} — using fallback")
        return _fallback_action(char)


# ---------------------------------------------------------------------------
# Single agent tick (one character, one cycle)
# ---------------------------------------------------------------------------

async def agent_tick(char: Character) -> None:
    action, reason = await decide_action(char)
    char.current_action = action
    char.stats = apply_action_tick(char.stats, action)

    entry = (
        f"{char.name} chose to {action.value.lower()}. "
        f"{reason} "
        f"[E:{char.stats.energy} C:{char.stats.cleanliness} "
        f"K:{char.stats.knowledge} M:{char.stats.mood}]"
    )
    try:
        await asyncio.to_thread(
            store_memory, char.id, entry, COLLECTION_DIARY, {"action": action.value}
        )
    except Exception as exc:
        logger.warning(f"Diary write failed for {char.name}: {exc}")

    await manager.broadcast(char.id, {
        "type": "state",
        "character_id": char.id,
        "name": char.name,
        "current_action": char.current_action,
        "stats": char.stats.model_dump(),
        "diary": entry,
    })
    logger.info(f"[TICK] {char.name} → {action.value} | {reason[:80]}")


# ---------------------------------------------------------------------------
# User chat  (RAG-grounded, stores exchange to Qdrant)
# ---------------------------------------------------------------------------

async def chat_with_character(char: Character, message: str) -> str:
    diary_mems, chat_mems = await _fetch_memories(char, message)
    system = _build_system_prompt(char, diary_mems, chat_mems)

    # Note current action so the character "acts in character"
    action_context = (
        f"You are currently {char.current_action.value.lower()}. "
        "The user has interrupted you. Respond accordingly — stay in character."
    )

    try:
        resp = await _claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=system,
            messages=[
                {"role": "user", "content": f"{action_context}\n\nUser says: {message}"},
            ],
        )
        reply = resp.content[0].text.strip()
    except Exception as exc:
        logger.error(f"Claude chat failed for {char.name}: {exc}")
        reply = f"[ ERROR: Claude unreachable — {exc} ]"

    try:
        log = f"User: {message}\n{char.name}: {reply}"
        await asyncio.to_thread(store_memory, char.id, log, COLLECTION_CHAT)
    except Exception as exc:
        logger.warning(f"Chat log write failed: {exc}")

    return reply


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def agent_loop() -> None:
    interval = AGENT_LOOP_INTERVAL_MINUTES * 60
    logger.info(f"Agent loop started — ticking every {interval}s ({AGENT_LOOP_INTERVAL_MINUTES} min)")
    while True:
        await asyncio.sleep(interval)
        for char in list(characters.values()):
            try:
                await agent_tick(char)
            except Exception as exc:
                logger.error(f"Agent tick error for {char.name}: {exc}", exc_info=True)
