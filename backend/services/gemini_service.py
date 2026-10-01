"""Google Gemini integration for TripMind AI.

Uses the REST API (generativelanguage.googleapis.com) so no extra SDK
dependency is required. This module is the ONLY place that talks to the
Gemini API; the rest of the app calls call_ai() from services/ai_service.

Keys are read lazily from the environment (config.GEMINI_API_KEY /
config.GEMINI_MODEL) so the app boots cleanly without a key and falls back
to deterministic local logic.
"""
import json

import requests

try:
    from config import GEMINI_API_KEY, GEMINI_MODEL
except Exception:  # pragma: no cover - defensive import for odd cwd launches
    import os
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


_BASE = "https://generativelanguage.googleapis.com/v1beta"


def is_gemini_configured():
    return bool(GEMINI_API_KEY)


def reset_session():
    """No persistent session needed for stateless REST calls."""
    return True


def make_full_prompt(system_prompt, prompt):
    """Build the Gemini contents payload (system vs user distinction)."""
    contents = []
    if system_prompt:
        contents.append({"role": "user", "parts": [{"text": system_prompt}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    return contents


def generate_text(prompt, system_prompt="", max_tokens=1024, temperature=0.7):
    """One-shot text generation. Returns raw model text or raises on failure.

    The free tier frequently returns transient HTTP 503 (high demand), so the
    call is retried a few times with short backoff before giving up.
    """
    import time
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    url = "%s/models/%s:generateContent?key=%s" % (_BASE, GEMINI_MODEL, GEMINI_API_KEY)
    payload = {
        "contents": make_full_prompt(system_prompt, prompt),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json" if system_prompt and "JSON" in system_prompt.upper() else None,
        },
    }
    if payload["generationConfig"]["responseMimeType"] is None:
        del payload["generationConfig"]["responseMimeType"]
    last = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if resp.status_code == 200:
                data = resp.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError("Unexpected Gemini response: %s" % json.dumps(data)[:500])
            if resp.status_code not in (429, 500, 503):
                raise RuntimeError("Gemini API error %s: %s" % (resp.status_code, resp.text[:500]))
            last = "Gemini API transient %s: %s" % (resp.status_code, resp.text[:200])
        except requests.exceptions.RequestException as e:
            last = "Gemini network error: %s" % e
        if attempt < 3:
            time.sleep(3 * attempt)
    raise RuntimeError(last or "Gemini request failed")


def generate_json(prompt, system_prompt):
    """Generate a JSON object. Strips markdown fences defensively."""
    text = generate_text(prompt, system_prompt, max_tokens=2048, temperature=0.4)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)