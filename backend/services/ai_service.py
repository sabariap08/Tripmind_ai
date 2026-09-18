"""Unified AI service with env-gated provider chain.

Priority:
1. GEMINI_API_KEY → Google Gemini  (primary, replaces the legacy Groq plan)
2. OPENROUTER_API_KEY → OpenRouter (OpenAI-compatible API, optional secondary)
3. Neither → deterministic fallback (returns None / signals unavailability)

No code outside this module should import gemini/openrouter/groq directly.
The rest of the app calls `call_ai(prompt, system_prompt)` and
`is_ai_available()` only.
"""
import os

# Lazy-loaded settings (read once at import, overridable in-process for tests).
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Fallback models tried when the configured one 429s/503s or returns nothing.
# Free-tier endpoints are often overloaded, so callers keep working even when
# the primary model is temporarily unavailable.
OPENROUTER_FALLBACK_MODELS = [
    "poolside/laguna-xs-2.1:free",
    "nex-agi/nex-n2.5-pro:free",
    "deepseek/deepseek-v4-flash-0731:free",
]


def is_ai_available():
    """True when at least one real LLM backend is configured."""
    return bool(GEMINI_KEY) or bool(OPENROUTER_API_KEY)


def call_ai(prompt, system_prompt="", max_tokens=1024, temperature=0.7):
    """Route to the first available backend; return raw string content.

    Returns None when no backend is available so callers can fall back to
    deterministic logic.
    """
    if GEMINI_KEY:
        try:
            from services.gemini_service import generate_text
            return generate_text(prompt, system_prompt, max_tokens=max_tokens,
                                 temperature=temperature)
        except Exception:
            pass  # fall through to OpenRouter
    if OPENROUTER_API_KEY:
        try:
            return _call_openrouter(prompt, system_prompt,
                                    max_tokens=max_tokens, temperature=temperature)
        except Exception:
            pass
    return None  # deterministic callers use None to trigger local fallback


# ---------------------------------------------------------------------------
# OpenRouter  (OpenAI-compatible /v1/chat/completions)
# ---------------------------------------------------------------------------

def _models_to_try():
    """Ordered list of models: configured primary first, then fallbacks."""
    chain = [OPENROUTER_MODEL]
    for m in OPENROUTER_FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def _call_openrouter(prompt, system_prompt="", max_tokens=1024, temperature=0.7,
                     attempts=2):
    """Call OpenRouter using the `requests` library (no extra dependency).

    Free-tier endpoints are often overloaded (HTTP 429/503, empty replies or
    long stalls), so each model is retried a couple of times and if it still
    fails the next fallback model on the chain is tried. Lower timeouts so the
    chain fails over fast instead of waiting minutes on a stalled provider.
    Raise a descriptive RuntimeError only when every model failed.
    """
    import time
    import requests  # guaranteed available in this project's venv

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last = None
    for n, model in enumerate(_models_to_try()):
        # Primary gets 2 attempts, quick fallbacks 1 attempt each.
        limit = attempts if n == 0 else 1
        for attempt in range(max(1, limit)):
            try:
                resp = requests.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://tripmind.ai",
                        "X-Title": "TripMind AI",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=75,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                if content:
                    return content
                last = "%s -> empty reply" % model
            except Exception as e:
                last = "%s -> %s: %s" % (model, type(e).__name__, e)
            if attempt + 1 < max(1, limit):
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "OpenRouter request failed")