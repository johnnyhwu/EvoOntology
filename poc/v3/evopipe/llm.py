"""The ONLY place where an LLM is called.

    LLM(role).chat(stage=..., system=..., messages=[...]) -> text

A *backend* turns (model, system, messages) into text + token/cost accounting.
  * OpenRouterBackend  — production backend (OpenAI-compatible /chat/completions over HTTPS, stdlib only)
  * ClaudeCliBackend   — stand-in used while no OpenRouter key exists: `claude -p` with every tool,
                         memory and setting disabled, so it behaves as a plain text-completion API
  * MockBackend        — scripted replies for unit tests

Everything above this layer (agents, build, evolve, judge) is backend-agnostic: no native tool calling is
used; the tool protocol is plain JSON in text (see agent.py), so any chat model can be plugged in.
Every call is appended to runs/ledger.jsonl (cost, tokens, latency) and its full text to runs/llm_log/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config


class LLMError(RuntimeError):
    """Retryable / reportable backend failure."""


class LLMUnavailable(LLMError):
    """Non-retryable: quota/usage limit reached. Pipeline stages are resumable, so just re-run later."""


class BudgetExceeded(LLMError):
    pass


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    model: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- ledger
class Ledger:
    """Append-only cost/token record shared by all threads and all pipeline runs."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._total = 0.0
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    try:
                        self._total += float(json.loads(line).get("cost_usd", 0.0))
                    except (ValueError, TypeError):
                        pass

    @property
    def total(self) -> float:
        return self._total

    def check(self, cap: float) -> None:
        if self._total >= cap:
            raise BudgetExceeded("LLM budget cap reached: $%.4f >= $%.2f" % (self._total, cap))

    def add(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._total += float(record.get("cost_usd", 0.0))
            with open(self.path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")


_LEDGER: Optional[Ledger] = None


def ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger(os.path.join(config.RUNS, "ledger.jsonl"))
    return _LEDGER


# --------------------------------------------------------------------------- backends
def render_transcript(messages: List[Dict[str, str]]) -> str:
    """Flatten a chat into one prompt (for backends that only accept a single user turn)."""
    if len(messages) == 1:
        return messages[0]["content"]
    parts = ["以下是到目前為止的對話。請只回覆「下一則 assistant 訊息」，不要重複前文。\n"]
    for m in messages:
        parts.append("<%s>\n%s\n</%s>\n" % (m["role"], m["content"], m["role"]))
    return "\n".join(parts)


class ClaudeCliBackend:
    name = "claude_cli"

    def complete(self, *, model, system, messages, max_tokens, temperature=None) -> Completion:
        os.makedirs(config.LLM_CWD, exist_ok=True)
        cmd = ["claude", "-p", "--model", model, "--tools", "", "--system-prompt", system,
               "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
               "--disable-slash-commands", "--setting-sources", ""]
        started = time.time()
        proc = subprocess.run(cmd, input=render_transcript(messages), capture_output=True, text=True,
                              timeout=1200, cwd=config.LLM_CWD)
        latency = time.time() - started
        out = proc.stdout.strip()
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise LLMError("claude -p returned non-JSON (rc=%s): %s %s" % (proc.returncode, out[:300], proc.stderr[:300]))
        if data.get("is_error") or proc.returncode != 0:
            msg = str(data.get("result") or proc.stderr)[:400]
            if re.search(r"usage limit|session limit|limit reached|resets", msg, re.I):
                raise LLMUnavailable(msg)
            raise LLMError("claude -p error: " + msg)
        usage = data.get("usage", {})
        tokens_in = (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                     + usage.get("cache_read_input_tokens", 0))
        return Completion(text=data.get("result", ""), input_tokens=tokens_in,
                          output_tokens=usage.get("output_tokens", 0),
                          cost_usd=float(data.get("total_cost_usd", 0.0)), latency_s=latency, model=model,
                          raw={"session_id": data.get("session_id"), "num_turns": data.get("num_turns")})


def load_env_file(path: str) -> Dict[str, str]:
    values = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


class OpenRouterBackend:
    """OpenAI-compatible chat completions. Key from env OPENROUTER_API_KEY or poc/.env (never logged)."""
    name = "openrouter"

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or config.OPENROUTER_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or load_env_file(config.ENV_FILE).get("OPENROUTER_API_KEY")

    def complete(self, *, model, system, messages, max_tokens, temperature=0.0) -> Completion:
        if not self.api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY not set (env or poc/.env)")
        body = {"model": model, "temperature": 0.0 if temperature is None else temperature,
                "max_tokens": max_tokens, "usage": {"include": True},
                "messages": [{"role": "system", "content": system}] + messages}
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
                     "X-Title": "EvoOntology PoC"})
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (401, 402, 403):
                raise LLMUnavailable("OpenRouter HTTP %s: %s" % (exc.code, detail))
            raise LLMError("OpenRouter HTTP %s: %s" % (exc.code, detail))      # 429 / 5xx -> retried by LLM.chat
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError("OpenRouter network error: %s" % exc)
        if "error" in data:
            raise LLMError("OpenRouter error: %s" % json.dumps(data["error"])[:300])
        usage = data.get("usage", {})
        return Completion(text=data["choices"][0]["message"].get("content") or "",
                          input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0),
                          cost_usd=float(usage.get("cost", 0.0)), latency_s=time.time() - started,
                          model=data.get("model", model), raw={"id": data.get("id")})


