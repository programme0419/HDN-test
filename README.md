# After-Action Debrief Assistant

An offline desktop tool that guides military operators through a structured
post-mission debrief. It asks doctrinally grounded questions, quality-checks
each response, and generates targeted follow-up questions to surface the detail
a useful After-Action Review (AAR) requires.

## Why this tool

A debrief is only as good as the questions asked and the discipline of the
answers captured. Under fatigue and time pressure, debriefs drift toward vague,
non-actionable statements ("it went fine", "comms were bad"). This tool applies
a consistent doctrinal structure and a response-quality gate so that every
debrief produces specific, observable, and actionable findings.

Design goals:

- **Offline first.** No cloud services, no network calls. Operational
  information never leaves the machine.
- **Doctrine driven.** Question sets follow the After-Action Review model
  (what was planned, what happened, why, what to sustain/improve).
- **Deterministic.** The quality checks and follow-up logic are transparent
  rules an operator can inspect and trust, not an opaque model.

## Status

Under active development. See commit history for the build progression.

## Project layout

```
debrief/        Core engine (doctrine, quality checks, follow-ups, session)
web/            Desktop UI (served locally)
tests/          Unit tests for the engine
app.py          Desktop launcher
```

## Running

Requires Python 3.9+. No third-party packages are required to run the core
tool.

```
python3 app.py
```
