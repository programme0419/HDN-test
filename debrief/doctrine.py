"""The doctrinal question bank for the debrief.

The structure follows the After-Action Review (AAR) model described in US Army
TC 25-20 / ATP 3-21.x: establish what was planned, what actually happened, why
it happened, and what to sustain and improve. Questions are grouped into
functional phases so a debrief walks the mission from planning through
execution to assessment.

Doctrine references are indicative pointers to the framework a question draws
from, not verbatim citations.
"""

from __future__ import annotations

from typing import List

from .models import Expectation as E
from .models import Phase, Question

QUESTION_BANK: List[Question] = [
    # ------------------------------------------------------------------ #
    # Mission Overview
    # ------------------------------------------------------------------ #
    Question(
        id="ov-mission",
        phase=Phase.OVERVIEW,
        prompt="State the mission: who, what, when, where, and why (the task and purpose).",
        intent="Anchor the debrief to the actual mission statement so every "
        "later observation can be judged against the task and purpose.",
        doctrine_ref="AAR: what was supposed to happen; FM 6-0 mission statement",
        expects=(E.TIME, E.LOCATION, E.ACTION),
        min_words=12,
        follow_ups={
            E.TIME: "When was the mission executed? Give the date and H-hour or timeframe.",
            E.LOCATION: "Where did this take place? Provide the area of operations or grid.",
            E.ACTION: "What was the specific task the element was directed to accomplish?",
        },
    ),
    Question(
        id="ov-intent",
        phase=Phase.OVERVIEW,
        prompt="What was the commander's intent and the definition of success for this mission?",
        intent="Success is measured against intent and end state, not against "
        "whether the plan was followed to the letter.",
        doctrine_ref="FM 6-0: commander's intent and end state",
        expects=(E.OUTCOME,),
        min_words=10,
        follow_ups={
            E.OUTCOME: "What did the desired end state look like? How would you know the mission succeeded?",
        },
    ),
    Question(
        id="ov-result",
        phase=Phase.OVERVIEW,
        prompt="Was the mission accomplished? Assess the outcome against the intent.",
        intent="Force an explicit, up-front judgement of mission success before "
        "detail is examined.",
        doctrine_ref="AAR: what actually happened vs. intent",
        expects=(E.OUTCOME, E.COMPARISON),
        min_words=10,
        follow_ups={
            E.COMPARISON: "How did the outcome compare to the intended end state \u2014 fully, partially, or not met?",
        },
    ),

    # ------------------------------------------------------------------ #
    # Planning & Preparation
    # ------------------------------------------------------------------ #
    Question(
        id="pl-plan",
        phase=Phase.PLANNING,
        prompt="Summarise the scheme of manoeuvre as planned, including key phases and timings.",
        intent="Capture the plan of record so deviations during execution can "
        "be identified precisely.",
        doctrine_ref="AAR: what was planned; troop-leading procedures",
        expects=(E.ACTION, E.TIME),
        min_words=12,
        follow_ups={
            E.TIME: "What were the planned timings or phase triggers?",
            E.ACTION: "Walk through the planned phases of the operation in order.",
        },
    ),
    Question(
        id="pl-risk",
        phase=Phase.PLANNING,
        prompt="What risks and contingencies were identified in planning, and how were they mitigated?",
        intent="Test whether risk management was deliberate and whether the "
        "contingencies matched what actually occurred.",
        doctrine_ref="Composite risk management; branches and sequels",
        expects=(E.ACTION, E.OUTCOME),
        required=False,
        min_words=10,
    ),
    Question(
        id="pl-rehearsal",
        phase=Phase.PLANNING,
        prompt="What rehearsals or pre-combat checks and inspections were conducted?",
        intent="Preparation quality is a leading indicator of execution "
        "quality; capture what was and was not rehearsed.",
        doctrine_ref="Pre-combat checks/inspections (PCC/PCI); rehearsals",
        expects=(E.ACTION,),
        required=False,
        min_words=8,
    ),

    # ------------------------------------------------------------------ #
    # Execution & Sequence of Events
    # ------------------------------------------------------------------ #
    Question(
        id="ex-timeline",
        phase=Phase.EXECUTION,
        prompt="Give the sequence of significant events from SP/infil to RTB/exfil, with times.",
        intent="A time-ordered narrative of observable facts is the spine of "
        "the AAR and prevents opinion from displacing fact.",
        doctrine_ref="AAR: chronological reconstruction of what happened",
        expects=(E.TIME, E.ACTION),
        min_words=20,
        follow_ups={
            E.TIME: "Attach approximate times to those events so the timeline can be reconstructed.",
            E.ACTION: "List the significant events in the order they occurred.",
        },
    ),
    Question(
        id="ex-deviation",
        phase=Phase.EXECUTION,
        prompt="Where did execution deviate from the plan, and what triggered each deviation?",
        intent="Deviations are where most lessons live. Tie each deviation to "
        "its cause.",
        doctrine_ref="AAR: what happened vs. what was planned; why",
        expects=(E.COMPARISON, E.CAUSAL),
        min_words=12,
        follow_ups={
            E.CAUSAL: "What specifically caused that deviation from the plan?",
            E.COMPARISON: "How did what happened differ from what was planned?",
        },
    ),
    Question(
        id="ex-decision",
        phase=Phase.EXECUTION,
        prompt="What key decisions were made during execution, by whom, and on what information?",
        intent="Decision quality depends on the information available at the "
        "time; capture both to avoid hindsight bias.",
        doctrine_ref="Decision-making under uncertainty; C2",
        expects=(E.ACTION, E.CAUSAL),
        min_words=12,
        follow_ups={
            E.CAUSAL: "What information or trigger drove that decision at the time?",
        },
    ),

    # ------------------------------------------------------------------ #
    # Enemy & Threat
    # ------------------------------------------------------------------ #
    Question(
        id="en-contact",
        phase=Phase.ENEMY,
        prompt="Describe enemy contact: size, activity, location, unit, time, and equipment (SALUTE).",
        intent="A disciplined SALUTE report turns 'we got shot at' into "
        "usable intelligence.",
        doctrine_ref="SALUTE report; enemy situation",
        expects=(E.TIME, E.LOCATION, E.QUANTITY),
        required=False,
        min_words=10,
        follow_ups={
            E.QUANTITY: "How many enemy were observed, and what were they equipped with?",
            E.LOCATION: "Where was the enemy located or last seen? Give a grid or bearing/distance.",
            E.TIME: "When did the contact occur, and for how long?",
        },
    ),
    Question(
        id="en-response",
        phase=Phase.ENEMY,
        prompt="How did the enemy react to friendly actions, and did that match the assessed threat?",
        intent="Comparing expected to actual enemy behaviour validates or "
        "corrects the threat picture for next time.",
        doctrine_ref="Enemy most likely / most dangerous course of action",
        expects=(E.COMPARISON, E.OUTCOME),
        required=False,
        min_words=10,
    ),

    # ------------------------------------------------------------------ #
    # Friendly Forces & Actions
    # ------------------------------------------------------------------ #
    Question(
        id="fr-actions",
        phase=Phase.FRIENDLY,
        prompt="What actions did friendly elements take at each significant event, and to what effect?",
        intent="Link friendly action to observable effect so cause and result "
        "are both recorded.",
        doctrine_ref="AAR: friendly actions and their effects",
        expects=(E.ACTION, E.OUTCOME),
        min_words=12,
        follow_ups={
            E.OUTCOME: "What was the effect or result of that action?",
            E.ACTION: "What did the element physically do at that point?",
        },
    ),
    Question(
        id="fr-coordination",
        phase=Phase.FRIENDLY,
        prompt="How well did elements and adjacent/supporting units coordinate and maintain SA?",
        intent="Most friendly-fire and timing failures trace back to "
        "coordination and shared situational awareness.",
        doctrine_ref="Actions on the objective; adjacent unit coordination",
        expects=(E.ASSESSMENT,),
        required=False,
        min_words=10,
    ),

    # ------------------------------------------------------------------ #
    # Fires & Effects
    # ------------------------------------------------------------------ #
    Question(
        id="fi-fires",
        phase=Phase.FIRES,
        prompt="What fires or supporting effects were employed, when, and were they timely and accurate?",
        intent="Assess responsiveness and accuracy of fires against the "
        "scheme of fires.",
        doctrine_ref="Scheme of fires; call for fire; effects assessment",
        expects=(E.TIME, E.OUTCOME),
        required=False,
        min_words=10,
        follow_ups={
            E.OUTCOME: "What effect did those fires achieve on target?",
            E.TIME: "How responsive were the fires \u2014 what was the time from request to effect?",
        },
    ),

    # ------------------------------------------------------------------ #
    # Communications & C2
    # ------------------------------------------------------------------ #
    Question(
        id="co-comms",
        prompt="How did communications perform across the mission (PACE plan, dead spots, failures)?",
        phase=Phase.COMMS,
        intent="Comms failures are common and consequential; capture where "
        "and why they occurred, not just that they did.",
        doctrine_ref="PACE plan; signal operating instructions",
        expects=(E.CAUSAL, E.LOCATION),
        min_words=10,
        follow_ups={
            E.CAUSAL: "What caused the communications problem \u2014 terrain, equipment, procedure, or plan?",
            E.LOCATION: "Where did the comms degradation occur?",
        },
    ),

    # ------------------------------------------------------------------ #
    # Casualties & Sustainment
    # ------------------------------------------------------------------ #
    Question(
        id="su-casualties",
        phase=Phase.SUSTAINMENT,
        prompt="Were there any casualties (friendly, enemy, or civilian)? Describe CASEVAC/MEDEVAC handling.",
        intent="Casualty handling and evacuation timelines are life-critical "
        "and frequently rehearsed poorly.",
        doctrine_ref="9-line MEDEVAC; casualty collection point procedures",
        expects=(E.QUANTITY, E.TIME),
        required=False,
        min_words=8,
        follow_ups={
            E.TIME: "What was the timeline from point of injury to evacuation?",
            E.QUANTITY: "How many casualties were there, and of what category?",
        },
    ),
    Question(
        id="su-logistics",
        phase=Phase.SUSTAINMENT,
        prompt="How did sustainment hold up: ammunition, water, batteries, fuel, and resupply?",
        intent="Consumption rates and resupply timing feed directly into "
        "planning factors for the next mission.",
        doctrine_ref="Classes of supply; logistics estimate",
        expects=(E.QUANTITY,),
        required=False,
        min_words=8,
    ),

    # ------------------------------------------------------------------ #
    # Assessment (Sustain / Improve)
    # ------------------------------------------------------------------ #
    Question(
        id="as-sustain",
        phase=Phase.ASSESSMENT,
        prompt="What went well and should be sustained? Be specific about why it worked.",
        intent="Sustains must be reinforced deliberately or they decay; tie "
        "each to the reason it succeeded.",
        doctrine_ref="AAR: sustain items",
        expects=(E.ASSESSMENT, E.CAUSAL),
        min_words=10,
        follow_ups={
            E.CAUSAL: "Why did that work \u2014 what specifically made it effective?",
        },
    ),
    Question(
        id="as-improve",
        phase=Phase.ASSESSMENT,
        prompt="What did not go well and needs to improve? Focus on systems and actions, not individuals.",
        intent="Improves must be observable and impersonal so they can be "
        "fixed through training or procedure.",
        doctrine_ref="AAR: improve items; no-fault learning environment",
        expects=(E.ASSESSMENT, E.CAUSAL),
        min_words=10,
        follow_ups={
            E.CAUSAL: "What was the root cause of that shortfall?",
        },
    ),

    # ------------------------------------------------------------------ #
    # Lessons Learned & Follow-up
    # ------------------------------------------------------------------ #
    Question(
        id="ll-actions",
        phase=Phase.LESSONS,
        prompt="What specific corrective actions are recommended, and who owns each one?",
        intent="A lesson is only learned when it becomes an assigned, "
        "trackable action with an owner.",
        doctrine_ref="AAR: turning observations into lessons learned",
        expects=(E.RECOMMENDATION, E.ACTION),
        min_words=10,
        follow_ups={
            E.RECOMMENDATION: "State the corrective action as a concrete recommendation.",
            E.ACTION: "Who is responsible for actioning this, and by when?",
        },
    ),
]


def phases() -> List[Phase]:
    """Return the doctrinal phases in debrief order."""
    seen: List[Phase] = []
    for question in QUESTION_BANK:
        if question.phase not in seen:
            seen.append(question.phase)
    return seen


def questions_for(phase: Phase) -> List[Question]:
    """Return all questions belonging to a phase, in bank order."""
    return [q for q in QUESTION_BANK if q.phase == phase]


def get_question(question_id: str) -> Question:
    """Look up a question by id, raising KeyError if it does not exist."""
    for question in QUESTION_BANK:
        if question.id == question_id:
            return question
    raise KeyError(f"No question with id {question_id!r}")
