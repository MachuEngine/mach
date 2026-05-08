import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Action(str, Enum):
    SLEEPING = "SLEEPING"
    STUDYING = "STUDYING"
    CLEANING = "CLEANING"
    CHILLING = "CHILLING"


class Mood(str, Enum):
    HAPPY = "HAPPY"
    TIRED = "TIRED"
    GRUMPY = "GRUMPY"
    FOCUSED = "FOCUSED"
    CHILL = "CHILL"
    ENERGETIC = "ENERGETIC"


class CharacterStats(BaseModel):
    energy: int = Field(default=70, ge=0, le=100)
    cleanliness: int = Field(default=70, ge=0, le=100)
    knowledge: int = Field(default=50, ge=0, le=100)
    mood: Mood = Mood.CHILL


class Character(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    persona: str
    stats: CharacterStats = Field(default_factory=CharacterStats)
    current_action: Action = Action.CHILLING
    created_at: float = Field(default_factory=time.time)


# --- Request / Response schemas ---

class CreateCharacterRequest(BaseModel):
    name: str
    persona: str
    initial_stats: Optional[CharacterStats] = None


class ChatRequest(BaseModel):
    character_id: str
    message: str


class ChatResponse(BaseModel):
    character_id: str
    response: str
    current_action: Action
    stats: CharacterStats


# --- Stat delta rules applied each agent tick ---

ACTION_STAT_DELTAS: dict[Action, dict] = {
    Action.SLEEPING: {"energy": +15, "cleanliness": -2, "knowledge": 0},
    Action.STUDYING:  {"energy": -10, "cleanliness": -3, "knowledge": +12},
    Action.CLEANING:  {"energy": -8,  "cleanliness": +18, "knowledge": 0},
    Action.CHILLING:  {"energy": +5,  "cleanliness": -1, "knowledge": 0},
}


def apply_action_tick(stats: CharacterStats, action: Action) -> CharacterStats:
    deltas = ACTION_STAT_DELTAS[action]
    new = stats.model_copy()
    new.energy = max(0, min(100, new.energy + deltas["energy"]))
    new.cleanliness = max(0, min(100, new.cleanliness + deltas["cleanliness"]))
    new.knowledge = max(0, min(100, new.knowledge + deltas["knowledge"]))
    new.mood = _derive_mood(new)
    return new


def _derive_mood(stats: CharacterStats) -> Mood:
    if stats.energy < 20:
        return Mood.TIRED
    if stats.energy > 80 and stats.cleanliness > 70:
        return Mood.ENERGETIC
    if stats.knowledge > 75:
        return Mood.FOCUSED
    if stats.cleanliness < 30 or stats.energy < 40:
        return Mood.GRUMPY
    if stats.energy > 60 and stats.cleanliness > 60:
        return Mood.HAPPY
    return Mood.CHILL
