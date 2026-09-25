"""Unified AI service with env-gated provider chain.

Priority:
1. OLLAMA_API_KEY → Ollama cloud (ollama.com)   primary, fast (cloud models)
2. GEMINI_API_KEY → Google Gemini      (free tier, forces JSON output)
3. CEREBRAS_API_KEY → Cerebras         (OpenAI-compatible, fast)
4. OPENROUTER_API_KEY → OpenRouter     (free-tier fallback, often slow/429)
5. None → AI unavailable (returns None / signals unavailability)

No code outside this module should import gemini/ollama/cerebras/openrouter/groq
directly. The rest of the app calls `call_ai(prompt, system_prompt)` and
`is_ai_available()` only.
"""
import os

# Lazy-loaded settings (read once at import, overridable in-process for tests).
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
# Models tried when the configured one 429s/503s or returns nothing.
OLLAMA_FALLBACK_MODELS = [
    "deepseek-v4-flash:0731",
    "glm-5.3",
]

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
CEREBRAS_BASE_URL = os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1")
# Models tried when the configured one 429s/503s or returns nothing.
CEREBRAS_MODELS_TO_TRY = [
    CEREBRAS_MODEL,
    "llama-3.3-70b",
]

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
    return (bool(OLLAMA_API_KEY) or bool(GEMINI_KEY) or bool(CEREBRAS_API_KEY)
            or bool(OPENROUTER_API_KEY))


def call_ai(prompt, system_prompt="", max_tokens=1024, temperature=0.7):
    """Route to the first available backend; return raw string content.

    Every provider failure is logged with its reason (never silently swallowed)
    so an empty plan can always be traced to its LLM cause. Returns None when
    no backend is available so callers can fall back to deterministic logic.
    """
    import time as _time
    started = _time.time()
    if OLLAMA_API_KEY:
        try:
            out = _call_ollama(prompt, system_prompt, max_tokens=max_tokens,
                               temperature=temperature)
            print("[TripMind AI] LLM ok · ollama/%s · %.1fs · %d chars"
                  % (OLLAMA_MODEL, _time.time() - started, len(out or "")))
            return out
        except Exception as e:
            print("[TripMind AI] LLM ollama failed after %.1fs: %s"
                  % (_time.time() - started, e))
    if GEMINI_KEY:
        try:
            from services.gemini_service import generate_text
            out = generate_text(prompt, system_prompt, max_tokens=max_tokens,
                                temperature=temperature)
            print("[TripMind AI] LLM ok · gemini/%s · %.1fs · %d chars"
                  % (GEMINI_MODEL, _time.time() - started, len(out or "")))
            return out
        except Exception as e:
            print("[TripMind AI] LLM gemini failed after %.1fs: %s"
                  % (_time.time() - started, e))
    if CEREBRAS_API_KEY:
        try:
            out = _call_openai_compatible(
                CEREBRAS_BASE_URL, CEREBRAS_API_KEY, CEREBRAS_MODELS_TO_TRY,
                prompt, system_prompt, max_tokens=max_tokens, temperature=temperature)
            print("[TripMind AI] LLM ok · cerebras/%s · %.1fs · %d chars"
                  % (CEREBRAS_MODEL, _time.time() - started, len(out or "")))
            return out
        except Exception as e:
            print("[TripMind AI] LLM cerebras failed after %.1fs: %s"
                  % (_time.time() - started, e))
    if OPENROUTER_API_KEY:
        try:
            out = _call_openrouter(prompt, system_prompt,
                                   max_tokens=max_tokens, temperature=temperature)
            print("[TripMind AI] LLM ok · openrouter · %.1fs · %d chars"
                  % (_time.time() - started, len(out or "")))
            return out
        except Exception as e:
            print("[TripMind AI] LLM openrouter failed after %.1fs: %s"
                  % (_time.time() - started, e))
    print("[TripMind AI] LLM unavailable: every configured provider failed "
          "(or no API key is set) after %.1fs." % (_time.time() - started))
    return None  # deterministic callers use None to trigger local fallback


# ---------------------------------------------------------------------------
# Ollama cloud (ollama.com) — primary backend.  Ollama's REST API with a
# Bearer API key; when a "JSON" system prompt is passed it sets format=json
# so callers receive parseable JSON directly (same guarantee Gemini gives
# via responseMimeType).
# ---------------------------------------------------------------------------

def _ollama_models_to_try():
    """Ordered model list: configured primary first, then fallbacks."""
    chain = [OLLAMA_MODEL]
    for m in OLLAMA_FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def _call_ollama(prompt, system_prompt="", max_tokens=1024, temperature=0.7,
                 attempts=2, timeout=90):
    """Call Ollama cloud /api/chat with the Bearer API key, retrying each
    model a couple of times and walking the model list before giving up."""
    import time
    import requests

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    body = {
        "stream": False,
        "messages": messages,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    if system_prompt and "JSON" in system_prompt.upper():
        body["format"] = "json"

    last = None
    for n, model in enumerate(_ollama_models_to_try()):
        limit = attempts if n == 0 else 1
        for attempt in range(max(1, limit)):
            try:
                resp = requests.post(
                    "%s/api/chat" % OLLAMA_BASE_URL.rstrip("/"),
                    headers={"Authorization": "Bearer %s" % OLLAMA_API_KEY,
                             "Content-Type": "application/json"},
                    json=dict(body, model=model),
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = ((data.get("message") or {}).get("content") or "").strip()
                if content:
                    return content
                last = "%s -> empty reply" % model
            except Exception as e:
                last = "%s -> %s: %s" % (model, type(e).__name__, e)
            if attempt + 1 < max(1, limit):
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "Ollama request failed")


# ---------------------------------------------------------------------------
# OpenAI-compatible backends  (Cerebras / OpenRouter /v1/chat/completions)
# ---------------------------------------------------------------------------

def _call_openai_compatible(base_url, api_key, models, prompt, system_prompt="",
                            max_tokens=1024, temperature=0.7, attempts=2,
                            timeout=90):
    """POST to any OpenAI-compatible /chat/completions endpoint, retrying each
    model a couple of times and walking the model list before giving up."""
    import time
    import requests

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last = None
    for n, model in enumerate(models):
        limit = attempts if n == 0 else 1
        for attempt in range(max(1, limit)):
            try:
                resp = requests.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json={"model": model, "messages": messages,
                          "temperature": temperature, "max_tokens": max_tokens},
                    timeout=timeout,
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
    raise RuntimeError(last or "OpenAI-compatible request failed")

def _models_to_try():
    """Ordered list of models: configured primary first, then fallbacks."""
    chain = [OPENROUTER_MODEL]
    for m in OPENROUTER_FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def _call_openrouter(prompt, system_prompt="", max_tokens=1024, temperature=0.7,
                     attempts=2):
    """Call OpenRouter (free-tier fallback). Delegates to the shared
    OpenAI-compatible helper with the OpenRouter model chain."""
    return _call_openai_compatible(
        OPENROUTER_BASE_URL, OPENROUTER_API_KEY, _models_to_try(),
        prompt, system_prompt, max_tokens=max_tokens, temperature=temperature,
        attempts=attempts, timeout=75)