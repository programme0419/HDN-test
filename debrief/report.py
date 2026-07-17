"""Render a completed (or in-progress) debrief as a structured Markdown report.

The report is organised as a standard After-Action Review: mission
identification, an overall quality picture, the doctrinal questions and answers
grouped by phase, and consolidated sustain / improve / recommended-action
sections drawn from the operator's answers.
"""

from __future__ import annotations

from typing import List, Optional

from . import doctrine
from .assessment import Evaluation
from .models import Phase
from .session import DebriefSession, QuestionRecord

_STATUS_ICON = {
    "Complete": "\u2714",            # check mark
    "Needs more detail": "\u26a0",  # warning sign
    "Not addressed": "\u2717",      # cross mark
}


def _fmt_datetime(ts: float) -> str:
    import datetime

    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def _evaluation_line(evaluation: Optional[Evaluation]) -> str:
    if not evaluation:
        return "_Not answered._"
    bits = [f"quality {evaluation.score}/100 ({evaluation.level.value})"]
    if evaluation.missing:
        bits.append("missing: " + ", ".join(e.value for e in evaluation.missing))
    return "_Assessment: " + "; ".join(bits) + "._"


def _metadata_section(session: DebriefSession) -> List[str]:
    m = session.metadata
    lines = ["## Mission", "", "| Field | Value |", "| --- | --- |"]
    lines.append(f"| Mission | {m.mission_name or '-'} |")
    lines.append(f"| Date/Time | {m.date_time or '-'} |")
    lines.append(f"| Unit | {m.unit or '-'} |")
    lines.append(f"| Location | {m.location or '-'} |")
    lines.append(f"| Mission type | {m.mission_type or '-'} |")
    lines.append(f"| Participants | {', '.join(m.participants) if m.participants else '-'} |")
    lines.append("")
    return lines


def _score_section(session: DebriefSession) -> List[str]:
    score = session.score()
    lines = [
        "## Quality Assessment",
        "",
        f"**Overall quality: {score.overall}/100**  "
        f"({score.answered} of {score.total} questions answered)",
        "",
        "| Section | Status | Score |",
        "| --- | --- | --- |",
    ]
    for section in score.sections:
        icon = _STATUS_ICON.get(section.status, "")
        lines.append(
            f"| {section.phase} | {icon} {section.status} | {section.score}/100 |"
        )
    lines.append("")
    return lines


def _answers_section(session: DebriefSession) -> List[str]:
    lines: List[str] = ["## Debrief"]
    for phase in doctrine.phases():
        questions = doctrine.questions_for(phase)
        phase_qids = [q.id for q in questions if q.id in session.records]
        if not phase_qids:
            continue
        lines.append("")
        lines.append(f"### {phase.value}")
        for q in questions:
            record: Optional[QuestionRecord] = session.records.get(q.id)
            lines.append("")
            lines.append(f"**Q: {q.prompt}**")
            if not record or not record.combined_answer:
                lines.append("")
                lines.append("_Not answered._")
                continue
            lines.append("")
            lines.append(f"A: {record.combined_answer}")
            if record.asked_follow_ups:
                lines.append("")
                lines.append("Follow-ups asked:")
                for fu in record.asked_follow_ups:
                    lines.append(f"- {fu.get('prompt', '')}")
            lines.append("")
            lines.append(_evaluation_line(record.evaluation))
            if record.evaluation and record.evaluation.coaching:
                lines.append("")
                lines.append(f"> {record.evaluation.coaching}")
    lines.append("")
    return lines


def _answer_for(session: DebriefSession, question_id: str) -> str:
    record = session.records.get(question_id)
    return record.combined_answer if record else ""


def _consolidated_section(session: DebriefSession) -> List[str]:
    sustain = _answer_for(session, "as-sustain")
    improve = _answer_for(session, "as-improve")
    actions = _answer_for(session, "ll-actions")
    lines = ["## Sustain / Improve / Actions", ""]
    lines.append("**Sustain (what worked):**")
    lines.append("")
    lines.append(sustain or "_Not captured._")
    lines.append("")
    lines.append("**Improve (what needs work):**")
    lines.append("")
    lines.append(improve or "_Not captured._")
    lines.append("")
    lines.append("**Recommended actions:**")
    lines.append("")
    lines.append(actions or "_Not captured._")
    lines.append("")
    return lines


def render_markdown(session: DebriefSession) -> str:
    """Produce the full Markdown debrief report for a session."""
    m = session.metadata
    title = m.mission_name.strip() or "Untitled Mission"
    lines = [
        f"# After-Action Debrief \u2014 {title}",
        "",
        f"_Generated {_fmt_datetime(session.updated_at)} \u00b7 "
        f"session {session.id[:8]} \u00b7 "
        f"assessment: {'LLM-assisted' if session.llm_active else 'rule-based (offline)'}_",
        "",
    ]
    lines += _metadata_section(session)
    lines += _score_section(session)
    lines += _consolidated_section(session)
    lines += _answers_section(session)
    return "\n".join(lines).rstrip() + "\n"
