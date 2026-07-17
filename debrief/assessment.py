"""Unified response evaluation: rule-based baseline plus optional LLM.

This module is the single entry point the session uses to evaluate an answer.
It always computes the deterministic rule-based assessment first, then \u2014 when
an LLM is configured and the answer is worth spending a call on \u2014 asks the
model to judge doctrinal completeness and propose follow-up questions.

The LLM output is treated as advisory and strictly validated against the
project's own vocabulary. If the model is unavailable, errors, or returns
something unusable, the rule-based result is used unchanged. The tool therefore
behaves identically offline, just with less nuance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .followups import MAX_FOLLOW_UPS, FollowUp, generate_follow_ups
from .llm import LLMClient, LLMError
from .models import Expectation, Phase, Question
from .quality import QualityLevel, ResponseAssessment, assess_response


@dataclass
class Evaluation:
    """The combined verdict on a single response."""

    question_id: str
    source: str  # "rules" or "llm"
    passed: bool
    score: int
    level: QualityLevel
    satisfied: List[Expectation] = field(default_factory=list)
    missing: List[Expectation] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    follow_ups: List[FollowUp] = field(default_factory=list)
    coaching: Optional[str] = None  # short freeform note from the LLM
    rule_assessment: Optional[ResponseAssessment] = None

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "source": self.source,
            "passed": self.passed,
            "score": self.score,
            "level": self.level.value,
            "satisfied": [e.value for e in self.satisfied],
            "missing": [e.value for e in self.missing],
            "issues": list(self.issues),
            "follow_ups": [
                {
                    "prompt": f.prompt,
                    "reason": f.reason,
                    "expectation": f.expectation.value if f.expectation else None,
                }
                for f in self.follow_ups
            ],
            "coaching": self.coaching,
        }


def _from_rules(question: Question, assessment: ResponseAssessment) -> Evaluation:
    return Evaluation(
        question_id=question.id,
        source="rules",
        passed=assessment.passed,
        score=assessment.score,
        level=assessment.level,
        satisfied=list(assessment.satisfied),
        missing=list(assessment.missing),
        issues=list(assessment.issues),
        follow_ups=generate_follow_ups(question, assessment),
        rule_assessment=assessment,
    )


_SYSTEM_PROMPT = (
    "You are an experienced After-Action Review (AAR) facilitator assessing a "
    "military operator's debrief answer. Judge only whether the answer is "
    "doctrinally complete, specific, and actionable \u2014 never the operator "
    "personally, and never the tactical decisions themselves. Be concise and "
    "reply with a single JSON object only."
)

_VALID_EXPECTATIONS = {e.value for e in Expectation}


def _build_user_prompt(question: Question, response: str) -> str:
    expected = ", ".join(e.value for e in question.expects) or "(none specified)"
    return (
        "Doctrinal question:\n"
        f"  {question.prompt}\n\n"
        f"Why it is asked: {question.intent}\n"
        f"Doctrine reference: {question.doctrine_ref}\n"
        f"Expected elements a complete answer should contain: {expected}\n"
        f"Minimum expected substance: about {question.min_words} words.\n\n"
        "Operator's answer:\n"
        f"  \"\"\"{response.strip()}\"\"\"\n\n"
        "Return a JSON object with exactly these keys:\n"
        '  "score": integer 0-100 for doctrinal completeness,\n'
        '  "level": one of "empty", "weak", "adequate", "strong",\n'
        '  "satisfied": array of expected elements the answer covers,\n'
        '  "missing": array of expected elements still missing,\n'
        '  "issues": array of short strings naming concrete gaps,\n'
        '  "follow_ups": array (max 2) of {"prompt": string, "reason": string} '
        "targeted questions to close the most important gaps,\n"
        '  "coaching": one short sentence of guidance for the operator.\n'
        "Only use these element names: "
        + ", ".join(sorted(_VALID_EXPECTATIONS))
        + ".\n"
        "If the answer already fully meets the bar, return an empty follow_ups array."
    )


def _coerce_expectations(values) -> List[Expectation]:
    result: List[Expectation] = []
    if not isinstance(values, list):
        return result
    for value in values:
        if isinstance(value, str) and value.lower() in _VALID_EXPECTATIONS:
            exp = Expectation(value.lower())
            if exp not in result:
                result.append(exp)
    return result


def _coerce_level(value, score: int) -> QualityLevel:
    if isinstance(value, str):
        try:
            return QualityLevel(value.lower())
        except ValueError:
            pass
    # Derive from score if the model gave something unexpected.
    if score <= 0:
        return QualityLevel.EMPTY
    if score >= 80:
        return QualityLevel.STRONG
    if score >= 55:
        return QualityLevel.ADEQUATE
    return QualityLevel.WEAK


def _parse_follow_ups(question: Question, raw) -> List[FollowUp]:
    follow_ups: List[FollowUp] = []
    if not isinstance(raw, list):
        return follow_ups
    for item in raw:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt", "")).strip()
        if not prompt:
            continue
        reason = str(item.get("reason", "")).strip() or "Targeted follow-up."
        follow_ups.append(
            FollowUp(question_id=question.id, prompt=prompt, reason=reason)
        )
        if len(follow_ups) >= MAX_FOLLOW_UPS:
            break
    return follow_ups


def _from_llm(question: Question, response: str, data: dict) -> Evaluation:
    """Validate a parsed LLM response into an Evaluation, raising on garbage."""
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        raise LLMError("LLM response missing a valid integer score.")
    score = max(0, min(100, score))

    level = _coerce_level(data.get("level"), score)
    satisfied = _coerce_expectations(data.get("satisfied"))
    missing = _coerce_expectations(data.get("missing"))

    issues_raw = data.get("issues")
    issues = [str(i).strip() for i in issues_raw if str(i).strip()] if isinstance(issues_raw, list) else []

    follow_ups = _parse_follow_ups(question, data.get("follow_ups"))

    coaching_raw = data.get("coaching")
    coaching = str(coaching_raw).strip() if coaching_raw else None

    passed = level in (QualityLevel.ADEQUATE, QualityLevel.STRONG)

    return Evaluation(
        question_id=question.id,
        source="llm",
        passed=passed,
        score=score,
        level=level,
        satisfied=satisfied,
        missing=missing,
        issues=issues,
        follow_ups=follow_ups,
        coaching=coaching,
    )


class Evaluator:
    """Evaluates responses using the rule engine, with optional LLM nuance."""

    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client if client is not None else LLMClient()

    @property
    def llm_active(self) -> bool:
        return bool(self.client) and self.client.available

    def evaluate(self, question: Question, response: str) -> Evaluation:
        assessment = assess_response(question, response)

        # Always short-circuit non-answers deterministically \u2014 no reason to
        # spend an API call to be told an empty box is empty.
        if not self.llm_active or assessment.level == QualityLevel.EMPTY:
            return _from_rules(question, assessment)

        try:
            data = self.client.chat_json(
                _SYSTEM_PROMPT,
                _build_user_prompt(question, response),
            )
            evaluation = _from_llm(question, response, data)
        except LLMError:
            return _from_rules(question, assessment)

        # Keep the rule assessment attached for transparency / auditing.
        evaluation.rule_assessment = assessment
        # If the LLM says the answer falls short but proposes no follow-ups,
        # borrow the deterministic ones so the operator is never left without
        # guidance.
        if not evaluation.passed and not evaluation.follow_ups:
            evaluation.follow_ups = generate_follow_ups(question, assessment)
        return evaluation


# --------------------------------------------------------------------------- #
# Aggregate scoring
#
# The session-level score rolls the individual evaluations up into a status per
# doctrinal section and a single headline number out of 100. Completeness is
# rewarded: a required question left unanswered counts against the section and
# the overall score, so operators cannot inflate the result by skipping the
# hard questions.
# --------------------------------------------------------------------------- #

STATUS_COMPLETE = "Complete"
STATUS_PARTIAL = "Needs more detail"
STATUS_MISSING = "Not addressed"

# A section's average quality must reach this to be marked complete.
_SECTION_COMPLETE_THRESHOLD = 70


@dataclass
class SectionScore:
    """Roll-up of a single doctrinal section (phase)."""

    phase: str
    status: str
    score: int          # average quality of answered questions, 0-100
    answered: int
    total: int
    required_total: int
    required_answered: int

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "status": self.status,
            "score": self.score,
            "answered": self.answered,
            "total": self.total,
            "required_total": self.required_total,
            "required_answered": self.required_answered,
        }


@dataclass
class DebriefScore:
    """The headline quality picture for a whole debrief."""

    overall: int
    sections: List[SectionScore] = field(default_factory=list)
    answered: int = 0
    total: int = 0

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "answered": self.answered,
            "total": self.total,
            "sections": [s.to_dict() for s in self.sections],
        }


def _is_answered(evaluation: Optional[Evaluation]) -> bool:
    return evaluation is not None and evaluation.level != QualityLevel.EMPTY


def score_debrief(
    graded: Sequence[Tuple[Question, Optional[Evaluation]]],
) -> DebriefScore:
    """Aggregate per-question evaluations into section and overall scores.

    ``graded`` pairs every question in the debrief with its evaluation (or
    ``None`` if it was never answered). Sections are reported in doctrinal
    phase order.
    """

    by_phase: Dict[Phase, List[Tuple[Question, Optional[Evaluation]]]] = {}
    order: List[Phase] = []
    for question, evaluation in graded:
        if question.phase not in by_phase:
            by_phase[question.phase] = []
            order.append(question.phase)
        by_phase[question.phase].append((question, evaluation))

    sections: List[SectionScore] = []
    overall_points: List[int] = []
    answered_total = 0
    question_total = 0

    for phase in order:
        pairs = by_phase[phase]
        total = len(pairs)
        answered_scores = [e.score for _, e in pairs if _is_answered(e)]
        answered = len(answered_scores)
        required_total = sum(1 for q, _ in pairs if q.required)
        required_answered = sum(
            1 for q, e in pairs if q.required and _is_answered(e)
        )

        section_score = round(sum(answered_scores) / answered) if answered else 0

        if answered == 0:
            status = STATUS_MISSING
        elif required_answered >= required_total and section_score >= _SECTION_COMPLETE_THRESHOLD:
            status = STATUS_COMPLETE
        else:
            status = STATUS_PARTIAL

        sections.append(
            SectionScore(
                phase=phase.value,
                status=status,
                score=section_score,
                answered=answered,
                total=total,
                required_total=required_total,
                required_answered=required_answered,
            )
        )

        # Overall: every question contributes. Answered questions contribute
        # their quality score; a required question left unanswered contributes
        # zero; an optional unanswered question is excluded so skipping the
        # non-mandatory ones is not punished.
        for question, evaluation in pairs:
            question_total += 1
            if _is_answered(evaluation):
                answered_total += 1
                overall_points.append(evaluation.score)
            elif question.required:
                overall_points.append(0)

    overall = round(sum(overall_points) / len(overall_points)) if overall_points else 0

    return DebriefScore(
        overall=overall,
        sections=sections,
        answered=answered_total,
        total=question_total,
    )
