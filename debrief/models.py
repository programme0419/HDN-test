"""Core data types shared across the debrief engine.

These types are intentionally small and dependency-free so the doctrine bank,
the quality checks, and the follow-up generator can all speak the same
vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple


class Expectation(str, Enum):
    """What a doctrinally complete answer to a question should contain.

    Quality checks use these tags to decide whether a response is specific
    enough, and the follow-up generator uses them to ask for the missing piece.
    """

    TIME = "time"              # timeframe: H-hour, timestamps, duration
    LOCATION = "location"      # grid reference or named location
    QUANTITY = "quantity"      # counts: personnel, rounds, casualties, distance
    CAUSAL = "causal"          # explanation of why something happened
    ACTION = "action"          # concrete actions that were taken
    OUTCOME = "outcome"        # the result or effect of an action
    COMPARISON = "comparison"  # planned vs. actual
    ASSESSMENT = "assessment"  # a sustain / improve judgement
    RECOMMENDATION = "recommendation"  # an actionable recommendation


class Phase(str, Enum):
    """The doctrinal phases of an After-Action Review, in debrief order."""

    OVERVIEW = "Mission Overview"
    PLANNING = "Planning & Preparation"
    EXECUTION = "Execution & Sequence of Events"
    ENEMY = "Enemy & Threat"
    FRIENDLY = "Friendly Forces & Actions"
    FIRES = "Fires & Effects"
    COMMS = "Communications & C2"
    SUSTAINMENT = "Casualties & Sustainment"
    ASSESSMENT = "Assessment (Sustain / Improve)"
    LESSONS = "Lessons Learned & Follow-up"


@dataclass(frozen=True)
class Question:
    """A single doctrinal debrief question and how to evaluate its answer."""

    id: str
    phase: Phase
    prompt: str
    intent: str
    doctrine_ref: str
    expects: Tuple[Expectation, ...] = ()
    required: bool = True
    min_words: int = 8
    # Optional targeted follow-up wording, keyed by the expectation that is
    # missing from a response. Falls back to a generic prompt when absent.
    follow_ups: Dict[Expectation, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Question.id must be non-empty")
        if not self.prompt:
            raise ValueError(f"Question {self.id!r} must have a prompt")


# The mission types offered in the metadata step. Kept broad; "Other" lets an
# operator record anything not listed.
MISSION_TYPES: Tuple[str, ...] = (
    "Reconnaissance",
    "Direct Action",
    "Security / Patrol",
    "Ambush",
    "Raid",
    "Cordon & Search",
    "Convoy / Escort",
    "Defensive Operation",
    "Humanitarian / Support",
    "Training Exercise",
    "Other",
)


@dataclass
class MissionMetadata:
    """Identifying information for the mission being debriefed.

    Captured before the doctrinal questions so every debrief record is
    attributable to a specific mission, unit, time, and place.
    """

    mission_name: str = ""
    date_time: str = ""      # free-text date/time, e.g. "2026-07-17 0530Z"
    unit: str = ""
    location: str = ""
    mission_type: str = ""
    participants: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Return a list of human-readable validation errors (empty if valid)."""
        errors: List[str] = []
        if not self.mission_name.strip():
            errors.append("Mission name is required.")
        if not self.date_time.strip():
            errors.append("Mission date/time is required.")
        if not self.unit.strip():
            errors.append("Unit is required.")
        if not self.location.strip():
            errors.append("Location is required.")
        if not self.mission_type.strip():
            errors.append("Mission type is required.")
        elif self.mission_type not in MISSION_TYPES:
            errors.append(
                "Mission type must be one of: " + ", ".join(MISSION_TYPES) + "."
            )
        cleaned = [p for p in (self.participants or []) if str(p).strip()]
        if not cleaned:
            errors.append("At least one participant is required.")
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()

    def normalised(self) -> "MissionMetadata":
        """Return a copy with surrounding whitespace stripped and blanks dropped."""
        return MissionMetadata(
            mission_name=self.mission_name.strip(),
            date_time=self.date_time.strip(),
            unit=self.unit.strip(),
            location=self.location.strip(),
            mission_type=self.mission_type.strip(),
            participants=[p.strip() for p in (self.participants or []) if str(p).strip()],
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "mission_name": self.mission_name,
            "date_time": self.date_time,
            "unit": self.unit,
            "location": self.location,
            "mission_type": self.mission_type,
            "participants": list(self.participants),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "MissionMetadata":
        data = data or {}
        participants = data.get("participants") or []
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split(",") if p.strip()]
        return cls(
            mission_name=str(data.get("mission_name", "") or ""),
            date_time=str(data.get("date_time", "") or ""),
            unit=str(data.get("unit", "") or ""),
            location=str(data.get("location", "") or ""),
            mission_type=str(data.get("mission_type", "") or ""),
            participants=[str(p) for p in participants],
        )
