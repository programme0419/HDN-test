"""Debrief session orchestration.

A :class:`DebriefSession` is the state machine that drives a debrief from end
to end:

    mission metadata  ->  walk the doctrinal questions in phase order  ->
    for each question, assess the answer and, while it falls short (or raises a
    topic worth chasing), ask targeted follow-ups up to a cap  ->  advance  ->
    complete.

Follow-up answers accumulate onto the question they belong to, so the operator
progressively builds one complete answer rather than a scattered thread. The
whole session is serialisable to a plain dict so it can be persisted and
resumed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from . import doctrine
from .assessment import DebriefScore, Evaluation, Evaluator, score_debrief
from .followups import contextual_follow_ups
from .models import MissionMetadata, Question

# Maximum follow-ups asked for any single question before moving on, so a
# debrief guides without becoming an interrogation.
FOLLOW_UP_CAP = 2


class SessionState(str, Enum):
    METADATA = "metadata"        # collecting mission metadata
    IN_PROGRESS = "in_progress"  # walking the doctrinal questions
    COMPLETE = "complete"        # every question addressed


@dataclass
class PendingPrompt:
    """The prompt currently awaiting an answer (a base question or follow-up)."""

    prompt: str
    is_follow_up: bool
    reason: str = ""


@dataclass
class QuestionRecord:
    """Everything captured for one doctrinal question during the debrief."""

    question_id: str
    answers: List[str] = field(default_factory=list)
    asked_follow_ups: List[Dict[str, str]] = field(default_factory=list)
    pending_follow_up: Optional[Dict[str, str]] = None
    evaluation: Optional[Evaluation] = None
    done: bool = False
    skipped: bool = False

    @property
    def combined_answer(self) -> str:
        return " ".join(a.strip() for a in self.answers if a.strip()).strip()

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "answers": list(self.answers),
            "asked_follow_ups": list(self.asked_follow_ups),
            "pending_follow_up": self.pending_follow_up,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "done": self.done,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionRecord":
        evaluation = None
        if data.get("evaluation"):
            evaluation = Evaluation.from_dict(data["evaluation"])
        return cls(
            question_id=data["question_id"],
            answers=list(data.get("answers") or []),
            asked_follow_ups=list(data.get("asked_follow_ups") or []),
            pending_follow_up=data.get("pending_follow_up"),
            evaluation=evaluation,
            done=bool(data.get("done", False)),
            skipped=bool(data.get("skipped", False)),
        )


class DebriefSession:
    """Stateful orchestration of a single debrief."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        metadata: Optional[MissionMetadata] = None,
        evaluator: Optional[Evaluator] = None,
        question_ids: Optional[List[str]] = None,
    ) -> None:
        self.id = session_id or uuid.uuid4().hex
        self.metadata = metadata or MissionMetadata()
        self.evaluator = evaluator or Evaluator()
        self.state = SessionState.METADATA
        self.created_at = time.time()
        self.updated_at = self.created_at

        ids = question_ids or [q.id for q in doctrine.QUESTION_BANK]
        self.order: List[str] = ids
        self.current_index = 0
        self.records: Dict[str, QuestionRecord] = {
            qid: QuestionRecord(question_id=qid) for qid in ids
        }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def set_metadata(self, metadata: MissionMetadata) -> List[str]:
        """Validate and store metadata; on success move to the questions.

        Returns the list of validation errors (empty means the session started).
        """
        errors = metadata.validate()
        if errors:
            return errors
        self.metadata = metadata.normalised()
        self.state = SessionState.IN_PROGRESS
        self._touch()
        return []

    @property
    def llm_active(self) -> bool:
        return self.evaluator.llm_active

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #
    def current_question(self) -> Optional[Question]:
        if self.state != SessionState.IN_PROGRESS:
            return None
        if self.current_index >= len(self.order):
            return None
        return doctrine.get_question(self.order[self.current_index])

    def current_record(self) -> Optional[QuestionRecord]:
        question = self.current_question()
        return self.records[question.id] if question else None

    def current_prompt(self) -> Optional[PendingPrompt]:
        """The prompt the operator should answer right now."""
        question = self.current_question()
        if not question:
            return None
        record = self.records[question.id]
        if record.pending_follow_up:
            return PendingPrompt(
                prompt=record.pending_follow_up["prompt"],
                is_follow_up=True,
                reason=record.pending_follow_up.get("reason", ""),
            )
        return PendingPrompt(prompt=question.prompt, is_follow_up=False)

    # ------------------------------------------------------------------ #
    # Answering
    # ------------------------------------------------------------------ #
    def submit_answer(self, text: str) -> Optional[Evaluation]:
        """Record an answer, evaluate it, and queue a follow-up or advance."""
        question = self.current_question()
        if not question:
            return None
        record = self.records[question.id]

        record.answers.append(text or "")
        record.pending_follow_up = None  # this answer resolves any pending ask

        combined = record.combined_answer
        evaluation = self.evaluator.evaluate(question, combined)
        record.evaluation = evaluation

        next_follow_up = self._next_follow_up(question, combined, record, evaluation)
        if next_follow_up is None:
            record.done = True
            self._advance()
        else:
            record.asked_follow_ups.append(next_follow_up)
            record.pending_follow_up = next_follow_up

        self._touch()
        return evaluation

    def skip_current(self) -> None:
        """Skip the current question (records it as unanswered) and advance."""
        record = self.current_record()
        if record:
            record.done = True
            record.skipped = True
            record.pending_follow_up = None
            self._advance()
            self._touch()

    def _next_follow_up(
        self,
        question: Question,
        combined: str,
        record: QuestionRecord,
        evaluation: Evaluation,
    ) -> Optional[Dict[str, str]]:
        """Pick the next follow-up to ask, or None to advance."""
        if len(record.asked_follow_ups) >= FOLLOW_UP_CAP:
            return None

        asked_prompts = {f["prompt"] for f in record.asked_follow_ups}

        candidates: List[Tuple[str, str]] = []
        # Quality / LLM driven gaps first (these are absent when the answer is
        # already complete).
        for fu in evaluation.follow_ups:
            candidates.append((fu.prompt, fu.reason))
        # Then content-driven branch / keyword follow-ups.
        for fu in contextual_follow_ups(question, combined):
            candidates.append((fu.prompt, fu.reason))

        for prompt, reason in candidates:
            if prompt not in asked_prompts:
                return {"prompt": prompt, "reason": reason}
        return None

    def _advance(self) -> None:
        self.current_index += 1
        if self.current_index >= len(self.order):
            self.state = SessionState.COMPLETE

    def _touch(self) -> None:
        self.updated_at = time.time()

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def progress(self) -> dict:
        answered = sum(
            1 for r in self.records.values() if r.done and not r.skipped
        )
        total = len(self.order)
        completed_steps = sum(1 for r in self.records.values() if r.done)
        percent = round((completed_steps / total) * 100) if total else 0
        return {
            "answered": answered,
            "total": total,
            "completed": completed_steps,
            "percent": percent,
            "state": self.state.value,
        }

    def graded_pairs(self) -> List[Tuple[Question, Optional[Evaluation]]]:
        pairs: List[Tuple[Question, Optional[Evaluation]]] = []
        for qid in self.order:
            question = doctrine.get_question(qid)
            pairs.append((question, self.records[qid].evaluation))
        return pairs

    def score(self) -> DebriefScore:
        return score_debrief(self.graded_pairs())

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata.to_dict(),
            "order": list(self.order),
            "current_index": self.current_index,
            "records": {qid: r.to_dict() for qid, r in self.records.items()},
        }

    @classmethod
    def from_dict(
        cls, data: dict, evaluator: Optional[Evaluator] = None
    ) -> "DebriefSession":
        session = cls(
            session_id=data["id"],
            metadata=MissionMetadata.from_dict(data.get("metadata") or {}),
            evaluator=evaluator,
            question_ids=list(data.get("order") or []),
        )
        session.state = SessionState(data.get("state", SessionState.METADATA.value))
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.updated_at)
        session.current_index = int(data.get("current_index", 0))
        records = data.get("records") or {}
        for qid in session.order:
            if qid in records:
                session.records[qid] = QuestionRecord.from_dict(records[qid])
        return session
