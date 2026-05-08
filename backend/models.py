import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Action(str, Enum):
    SLEEPING   = "SLEEPING"
    STUDYING   = "STUDYING"
    CLEANING   = "CLEANING"
    CHILLING   = "CHILLING"
    EATING     = "EATING"
    EXERCISING = "EXERCISING"


class Mood(str, Enum):
    HAPPY     = "HAPPY"
    TIRED     = "TIRED"
    GRUMPY    = "GRUMPY"
    FOCUSED   = "FOCUSED"
    CHILL     = "CHILL"
    ENERGETIC = "ENERGETIC"
    HUNGRY    = "HUNGRY"
    EXHAUSTED = "EXHAUSTED"


class CharacterStats(BaseModel):
    energy:      int  = Field(default=70, ge=0, le=100)
    cleanliness: int  = Field(default=70, ge=0, le=100)
    knowledge:   int  = Field(default=50, ge=0, le=100)
    hunger:      int  = Field(default=70, ge=0, le=100)
    mood:        Mood = Mood.CHILL


class Character(BaseModel):
    id:             str           = Field(default_factory=lambda: str(uuid.uuid4()))
    name:           str
    persona:        str
    stats:          CharacterStats = Field(default_factory=CharacterStats)
    current_action: Action         = Action.CHILLING
    created_at:     float          = Field(default_factory=time.time)


# --- Request / Response schemas ---

class CreateCharacterRequest(BaseModel):
    name:          str
    persona:       str
    initial_stats: Optional[CharacterStats] = None


class ChatRequest(BaseModel):
    character_id: str
    message:      str


class ChatResponse(BaseModel):
    character_id:   str
    response:       str
    current_action: Action
    stats:          CharacterStats


# --- Stat delta rules applied each agent tick ---
# hunger decays every tick; EATING is the only way to restore it.

ACTION_STAT_DELTAS: dict[Action, dict] = {
    Action.SLEEPING:   {"energy": +15, "cleanliness": -2,  "knowledge":  0, "hunger": -6},
    Action.STUDYING:   {"energy": -10, "cleanliness": -3,  "knowledge": +12, "hunger": -10},
    Action.CLEANING:   {"energy":  -8, "cleanliness": +18, "knowledge":  0, "hunger": -8},
    Action.CHILLING:   {"energy":  +5, "cleanliness":  -1, "knowledge":  0, "hunger": -6},
    Action.EATING:     {"energy":  +5, "cleanliness":  -2, "knowledge":  0, "hunger": +28},
    Action.EXERCISING: {"energy": -12, "cleanliness":  -8, "knowledge": +3, "hunger": -12},
}


def apply_action_tick(stats: CharacterStats, action: Action) -> CharacterStats:
    deltas = ACTION_STAT_DELTAS[action]
    new = stats.model_copy()
    new.energy      = max(0, min(100, new.energy      + deltas["energy"]))
    new.cleanliness = max(0, min(100, new.cleanliness + deltas["cleanliness"]))
    new.knowledge   = max(0, min(100, new.knowledge   + deltas["knowledge"]))
    new.hunger      = max(0, min(100, new.hunger      + deltas["hunger"]))
    new.mood        = _derive_mood(new)
    return new


def _derive_mood(stats: CharacterStats) -> Mood:
    if stats.hunger < 15:
        return Mood.HUNGRY
    if stats.energy < 10:
        return Mood.EXHAUSTED
    if stats.energy < 25:
        return Mood.TIRED
    if stats.energy > 80 and stats.cleanliness > 70 and stats.hunger > 60:
        return Mood.ENERGETIC
    if stats.knowledge > 75:
        return Mood.FOCUSED
    if stats.cleanliness < 30 or stats.energy < 40:
        return Mood.GRUMPY
    if stats.energy > 60 and stats.cleanliness > 60 and stats.hunger > 50:
        return Mood.HAPPY
    return Mood.CHILL
