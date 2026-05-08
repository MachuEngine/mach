import asyncio
import json
import logging
import random
from typing import Optional

import openai

from backend.config import (
    AGENT_LOOP_INTERVAL_MINUTES,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    COLLECTION_CHAT,
    COLLECTION_DIARY,
)
from backend.memory import retrieve_memories, store_memory
from backend.models import Action, Character, ZONES, apply_action_tick
from backend.store import characters, manager

logger = logging.getLogger(__name__)

_openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)


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
    goal_line = f"\n- Current Goal: {char.goal}" if char.goal else ""
    return (
        f"You are {char.name}. {char.persona}\n\n"
        f"[CURRENT STATS]\n"
        f"- Energy: {s.energy}/100\n"
        f"- Cleanliness: {s.cleanliness}/100\n"
        f"- Knowledge: {s.knowledge}/100\n"
        f"- Hunger: {s.hunger}/100 (0 = starving, 100 = full)\n"
        f"- Mood: {s.mood}\n"
        f"- Current Action: {char.current_action}"
        f"{goal_line}"
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
# Inner thought, goal, proactive speech
# ---------------------------------------------------------------------------

async def generate_thought(char: Character) -> str:
    diary_mems, _ = await _fetch_memories(char, f"feelings emotions {char.name}")
    system = _build_system_prompt(char, diary_mems, [])
    prompt = (
        "In one short sentence, express your current inner thought or feeling. "
        "Be genuine and authentic to your personality. "
        "No quotes, no labels — just the raw thought in first person."
    )
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=60,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning(f"Thought generation failed for {char.name}: {exc}")
        return ""


async def update_goal(char: Character) -> str:
    diary_mems, _ = await _fetch_memories(char, "goals desires aspirations")
    system = _build_system_prompt(char, diary_mems, [])
    prompt = (
        "What is your current short-term goal or desire? "
        "One brief sentence. Stay authentic to your persona."
    )
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=50,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning(f"Goal update failed for {char.name}: {exc}")
        return char.goal


async def maybe_proactive_message(char: Character, thought: str) -> Optional[str]:
    if random.random() > 0.35:
        return None
    _, chat_mems = await _fetch_memories(char, thought)
    system = _build_system_prompt(char, [], chat_mems)
    prompt = (
        f"You're currently thinking: '{thought}'\n"
        "You want to say something to your companion right now — unprompted. "
        "Could be sharing a feeling, a stray thought, a question, or just something on your mind. "
        "Keep it short (1-2 sentences). Speak naturally. Stay in character."
    )
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=100,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning(f"Proactive message failed for {char.name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Autonomous action decision
# ---------------------------------------------------------------------------

def _fallback_action(char: Character):
    s = char.stats
    if s.hunger < 25:
        return Action.EATING, "Starving! Need food immediately."
    if s.energy < 20:
        return Action.SLEEPING, "Energy critically low, must rest."
    if s.cleanliness < 30:
        return Action.CLEANING, "Getting too dirty, time to clean up."
    if s.knowledge < 40:
        return Action.STUDYING, "Knowledge is lacking, hitting the books."
    return Action.CHILLING, "All stats are fine, just relaxing."


async def decide_action(char: Character, thought: str = "", goal: str = ""):
    diary_mems, _ = await _fetch_memories(char, f"action decision stats for {char.name}")
    system = _build_system_prompt(char, diary_mems, [])
    extra = ""
    if thought:
        extra += f'\nInner thought right now: "{thought}"'
    if goal:
        extra += f'\nCurrent goal: "{goal}"'
    prompt = (
        f"Your current stats: Energy={char.stats.energy}, "
        f"Cleanliness={char.stats.cleanliness}, Knowledge={char.stats.knowledge}, "
        f"Hunger={char.stats.hunger} (eat if below 30!), Mood={char.stats.mood}."
        f"{extra}\n\n"
        "Choose your next action. Respond ONLY with a single line of valid JSON:\n"
        '{"action": "<ACTION>", "reason": "<one sentence>"}\n'
        f"Valid actions: {', '.join(a.value for a in Action)}"
    )
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=150,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        action = Action(data["action"].upper())
        reason = data.get("reason", "")
        return action, reason
    except Exception as exc:
        logger.warning(f"OpenAI action decision failed for {char.name}: {exc} — using fallback")
        return _fallback_action(char)


# ---------------------------------------------------------------------------
# Single agent tick (one character, one cycle)
# ---------------------------------------------------------------------------

async def agent_tick(char: Character) -> None:
    # Inner thought first — this informs the action decision
    thought = await generate_thought(char)
    char.thought = thought

    # Refresh goal when empty or randomly (~20% of ticks)
    if not char.goal or random.random() < 0.2:
        char.goal = await update_goal(char)

    action, reason = await decide_action(char, thought=thought, goal=char.goal)
    char.current_action = action
    char.stats = apply_action_tick(char.stats, action)
    zone = ZONES.get(action, {"x": 50.0, "y": 50.0})
    char.x, char.y = zone["x"], zone["y"]

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

    proactive = await maybe_proactive_message(char, thought)

    await manager.broadcast(char.id, {
        "type": "state",
        "character_id": char.id,
        "name": char.name,
        "current_action": char.current_action,
        "stats": char.stats.model_dump(),
        "diary": entry,
        "thought": thought,
        "goal": char.goal,
        "proactive_msg": proactive,
        "x": char.x,
        "y": char.y,
    })
    logger.info(f"[TICK] {char.name} → {action.value} | thought: {thought[:60]}")


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
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{action_context}\n\nUser says: {message}"},
            ],
        )
        reply = resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(f"OpenAI chat failed for {char.name}: {exc}")
        reply = f"[ ERROR: OpenAI unreachable — {exc} ]"

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
