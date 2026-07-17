"""Response quality checks for debrief answers.

The goal is not to grade prose but to enforce debrief discipline: an answer
should be substantive, specific, and contain the doctrinal elements the
question is asking for (times, locations, causes, effects, and so on).

Everything here is deterministic and rule-based so an operator can read the
code and understand exactly why a response was flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List

from .models import Expectation, Question

# --------------------------------------------------------------------------- #
# Non-answers and vague filler
# --------------------------------------------------------------------------- #

# Responses that are, on their own, an absence of information.
_NON_ANSWERS = {
    "", "n/a", "na", "none", "nil", "-", "--", "idk", "i don't know",
    "i dont know", "no", "yes", "nothing", "nothing to report", "ntr",
    "same", "as above", "see above", "tbc", "tbd", "?",
}

# Vague phrases that pretend to be answers but carry no observable detail.
_VAGUE_PHRASES = [
    "went well", "went fine", "went ok", "went okay", "all good",
    "no issues", "no problems", "no dramas", "as expected", "as planned",
    "as briefed", "as normal", "nothing major", "nothing significant",
    "pretty good", "pretty bad", "it was fine", "it was good", "it was bad",
    "worked well", "worked fine", "generally good", "overall good",
    "smoothly", "without incident", "uneventful",
]

# --------------------------------------------------------------------------- #
# Expectation detectors
# --------------------------------------------------------------------------- #

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_TIME_PATTERNS = [
    r"\bh-?\s?(?:hour|hr)\b",              # H-hour
    r"\bh\s?[+-]\s?\d+",                   # H+30, H-10
    r"\b\d{3,4}\s?(?:hrs?|z|zulu|local)\b",  # 0530hrs, 1300Z
    r"\b\d{1,2}:\d{2}\b",                   # 05:30
    r"\b\d{1,2}\s?(?:am|pm)\b",            # 5pm
    r"\b\d+\s?(?:sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?|days?)\b",  # durations
    r"\b(?:" + _MONTHS + r")\b",           # month names
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",  # dates 12/06
]

_LOCATION_PATTERNS = [
    r"\b\d{1,2}[a-z]{3}\s?[a-z]{2}\s?\d{4,10}\b",  # rough MGRS: 33UXP1234 5678
    r"\bgrid\b", r"\bvic(?:inity)?\b", r"\bcheckpoint\b", r"\bcp\s?\d",
    r"\bobj(?:ective)?\b", r"\brally\b", r"\brv\b", r"\bphase line\b",
    r"\bpl\s+\w+", r"\bnai\b", r"\bwaypoint\b", r"\bcoord(?:inate)?s?\b",
    r"\b(?:north|south|east|west|ne|nw|se|sw)\b.*\b\d",  # bearing + distance
    r"\b\d+\s?(?:m|km|metres|meters|kilometres|kilometers|klicks?)\b",
    r"\broute\s+\w+", r"\bbuilding\s+\w+", r"\bcompound\b",
]

_QUANTITY_PATTERNS = [
    r"\b\d+\b",                            # any explicit number
    r"\bx\d+\b", r"\b\d+x\b",              # 3x / x3
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|dozen)\b",
    r"\b\d+\s?(?:pax|personnel|rounds|rds|mags|casualt|kia|wia|vehicles?)\b",
]

_CAUSAL_MARKERS = [
    "because", "due to", "owing to", "as a result", "resulted in", "led to",
    "caused", "cause was", "since", "therefore", "so that", "which meant",
    "meant that", "root cause", "driven by", "on account of", "this was why",
    "the reason",
]

_ACTION_MARKERS = [
    "moved", "assaulted", "cleared", "secured", "occupied", "engaged",
    "suppressed", "flanked", "withdrew", "extracted", "inserted", "breached",
    "established", "reported", "called", "requested", "returned fire",
    "took cover", "maneuvered", "manoeuvred", "advanced", "halted", "deployed",
    "conducted", "executed", "provided", "covered", "bounded", "consolidated",
    "reorganised", "reorganized", "patrolled", "observed", "identified",
]

_OUTCOME_MARKERS = [
    "achieved", "accomplished", "succeeded", "failed", "destroyed",
    "neutralised", "neutralized", "suppressed", "secured", "captured",
    "cleared", "enabled", "prevented", "delayed", "resulted", "effect",
    "denied", "disrupted", "casualt", "no effect", "on target", "mission",
    "objective met", "objective not", "partially", "fully",
]

_COMPARISON_MARKERS = [
    "planned", "instead", "rather than", "as opposed to", "compared",
    "expected", "actual", "deviat", "unlike", "however", "but the plan",
    "vs", "versus", "differed", "in contrast", "whereas", "originally",
]

_ASSESSMENT_MARKERS = [
    "should", "need to", "needs to", "improve", "sustain", "better",
    "worked", "did not work", "didn't work", "well", "poorly", "recommend",
    "issue", "shortfall", "strength", "weakness", "went wrong", "went right",
    "effective", "ineffective", "must",
]

_RECOMMENDATION_MARKERS = [
    "recommend", "should", "must", "propose", "action:", "assign", "own",
    "responsible", "by end", "nlt", "no later than", "next time", "in future",
    "training", "update the", "revise", "add to", "brief", "task",
]


def _matches_any_regex(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _contains_any(text: str, markers: List[str]) -> bool:
    return any(m in text for m in markers)


# Map each expectation to a detector that returns True when the response
# appears to satisfy it.
_DETECTORS: Dict[Expectation, Callable[[str], bool]] = {
    Expectation.TIME: lambda t: _matches_any_regex(t, _TIME_PATTERNS),
    Expectation.LOCATION: lambda t: _matches_any_regex(t, _LOCATION_PATTERNS),
    Expectation.QUANTITY: lambda t: _matches_any_regex(t, _QUANTITY_PATTERNS),
    Expectation.CAUSAL: lambda t: _contains_any(t, _CAUSAL_MARKERS),
    Expectation.ACTION: lambda t: _contains_any(t, _ACTION_MARKERS),
    Expectation.OUTCOME: lambda t: _contains_any(t, _OUTCOME_MARKERS),
    Expectation.COMPARISON: lambda t: _contains_any(t, _COMPARISON_MARKERS),
    Expectation.ASSESSMENT: lambda t: _contains_any(t, _ASSESSMENT_MARKERS),
    Expectation.RECOMMENDATION: lambda t: _contains_any(t, _RECOMMENDATION_MARKERS),
}


# --------------------------------------------------------------------------- #
# Assessment result
# --------------------------------------------------------------------------- #

class QualityLevel(str, Enum):
    """Overall quality band for a response."""

    EMPTY = "empty"        # no usable information
    WEAK = "weak"          # too short or too vague to be useful
    ADEQUATE = "adequate"  # acceptable, minor gaps
    STRONG = "strong"      # substantive and specific


@dataclass
class ResponseAssessment:
    """The result of quality-checking one response."""

    question_id: str
    word_count: int
    level: QualityLevel
    score: int  # 0-100
    satisfied: List[Expectation] = field(default_factory=list)
    missing: List[Expectation] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether the response clears the debrief quality bar."""
        return self.level in (QualityLevel.ADEQUATE, QualityLevel.STRONG)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_non_answer(normalised_lower: str) -> bool:
    return normalised_lower in _NON_ANSWERS