class MockBackend:
    """Scripted backend for tests: ``replies`` is a list of strings or callables(system, messages)->str."""
    name = "mock"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, *, model, system, messages, max_tokens, temperature=None) -> Completion:
        self.calls.append({"model": model, "system": system, "messages": [dict(m) for m in messages]})
        reply = self.replies.pop(0)
        text = reply(system, messages) if callable(reply) else reply
        return Completion(text=text, input_tokens=10, output_tokens=5, cost_usd=0.0, model=model)


def make_backend(name: Optional[str] = None):
    name = name or config.BACKEND
    if name == "claude_cli":
        return ClaudeCliBackend()
    if name == "openrouter":
        return OpenRouterBackend()
    raise ValueError("unknown backend %r (mock backends are constructed directly in tests)" % name)


# --------------------------------------------------------------------------- facade
_log_counter = {"n": 0}
_log_lock = threading.Lock()


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in ``text`` (tolerates ```json fences and chatter)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = [fence.group(1).strip()] if fence else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"[\{\[]", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model output: %r" % text[:200])


class LLM:
    def __init__(self, role: str, backend=None, models: Optional[Dict[str, str]] = None, stage_prefix: str = ""):
        self.role = role
        self.backend = backend or make_backend()
        if models is None:
            models = config.OPENROUTER_ROLE_MODELS if self.backend.name == "openrouter" else config.ROLE_MODELS
        self.model = models[role]
        self.stage_prefix = stage_prefix

    def chat(self, *, stage: str, system: str, messages: List[Dict[str, str]], max_tokens: int = 16000,
             retries: int = 4) -> str:
        ledger().check(config.BUDGET_USD)
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                completion = self.backend.complete(model=self.model, system=system, messages=messages,
                                                   max_tokens=max_tokens, temperature=0.0)
                break
            except LLMUnavailable:
                raise
            except LLMError as exc:
                last = exc
                time.sleep(min(60, 3 * 2 ** attempt))
        else:
            raise LLMError("giving up after %d attempts: %s" % (retries + 1, last))
        self._record(stage, system, messages, completion)
        return completion.text

    def _record(self, stage, system, messages, completion: Completion) -> None:
        with _log_lock:
            _log_counter["n"] += 1
            call_id = "%s_%06d" % (time.strftime("%m%d_%H%M%S"), _log_counter["n"])
        system_hash = hashlib.sha1(system.encode("utf-8")).hexdigest()[:12]
        store = os.path.join(config.RUNS, "llm_log", "system")
        os.makedirs(store, exist_ok=True)
        path = os.path.join(store, system_hash + ".txt")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(system)
        record = {"call_id": call_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": self.stage_prefix + stage,
                  "role": self.role, "model": completion.model or self.model, "backend": self.backend.name,
                  "input_tokens": completion.input_tokens, "output_tokens": completion.output_tokens,
                  "cost_usd": completion.cost_usd, "latency_s": round(completion.latency_s, 2),
                  "system_sha1": system_hash}
        ledger().add(record)
        full = dict(record, messages=messages, response=completion.text)
        os.makedirs(os.path.join(config.RUNS, "llm_log"), exist_ok=True)
        with open(os.path.join(config.RUNS, "llm_log", call_id + ".json"), "w", encoding="utf-8") as stream:
            json.dump(full, stream, ensure_ascii=False)
