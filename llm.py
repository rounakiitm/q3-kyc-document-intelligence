"""Thin Gemini client with multi-key rotation on quota/transient errors."""
from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types

from config import API_KEYS, KEY_ROTATION_ROUNDS, MAX_OUTPUT_TOKENS, MODEL_NAME

# 429 -> quota exhausted on this key: rotate immediately.
# 5xx / transient -> rotate but give the key a short cooldown.
COOLDOWN_S = 2.0


class AllKeysExhaustedError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, keys: list[str] | None = None) -> None:
        self._keys = keys if keys is not None else list(API_KEYS)
        self._cooldown: dict[int, float] = {}
        self._cursor = 0
        self.calls_made = 0

    def clear_cooldowns(self) -> None:
        self._cooldown.clear()

    def generate(self, contents: list[Any], system: str, model: str = MODEL_NAME) -> str:
        """One generateContent call, rotating keys and backing off on 503s.

        429 = this key's quota is gone (rotate, don't retry on it).
        503 = the MODEL is under global load (any key hits it), so we back off
        and retry the whole pool with increasing waits.
        """
        backoffs = [10.0, 25.0, 45.0]  # seconds; ~80s worst-case wait
        last_err: Exception | None = None
        for attempt, wait in enumerate([0.0, *backoffs], start=1):
            if wait:
                time.sleep(wait)
            for _ in range(len(self._keys)):
                idx = self._cursor % len(self._keys)
                self._cursor += 1
                until = self._cooldown.get(idx, 0.0)
                if time.monotonic() < until:
                    continue
                try:
                    client = genai.Client(
                        api_key=self._keys[idx],
                        http_options=types.HttpOptions(timeout=180_000),  # 3 min cap
                    )
                    resp = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            temperature=0.0,  # deterministic extraction
                            max_output_tokens=MAX_OUTPUT_TOKENS,
                            response_mime_type="application/json",
                        ),
                    )
                    self.calls_made += 1
                    return resp.text or ""
                except Exception as exc:  # noqa: BLE001 - rotate on any failure
                    last_err = exc
                    msg = str(exc)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        self._cooldown[idx] = time.monotonic() + 3600.0
                    elif "403" in msg or "PERMISSION_DENIED" in msg:
                        # key/project banned: rotate, don't retry on it
                        self._cooldown[idx] = time.monotonic() + 3600.0
                    elif "503" in msg or "UNAVAILABLE" in msg:
                        self._cooldown[idx] = time.monotonic() + COOLDOWN_S
                    else:
                        raise
        raise AllKeysExhaustedError(
            f"All API keys exhausted after {KEY_ROTATION_ROUNDS} rounds: {last_err}"
        )