def _vague_phrase_hits(text_lower: str) -> List[str]:
    return [p for p in _VAGUE_PHRASES if p in text_lower]


def assess_response(question: Question, response: str) -> ResponseAssessment:
    """Quality-check a single response against its doctrinal question."""

    normalised = _normalise(response)
    lower = normalised.lower()
    words = normalised.split()
    word_count = len(words)

    # Empty / non-answer: nothing usable.
    if _is_non_answer(lower) or word_count == 0:
        return ResponseAssessment(
            question_id=question.id,
            word_count=word_count,
            level=QualityLevel.EMPTY,
            score=0,
            missing=list(question.expects),
            issues=["No usable information was provided."],
        )

    satisfied = [e for e in question.expects if _DETECTORS[e](lower)]
    missing = [e for e in question.expects if e not in satisfied]

    issues: List[str] = []

    # Substance check against the question's minimum.
    too_short = word_count < question.min_words
    if too_short:
        issues.append(
            f"Response is brief ({word_count} words; expected at least "
            f"{question.min_words}). Add specifics."
        )

    # Vagueness check.
    vague_hits = _vague_phrase_hits(lower)
    # Only treat vagueness as damning when the answer is also thin; a long,
    # detailed answer that happens to contain "went well" is fine.
    vague_dominates = bool(vague_hits) and word_count < question.min_words * 2
    if vague_dominates:
        issues.append(
            "Response is vague ("
            + ", ".join(f'"{v}"' for v in vague_hits[:3])
            + "). State observable facts instead."
        )

    for exp in missing:
        issues.append(f"Missing detail: {exp.value}.")

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #
    score = 100

    # Substance component.
    if question.min_words:
        ratio = min(word_count / question.min_words, 1.0)
        score -= int((1.0 - ratio) * 30)

    # Expectation coverage component.
    if question.expects:
        coverage = len(satisfied) / len(question.expects)
        score -= int((1.0 - coverage) * 50)

    # Vagueness penalty.
    if vague_dominates:
        score -= 20

    score = max(0, min(100, score))

    # ------------------------------------------------------------------ #
    # Level
    # ------------------------------------------------------------------ #
    missing_required_detail = bool(missing) or too_short or vague_dominates

    if score >= 80 and not missing_required_detail:
        level = QualityLevel.STRONG
    elif score >= 55 and not too_short and not vague_dominates:
        level = QualityLevel.ADEQUATE
    else:
        level = QualityLevel.WEAK

    return ResponseAssessment(
        question_id=question.id,
        word_count=word_count,
        level=level,
        score=score,
        satisfied=satisfied,
        missing=missing,
        issues=issues,
    )
