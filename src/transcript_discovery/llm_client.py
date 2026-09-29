"""LLM client — single configuration and communication point.

All provider details (model name, base URL, API key env-var) live here.
``clipper.py`` calls :func:`chat_json` and never imports a provider SDK
directly, so swapping providers or models requires only environment-variable
changes (or edits to this file) — **not** changes to ``clipper.py``.

Supported providers (``CLIPPER_LLM_PROVIDER`` env-var):
    ``openai``    — OpenAI or any OpenAI-compatible endpoint (Azure,
                    Together, Fireworks, local Ollama …).
                    Override the base URL with ``OPENAI_BASE_URL``.
    ``anthropic`` — Anthropic Claude via the official ``anthropic`` SDK.
    ``google``    — Google Gemini via ``google-genai`` (``google.genai``).

Required environment variables (provider-dependent):
    CLIPPER_LLM_PROVIDER   one of openai / anthropic / google
                           (default: openai)
    CLIPPER_LLM_MODEL      model name override
                           (default: provider-specific, see _DEFAULTS below)
    OPENAI_API_KEY         required when provider == openai
    OPENAI_BASE_URL        optional base-URL override (OpenAI-compatible hosts)
    ANTHROPIC_API_KEY      required when provider == anthropic
    GEMINI_API_KEY         required when provider == google

Public API::

    from .llm_client import chat_json, active_config

    messages = [
        {"role": "system", "content": "You output JSON only."},
        {"role": "user",   "content": "..."},
    ]
    data = chat_json(messages)          # returns parsed dict / list
    print(active_config())              # {"provider": "openai", "model": "..."}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Load project .env (if present) before any os.environ access.
# override=False means variables already set in the shell always take
# precedence — secrets are never unexpectedly overwritten.
# python-dotenv is treated as optional so the module remains importable even
# in stripped environments where it is not installed.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(
        dotenv_path=Path(__file__).resolve().parents[2] / ".env",
        override=False,
    )
except ModuleNotFoundError:
    pass  # python-dotenv not installed; rely on env vars already in shell


# ---------------------------------------------------------------------------
# Provider defaults — change defaults here, not in clipper.py
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "model": "claude-3-5-haiku-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "google": {
        "model": "gemini-3.1-flash-lite",
        "api_key_env": "GEMINI_API_KEY",
    },
}

_DEFAULT_PROVIDER = "google"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.environ.get("CLIPPER_LLM_PROVIDER", _DEFAULT_PROVIDER).lower().strip()


def _model(provider: str) -> str:
    return os.environ.get("CLIPPER_LLM_MODEL", _DEFAULTS[provider]["model"])


def _api_key(provider: str) -> str:
    env_var = _DEFAULTS[provider]["api_key_env"]
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise EnvironmentError(
            f"Missing required environment variable {env_var!r} "
            f"for LLM provider {provider!r}."
        )
    return key


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that some models wrap around JSON."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # drop opening fence (```json or ```) and closing fence (```)
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        stripped = "\n".join(inner_lines)
    return stripped


# ---------------------------------------------------------------------------
# Provider-specific call implementations
# ---------------------------------------------------------------------------


def _call_openai(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        import openai  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Package 'openai' is required for provider 'openai'. "
            "Install: pip install openai"
        ) from exc

    base_url: str | None = os.environ.get("OPENAI_BASE_URL") or None
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        import anthropic  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Package 'anthropic' is required for provider 'anthropic'. "
            "Install: pip install anthropic"
        ) from exc

    system_prompt = ""
    user_messages: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_prompt = msg["content"]
        else:
            user_messages.append(msg)

    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=user_messages,
    )
    if system_prompt:
        kwargs["system"] = system_prompt

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(**kwargs)  # type: ignore[arg-type]
    return resp.content[0].text if resp.content else ""


def _call_google(
    messages: list[dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types as gtypes  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Package 'google-genai' is required for provider 'google'. "
            "Install: pip install google-genai"
        ) from exc

    # Separate system instruction from turn-by-turn messages.
    # GenerateContentConfig.system_instruction is the correct place for it in
    # the google-genai SDK; it must NOT appear in the contents list.
    system_instruction: str | None = None
    contents: list[gtypes.Content] = []
    for msg in messages:
        role = msg["role"]
        text = msg["content"]
        if role == "system":
            system_instruction = text
        else:
            # Google uses "model" where OpenAI uses "assistant"
            gemini_role = "model" if role == "assistant" else "user"
            contents.append(
                gtypes.Content(
                    role=gemini_role,
                    parts=[gtypes.Part(text=text)],
                )
            )

    config = gtypes.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        system_instruction=system_instruction,
    )

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    return resp.text or ""



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DISPATCH = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "google": _call_google,
}


def chat_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> Any:
    """Send *messages* to the configured LLM and return a parsed JSON value.

    Args:
        messages: OpenAI-style message list, e.g.::

            [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user",   "content": "..."},
            ]

        temperature: Sampling temperature (lower → more deterministic).
        max_tokens: Maximum tokens to generate in the response.

    Returns:
        Parsed Python object (``dict`` or ``list``) decoded from the
        LLM's JSON response.

    Raises:
        EnvironmentError: Required API-key env-var is unset.
        KeyError: ``CLIPPER_LLM_PROVIDER`` names an unknown provider.
        ModuleNotFoundError: The provider's SDK package is not installed.
        ValueError: The LLM response could not be parsed as JSON.
    """
    provider = _provider()
    if provider not in _DEFAULTS:
        raise KeyError(
            f"Unknown LLM provider {provider!r}. "
            f"Valid values: {sorted(_DEFAULTS)}"
        )

    model = _model(provider)
    api_key = _api_key(provider)

    raw: str = _DISPATCH[provider](messages, model, api_key, temperature, max_tokens)

    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM ({provider}/{model}) returned non-JSON content.\n"
            f"Raw response:\n{raw}"
        ) from exc


def active_config() -> dict[str, str]:
    """Return the currently-active provider and model (for logging/debugging)."""
    p = _provider()
    return {"provider": p, "model": _model(p)}
