"""The ONLY place OpenAI is called. Enforces budget, caches, logs usage.

- Never logs or returns the API key.
- Caches identical requests (model+messages+params) to avoid repeat paid calls.
- Records every call in the budget ledger.
- On failure keeps the error and allows retry; never fabricates a result.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any

from app import config
from app.llm import budget

_CACHE_LOCK = threading.Lock()
_CACHE_DB = config.DATA_DIR / "llm_cache.db"


def _cache_conn() -> sqlite3.Connection:
    c = sqlite3.connect(_CACHE_DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT, ts REAL)")
    return c


def _key(model: str, messages: list[dict], params: dict) -> str:
    blob = json.dumps({"m": model, "msgs": messages, "p": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    with _CACHE_LOCK, _cache_conn() as c:
        row = c.execute("SELECT response FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, response: dict) -> None:
    with _CACHE_LOCK, _cache_conn() as c:
        c.execute("INSERT OR REPLACE INTO cache(key,response,ts) VALUES(?,?,?)",
                  (key, json.dumps(response, ensure_ascii=False), time.time()))


class LLMError(RuntimeError):
    pass


def _client():
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY not set")
    from openai import OpenAI

    return OpenAI(api_key=config.OPENAI_API_KEY)


def complete(
    messages: list[dict[str, str]],
    *,
    purpose: str,
    model: str | None = None,
    tier: str = "task",            # "task" or "batch" (batch halts earlier)
    max_output_tokens: int | None = None,
    response_format: dict | None = None,
    temperature: float | None = None,
    agent: str = "",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return {text, model, usage, cached, est_cost_usd}. Raises BudgetExceeded / LLMError."""
    model = model or config.MODEL_CHEAP
    max_out = max_output_tokens or config.MAX_OUTPUT_TOKENS
    params = {"response_format": response_format, "temperature": temperature, "max_output_tokens": max_out}
    key = _key(model, messages, params)

    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            budget.record(purpose + ":cache", model, hit.get("usage", {}).get("input_tokens", 0),
                          hit.get("usage", {}).get("output_tokens", 0), cached=True, agent=agent)
            return {**hit, "cached": True, "est_cost_usd": 0.0}

    est_text = "\n".join(m.get("content", "") for m in messages)
    budget.check_can_spend(model, est_text, max_out, tier=tier)  # raises if over budget

    last_err: Exception | None = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            text, usage = _call_openai(model, messages, max_out, response_format, temperature)
            cost = budget.record(purpose, model, usage["input_tokens"], usage["output_tokens"],
                                 cached=False, agent=agent)
            result = {"text": text, "model": model, "usage": usage, "cached": False, "est_cost_usd": round(cost, 6)}
            if use_cache:
                _cache_put(key, {"text": text, "model": model, "usage": usage})
            return result
        except budget.BudgetExceeded:
            raise
        except Exception as e:  # keep error, allow retry; never fabricate
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise LLMError(f"LLM call failed after retries: {type(last_err).__name__}: {last_err}")


def _call_openai(model, messages, max_out, response_format, temperature):
    client = _client()
    # Prefer Responses API; fall back to Chat Completions for older models.
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_out,
        }
        if response_format and response_format.get("type") == "json_object":
            kwargs["text"] = {"format": {"type": "json_object"}}
        if temperature is not None:
            kwargs["temperature"] = temperature
        r = client.responses.create(**kwargs)
        text = getattr(r, "output_text", "") or ""
        u = getattr(r, "usage", None)
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) if u else 0,
            "output_tokens": getattr(u, "output_tokens", 0) if u else 0,
        }
        return text, usage
    except TypeError:
        pass
    # Chat Completions fallback
    kwargs = {"model": model, "messages": messages, "max_tokens": max_out}
    if response_format:
        kwargs["response_format"] = response_format
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = client.chat.completions.create(**kwargs)
    text = r.choices[0].message.content or ""
    u = r.usage
    usage = {"input_tokens": getattr(u, "prompt_tokens", 0), "output_tokens": getattr(u, "completion_tokens", 0)}
    return text, usage
