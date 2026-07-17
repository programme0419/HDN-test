"""Follow-up question generation.

When a response fails a quality check, the debrief should not simply move on.
This module turns the gaps found by :mod:`debrief.quality` into specific,
doctrinally worded follow-up questions that guide the operator toward a
complete answer.

Follow-ups are prioritised so the most important gap is asked first, and the
number asked per question is capped so a debrief does not turn into an
interrogation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Expectation, Question
from .quality import QualityLevel, ResponseAssessment

# Generic wording used when a question does not define a bespoke follow-up for
# a given missing expectation.
_GENERIC_FOLLOW_UPS = {
    Expectation.TIME: "When did this happen? Give approximate times or a timeframe.",
    Expectation.LOCATION: "Where did this happen? Provide a grid, route, or named location.",
    Expectation.QUANTITY: "Can you quantify that \u2014 how many, how much, or how far?",
    Expectation.CAUSAL: "Why did that happen? Identify the cause, not just the event.",
    Expectation.ACTION: "What specific actions were taken, and by whom?",
    Expectation.OUTCOME: "What was the effect or result of that?",
    Expectation.COMPARISON: "How did that compare to what was planned or expected?",
    Expectation.ASSESSMENT: "Was that a strength or a shortfall, and why?",
    Expectation.RECOMMENDATION: "What concrete corrective action do you recommend, and who owns it?",
}

# Order in which missing expectations are worth chasing. Facts that anchor the
# timeline and causation come before softer judgement calls.
_PRIORITY = [
    Expectation.CAUSAL,
    Expectation.OUTCOME,
    Expectation.TIME,
    Expectation.LOCATION,
    Expectation.QUANTITY,
    Expectation.ACTION,
    Expectation.COMPARISON,
    Expectation.RECOMMENDATION,
    Expectation.ASSESSMENT,
]

# Maximum number of follow-ups to raise for a single question at one time.
MAX_FOLLOW_UPS = 2


@dataclass
class FollowUp:
    """A single generated follow-up question."""

    question_id: str          # the parent question this follows up on
    prompt: str               # the follow-up wording shown to the operator
    reason: str               # why it is being asked (for transparency)
    expectation: Expectation | None = None  # the gap it targets, if any


def _prioritised_missing(missing: List[Expectation]) -> List[Expectation]:
    ranked = sorted(
        missing,
        key=lambda e: _PRIORITY.index(e) if e in _PRIORITY else len(_PRIORITY),
    )
    return ranked


def generate_follow_ups(
    question: Question,
    assessment: ResponseAssessment,
) -> List[FollowUp]:
    """Produce follow-up questions for a response that fell short.

    Returns an empty list when the response already clears the quality bar.
    """

    # A strong, complete answer needs no follow-up.
    if assessment.passed and not assessment.missing:
        return []

    follow_ups: List[FollowUp] = []

    # An empty / non-answer gets a single, direct re-ask rather than a list of
    # element-by-element prompts.
    if assessment.level == QualityLevel.EMPTY:
        return [
            FollowUp(
                question_id=question.id,
                prompt="That question was not answered. Please provide the details asked for.",
                reason="No usable information was captured.",
            )
        ]

    # Chase the missing doctrinal elements, most important first.
    for expectation in _prioritised_missing(assessment.missing):
        if len(follow_ups) >= MAX_FOLLOW_UPS:
            break
        prompt = question.follow_ups.get(expectation) or _GENERIC_FOLLOW_UPS[expectation]
        follow_ups.append(
            FollowUp(
                question_id=question.id,
                prompt=prompt,
                reason=f"Response did not address: {expectation.value}.",
                expectation=expectation,
            )
        )

    # If nothing was missing but the answer was still weak (short or vague),
    # ask a single broad expansion prompt.
    if not follow_ups and not assessment.passed:
        follow_ups.append(
            FollowUp(
                question_id=question.id,
                prompt="Expand on that with specific, observable detail (times, "
                "places, numbers, and effects).",
                reason="Response was too brief or too vague to be actionable.",
            )
        )

    return follow_ups


# --------------------------------------------------------------------------- #
# Contextual follow-ups: guided branching + keyword triggers
#
# These fire on the *content* of an answer regardless of whether it passed the
# quality bar, mirroring how a facilitator digs into a specific topic the
# operator raised (a mentioned system failure) or a decisive yes/no.
# --------------------------------------------------------------------------- #

_AFFIRMATIVE = re.compile(
    r"\b(yes|affirmative|achieved|accomplished|successful|success|complete[d]?|"
    r"met|attained|yep|correct)\b"
)
_NEGATIVE = re.compile(
    r"\b(no|negative|not achieved|unsuccessful|fail(?:ed|ure)?|did not|didn't|"
    r"unable|incomplete|aborted|not met|partially)\b"
)

# Per-question yes/no branches. When the answer reads as affirmative or
# negative, ask the matching branch questions. Keyed by question id.
_BRANCH_RULES: Dict[str, Dict[str, List[str]]] = {
    "ov-result": {
        "affirmative": [
            "What specific, observable evidence confirms the objective was achieved?",
        ],
        "negative": [
            "What prevented success \u2014 enemy activity, equipment, communications, "
            "weather, or something else? Name the primary factor.",
        ],
    },
}

# Keyword triggers: if any keyword appears, raise the associated follow-ups.
# (keywords, follow-up prompts). Order matters only for presentation.
_KEYWORD_RULES: List[Tuple[Tuple[str, ...], List[str]]] = [
    (
        ("communication", "comms", "radio", "net ", "signal", "antenna"),
        [
            "Which communications system or net degraded or failed?",
            "How long was the degradation, and what was the mission impact?",
        ],
    ),
    (
        ("equipment", "kit", "weapon", "optic", "nvg", "vehicle", "gps", "battery"),
        [
            "Which specific equipment was involved, and what was the failure mode?",
            "What workaround was used, and how did it affect the mission?",
        ],
    ),
    (
        ("casualt", "wounded", "injur", "kia", "wia", "medevac", "casevac"),
        [
            "How many casualties, of what category, and what was the evacuation timeline?",
        ],
    ),
    (
        ("weather", "rain", "fog", "wind", "visibility", "storm", "heat", "cold"),
        [
            "How did the weather specifically affect movement, sensors, or timings?",
        ],
    ),
    (
        ("ambush", "ied", "contact", "engaged", "fire"),
        [
            "Describe the contact using SALUTE (size, activity, location, unit, time, equipment).",
        ],
    ),
]


def _branch_key(response_lower: str) -> str | None:
    """Classify a response as affirmative/negative for branching, or None."""
    neg = _NEGATIVE.search(response_lower)
    aff = _AFFIRMATIVE.search(response_lower)
    if neg and not aff:
        return "negative"
    if aff and not neg:
        return "affirmative"
    if aff and neg:
        # Both present (e.g. "partially achieved but ..."): treat as negative so
        # the operator is pushed to explain the shortfall.
        return "negative"
    return None


def contextual_follow_ups(question: Question, response: str) -> List[FollowUp]:
    """Follow-ups driven by the content of the answer (branches + keywords)."""

    lower = (response or "").lower()
    follow_ups: List[FollowUp] = []
    seen_prompts = set()

    def _add(prompt: str, reason: str, expectation: Expectation | None = None) -> None:
        if prompt not in seen_prompts:
            seen_prompts.add(prompt)
            follow_ups.append(
                FollowUp(
                    question_id=question.id,
                    prompt=prompt,
                    reason=reason,
                    expectation=expectation,
                )
            )

    branch = _BRANCH_RULES.get(question.id)
    if branch:
        key = _branch_key(lower)
        if key and branch.get(key):
            for prompt in branch[key]:
                _add(prompt, reason=f"Branch follow-up for a {key} answer.")

    for keywords, prompts in _KEYWORD_RULES:
        if any(k in lower for k in keywords):
            topic = keywords[0]
            for prompt in prompts:
                _add(prompt, reason=f'You mentioned "{topic}"; drilling into specifics.')

    return follow_ups
