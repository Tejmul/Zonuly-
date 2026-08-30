"""Thin Ollama client — chat, JSON-mode chat, and embeddings.

Every agent in the pipeline goes through here, so swapping the local model for a
bigger one (or a cloud API) is a config change, not a code change.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from jobhunter import CONFIG

log = logging.getLogger(__name__)

_LLM = CONFIG["llm"]
BASE_URL = _LLM["base_url"].rstrip("/")
MODEL = _LLM["model"]
EMBED_MODEL = _LLM["embed_model"]
OPTIONS = dict(_LLM.get("options") or {})
KEEP_ALIVE = _LLM.get("keep_alive", "30m")

# Local 4B on 8 GB RAM: a long JD + rubric can take a while on first load.
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT)
    return _client


class LLMUnavailable(RuntimeError):
    """Ollama isn't reachable or the model isn't pulled."""


def health() -> dict:
    """Return {ok, models, model_present, embed_present} — used by the API /health route."""
    try:
        r = client().get("/api/tags", timeout=5.0)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:  # noqa: BLE001 — health check must never raise
        return {"ok": False, "error": str(e), "models": [], "model_present": False, "embed_present": False}

    def present(want: str) -> bool:
        # ollama reports "qwen3:4b"; a bare "qwen3" in config should still match
        return any(n == want or n.split(":")[0] == want.split(":")[0] for n in names)

    return {
        "ok": True,
        "models": names,
        "model": MODEL,
        "embed_model": EMBED_MODEL,
        "model_present": present(MODEL),
        "embed_present": present(EMBED_MODEL),
    }


def chat(
    prompt: str,
    system: str | None = None,
    *,
    json_mode: bool = False,
    temperature: float | None = None,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    model: str | None = None,
    think: bool = False,
) -> str:
    """Single-turn chat. Returns the assistant text (thinking stripped).

    Qwen3 is a hybrid-reasoning model. Bulk pipeline work doesn't need the think
    pass and it costs 5-10x the tokens, so it's off by default — belt and braces,
    via both the API flag and the `/no_think` prompt switch the model itself honours.
    """
    messages: list[dict[str, str]] = []
    sys_text = system or ""
    if not think:
        # the switch belongs in the system turn — appended to the user turn the model
        # sometimes echoes it back as part of the answer
        sys_text = (sys_text + "\n/no_think").strip()
    if sys_text:
        messages.append({"role": "system", "content": sys_text})
    messages.append({"role": "user", "content": prompt})

    options = dict(OPTIONS)
    if temperature is not None:
        options["temperature"] = temperature
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if num_predict is not None:
        options["num_predict"] = num_predict

    payload: dict[str, Any] = {
        "model": model or MODEL,
        "messages": messages,
        "stream": False,
        "options": options,
        "think": think,
        # 8 GB is tight for a 4B chat model + an embedder; keeping both resident
        # avoids multi-minute reload stalls partway through a long scoring run
        "keep_alive": KEEP_ALIVE,
    }
    if json_mode:
        payload["format"] = "json"

    try:
        r = client().post("/api/chat", json=payload)
        r.raise_for_status()
    except httpx.ConnectError as e:
        raise LLMUnavailable(f"Ollama not reachable at {BASE_URL} — is `ollama serve` running?") from e
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        if e.response.status_code == 404:
            raise LLMUnavailable(f"Model '{model or MODEL}' not found — run `ollama pull {model or MODEL}`") from e
        raise LLMUnavailable(f"Ollama error {e.response.status_code}: {body}") from e

    content = r.json().get("message", {}).get("content", "")
    return _strip_think(content).strip()


def chat_json(
    prompt: str,
    system: str | None = None,
    *,
    default: Any = None,
    retries: int = 2,
    **kw: Any,
) -> Any:
    """Chat in JSON mode with parse-retry. Returns `default` if the model never produces valid JSON."""
    last_raw = ""
    for attempt in range(retries + 1):
        nudge = "" if attempt == 0 else "\n\nYour previous reply was not valid JSON. Reply with JSON only."
        raw = chat(prompt + nudge, system, json_mode=True, **kw)
        last_raw = raw
        parsed = _extract_json(raw)
        if parsed is not None:
            return parsed
        log.warning("LLM returned unparseable JSON (attempt %d/%d)", attempt + 1, retries + 1)
    log.error("Giving up on JSON parse; last raw output: %s", last_raw[:400])
    return default


def embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input, in order."""
    if not texts:
        return []
    try:
        r = client().post(
            "/api/embed",
            json={
                "model": model or EMBED_MODEL,
                "input": texts,
                "truncate": True,
                "keep_alive": KEEP_ALIVE,
            },
        )
        r.raise_for_status()
    except httpx.ConnectError as e:
        raise LLMUnavailable(f"Ollama not reachable at {BASE_URL} — is `ollama serve` running?") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise LLMUnavailable(
                f"Embedding model '{model or EMBED_MODEL}' not found — run `ollama pull {model or EMBED_MODEL}`"
            ) from e
        raise LLMUnavailable(f"Ollama embed error {e.response.status_code}: {e.response.text[:300]}") from e
    return r.json()["embeddings"]


def embed_one(text: str, **kw: Any) -> list[float]:
    vecs = embed([text], **kw)
    return vecs[0] if vecs else []


# ---------------------------------------------------------------- helpers

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # Ollama can emit the reasoning with only a closing tag (the opener is consumed
    # by the chat template) — everything before the last </think> is reasoning.
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    # an unclosed <think> means the model ran out of budget mid-reasoning
    if "<think>" in text:
        text = text.split("<think>")[0]
    return text


def _extract_json(raw: str) -> Any:
    """Parse JSON, tolerating markdown fences and leading/trailing prose."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # fall back to the first balanced {...} or [...] block
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(raw[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None
