"""Optional LLM integration for the debrief tool.

The tool is fully functional offline using the deterministic rule-based engine.
When an OpenAI-compatible API is configured through the environment, this module
provides a thin client that lets the engine ask a model to judge doctrinal
completeness and propose sharper follow-up questions.

Only the Python standard library is used (``urllib``) so the tool has no
third-party runtime dependency. If no API key is present, or a request fails,
callers should fall back to the rule-based results \u2014 see
:mod:`debrief.assessment`.

Configuration (all via environment variables):

    OPENAI_API_KEY    the API key. When absent, the client is "unavailable"
                      and the tool runs entirely offline.
    OPENAI_BASE_URL   API base URL. Defaults to the OpenAI public endpoint.
                      Point this at any OpenAI-compatible gateway if desired.
    OPENAI_MODEL      chat model name. Defaults to ``gpt-4o-mini``.
    OPENAI_TIMEOUT    per-request timeout in seconds (default 30).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

# A sensible, widely-available default. It is intentionally a small, fast model
# because the debrief makes several short calls per session. Override with the
# OPENAI_MODEL environment variable. Documented in README.md / MODEL_NOTES.md.
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 30.0


class LLMError(RuntimeError):
    """Raised when a configured LLM request cannot be completed."""


@dataclass(frozen=True)
class LLMConfig:
    """Resolved LLM configuration."""

    api_key: Optional[str]
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "LLMConfig":
        source = os.environ if env is None else env
        timeout_raw = source.get("OPENAI_TIMEOUT", "").strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT
        except ValueError:
            timeout = DEFAULT_TIMEOUT
        return cls(
            api_key=(source.get("OPENAI_API_KEY") or "").strip() or None,
            base_url=(source.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
            model=(source.get("OPENAI_MODEL") or DEFAULT_MODEL).strip(),
            timeout=timeout,
        )

    @property
    def available(self) -> bool:
        """True when enough is configured to attempt a request."""
        return bool(self.api_key)


class LLMClient:
    """Minimal OpenAI-compatible Chat Completions client (stdlib only)."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig.from_env()

    @property
    def available(self) -> bool:
        return self.config.available

    @property
    def model(self) -> str:
        return self.config.model

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 700,
        force_json: bool = False,
    ) -> str:
        """Send a chat request and return the assistant's text content.

        Raises :class:`LLMError` on any configuration, transport, or protocol
        problem so callers can fall back deterministically.
        """
        if not self.available:
            raise LLMError("No API key configured (OPENAI_API_KEY is unset).")

        payload: Dict[str, object] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.config.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise LLMError(f"HTTP {exc.code} from LLM API: {detail}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network
            raise LLMError(f"Could not reach LLM API: {exc.reason}") from exc
        except TimeoutError as exc:  # pragma: no cover - network
            raise LLMError("LLM API request timed out.") from exc

        try:
            parsed = json.loads(body)
            return parsed["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from LLM API.") from exc

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> dict:
        """Request a JSON object response and parse it.

        Tolerates models that wrap JSON in prose or code fences by extracting
        the outermost JSON object. Raises :class:`LLMError` if no object can be
        recovered.
        """
        content = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            force_json=True,
        )
        return _extract_json_object(content)


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a single JSON object from model output."""
    text = (text or "").strip()
    if not text:
        raise LLMError("LLM returned an empty response.")
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fall back to slicing between the first '{' and the last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    raise LLMError("Could not parse a JSON object from the LLM response.")
