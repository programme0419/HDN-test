"""Core data types shared across the debrief engine.

These types are intentionally small and dependency-free so the doctrine bank,
the quality checks, and the follow-up generator can all speak the same
vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Tuple


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
