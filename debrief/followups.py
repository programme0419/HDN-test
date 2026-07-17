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

from dataclasses import dataclass
from typing import List

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
