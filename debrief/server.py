"""Local HTTP server for the debrief desktop tool (standard library only).

Serves the static ``web/`` frontend and a small JSON API that drives the
session engine. Active sessions are held in memory and can be persisted to (and
resumed from) the SQLite store.

Nothing here binds to anything but localhost by default; this is a
single-operator desktop tool, not a network service.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from .assessment import Evaluator
from .models import MISSION_TYPES, MissionMetadata
from .report import render_markdown
from .session import DebriefSession
from .store import DebriefStore

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class DebriefApp:
    """Holds shared state (sessions, evaluator, store) for the request handler."""

    def __init__(self, store: Optional[DebriefStore] = None) -> None:
        self.evaluator = Evaluator()
        self.store = store or DebriefStore()
        self.sessions: Dict[str, DebriefSession] = {}
        self._lock = threading.Lock()

    def get_session(self, session_id: str) -> Optional[DebriefSession]:
        with self._lock:
            session = self.sessions.get(session_id)
            if session:
                return session
        # Fall back to the persistent store (resume a saved debrief).
        session = self.store.load(session_id, evaluator=self.evaluator)
        if session:
            with self._lock:
                self.sessions[session.id] = session
        return session

    def add_session(self, session: DebriefSession) -> None:
        with self._lock:
            self.sessions[session.id] = session


def _step_payload(session: DebriefSession) -> dict:
    """The state the frontend needs to render the current step."""
    prompt = session.current_prompt()
    question = session.current_question()
    return {
        "session_id": session.id,
        "state": session.state.value,
        "progress": session.progress(),
        "question": (
            {
                "id": question.id,
                "phase": question.phase.value,
                "intent": question.intent,
                "doctrine_ref": question.doctrine_ref,
                "required": question.required,
            }
            if question
            else None
        ),
        "prompt": (
            {
                "text": prompt.prompt,
                "is_follow_up": prompt.is_follow_up,
                "reason": prompt.reason,
            }
            if prompt
            else None
        ),
    }


class DebriefHandler(BaseHTTPRequestHandler):
    app: DebriefApp = None  # type: ignore[assignment]

    # Quieten the default noisy logging.
    def log_message(self, *args) -> None:  # noqa: D401
        return

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _not_found(self) -> None:
        self._send_json({"error": "not found"}, status=404)

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path.startswith("/api/"):
            return self._route_api_get(path)
        # Any other path is treated as a static asset request.
        return self._serve_static(path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._route_api_post(path)
        return self._not_found()

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        parts = _api_parts(path)
        if len(parts) == 2 and parts[0] == "session":
            deleted = self.app.store.delete(parts[1])
            return self._send_json({"deleted": deleted})
        return self._not_found()

    def _serve_static(self, rel_path: str) -> None:
        # Prevent path traversal.
        safe = os.path.normpath(rel_path).lstrip("/\\")
        if safe.startswith(".."):
            return self._not_found()
        full = os.path.join(WEB_DIR, safe)
        if not os.path.isfile(full):
            return self._not_found()
        ext = os.path.splitext(full)[1].lower()
        ctype = _STATIC_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -------------------------- GET API -------------------------------- #
    def _route_api_get(self, path: str) -> None:
        parts = _api_parts(path)
        if parts == ["config"]:
            return self._send_json(
                {
                    "llm_active": self.app.evaluator.llm_active,
                    "model": self.app.evaluator.client.model,
                    "mission_types": list(MISSION_TYPES),
                }
            )
        if parts == ["sessions"]:
            return self._send_json({"sessions": self.app.store.list()})
        if len(parts) == 3 and parts[0] == "session":
            session_id, action = parts[1], parts[2]
            session = self.app.get_session(session_id)
            if not session:
                return self._not_found()
            if action == "current":
                return self._send_json(_step_payload(session))
            if action == "score":
                return self._send_json(session.score().to_dict())
            if action == "report":
                return self._send_text(
                    render_markdown(session), "text/markdown; charset=utf-8"
                )
        return self._not_found()

    # -------------------------- POST API ------------------------------- #
    def _route_api_post(self, path: str) -> None:
        parts = _api_parts(path)

        if parts == ["session"]:
            session = DebriefSession(evaluator=self.app.evaluator)
            self.app.add_session(session)
            return self._send_json(_step_payload(session), status=201)

        if len(parts) == 3 and parts[0] == "session":
            session_id, action = parts[1], parts[2]
            session = self.app.get_session(session_id)
            if not session:
                return self._not_found()

            if action == "metadata":
                body = self._read_json()
                errors = session.set_metadata(MissionMetadata.from_dict(body))
                if errors:
                    return self._send_json({"errors": errors}, status=400)
                self.app.store.save(session)
                return self._send_json(_step_payload(session))

            if action == "answer":
                body = self._read_json()
                evaluation = session.submit_answer(str(body.get("text", "")))
                self.app.store.save(session)
                payload = _step_payload(session)
                payload["evaluation"] = (
                    evaluation.to_dict() if evaluation else None
                )
                return self._send_json(payload)

            if action == "skip":
                session.skip_current()
                self.app.store.save(session)
                return self._send_json(_step_payload(session))

            if action == "save":
                self.app.store.save(session)
                return self._send_json({"saved": True})

        return self._not_found()


def _api_parts(path: str):
    """Split '/api/session/abc/answer' -> ['session', 'abc', 'answer']."""
    trimmed = path[len("/api/"):] if path.startswith("/api/") else path
    return [p for p in trimmed.split("/") if p]


def create_server(
    host: str = "127.0.0.1", port: int = 8765, store: Optional[DebriefStore] = None
) -> Tuple[ThreadingHTTPServer, DebriefApp]:
    """Build (but do not start) the threading HTTP server and its app state."""
    app = DebriefApp(store=store)

    handler = type("BoundDebriefHandler", (DebriefHandler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the server until interrupted (used for headless/CLI serving)."""
    httpd, _ = create_server(host, port)
    url = f"http://{host}:{port}/"
    print(f"Debrief tool serving on {url}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()
