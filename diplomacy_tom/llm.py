"""Provider abstraction, model routing, and cost accounting.

Three requirements shape this module, and they pull against each other:

1. **Determinism.** LLM calls are nondeterministic, but D4 needs both ablation arms
   to run on identical conditions and CI must run without an API key. Solved by
   making record/replay a first-class provider rather than a test hack: every call is
   recorded into the turn log's `llm_calls`, keyed by prompt hash, and a logged run
   replays exactly with no network.

2. **Cost.** Betrayal-prediction accuracy needs tens of games. Prompt caching and
   model routing are therefore designed in, not retrofitted -- see ARCHITECTURE.md
   section 5. Every response carries usage, so cost-per-game is derivable from the
   artifact itself.

3. **Provider choice.** Anthropic is the primary path via the official SDK.
   OpenRouter is supported for swapping in cheaper or open models, over raw HTTP
   (it has no official Python SDK, and reaching for an OpenAI-compatible shim to
   call Claude would be wrong).

The Provider protocol is the seam. Nothing above this module knows which provider,
or whether a call is live, recorded, replayed or mocked.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    """What we need to know about a model to route to it and cost it.

    Prices are USD per million tokens. `None` means unknown -- OpenRouter's catalogue
    is large and changes, so prices there are fetched from its /models endpoint at
    runtime rather than invented here.
    """

    model_id: str
    provider: str
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cache_read_per_mtok: float | None = None
    supports_caching: bool = False
    supports_adaptive_thinking: bool = False

    def cost_usd(self, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float | None:
        if self.input_per_mtok is None or self.output_per_mtok is None:
            return None
        cache_rate = (
            self.cache_read_per_mtok
            if self.cache_read_per_mtok is not None
            else self.input_per_mtok * 0.1
        )
        return (
            input_tokens / 1e6 * self.input_per_mtok
            + output_tokens / 1e6 * self.output_per_mtok
            + cache_read / 1e6 * cache_rate
        )


# Anthropic first-party pricing, USD per million tokens.
ANTHROPIC_MODELS: dict[str, ModelSpec] = {
    "claude-opus-5": ModelSpec(
        "claude-opus-5", "anthropic", 5.00, 25.00,
        supports_caching=True, supports_adaptive_thinking=True,
    ),
    "claude-sonnet-5": ModelSpec(
        "claude-sonnet-5", "anthropic", 2.00, 10.00,
        supports_caching=True, supports_adaptive_thinking=True,
    ),
    "claude-haiku-4-5": ModelSpec(
        "claude-haiku-4-5", "anthropic", 1.00, 5.00,
        supports_caching=True, supports_adaptive_thinking=False,
    ),
}


def openrouter_model(model_id: str, **prices) -> ModelSpec:
    """An OpenRouter-routed model. Prices default to unknown and are filled from
    OpenRouter's own catalogue when the provider is constructed."""
    return ModelSpec(model_id, "openrouter", supports_caching=False, **prices)


MODELS: dict[str, ModelSpec] = dict(ANTHROPIC_MODELS)


def resolve_model(model_id: str) -> ModelSpec:
    """Known models come from the registry; anything else is assumed OpenRouter.

    A slash in the id ("meta-llama/llama-3.3-70b-instruct") is OpenRouter's naming
    convention, so unknown ids route there rather than failing.
    """
    if model_id in MODELS:
        return MODELS[model_id]
    spec = openrouter_model(model_id)
    MODELS[model_id] = spec
    return spec


# --------------------------------------------------------------------------
# Request / response
# --------------------------------------------------------------------------


@dataclass
class LLMRequest:
    """One call. `cacheable_system` is separated from `system` deliberately.

    Prompt caching is a prefix match: tools -> system -> messages, and any byte
    change invalidates everything after it. Keeping the stable part (rules, map,
    schema) in its own field makes the breakpoint placement explicit instead of
    accidental, and makes it obvious when volatile content has crept forward.
    """

    role: str                       # negotiator | belief_evaluator | decision
    cacheable_system: str           # stable prefix: rules, map, output contract
    system: str = ""                # volatile system content, after the breakpoint
    messages: list[dict] = field(default_factory=list)
    tool: dict | None = None        # structured-output tool schema
    max_tokens: int = 4096
    effort: str | None = None       # low | medium | high | xhigh | max
    thinking: bool = True
    # Structured echo of data already present in `messages`, for MockProvider only.
    # Real providers never read it, and it is excluded from cache_key so it cannot
    # affect hashing or replay. It exists so the mock can return *legal* orders and
    # belief-sensitive choices -- without it every mock decision is invalid, the
    # decision layer is never exercised, and the D4 ablation cannot be tested in CI.
    mock_hint: dict | None = None

    def cache_key(self) -> str:
        """Stable hash of everything that determines the response.

        sort_keys is not cosmetic: unsorted JSON is one of the classic silent cache
        invalidators, and here it would also break replay lookup.
        """
        payload = json.dumps(
            {
                "role": self.role,
                "cacheable_system": self.cacheable_system,
                "system": self.system,
                "messages": self.messages,
                "tool": self.tool,
                "max_tokens": self.max_tokens,
                "effort": self.effort,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class LLMResponse:
    text: str = ""
    data: dict | None = None        # parsed structured output, when a tool was used
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def as_log_entry(self, request: LLMRequest, phase: str) -> dict:
        entry = {
            "call_id": self.call_id,
            "phase": phase,
            "role": request.role,
            "model": self.model,
            "prompt_sha256": request.cache_key(),
            "response": json.dumps(self.data) if self.data is not None else self.text,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "cache_read_tokens": self.cache_read_tokens,
        }
        if self.cost_usd is not None:
            entry["usage"]["cost_usd"] = round(self.cost_usd, 8)
        return entry


class Provider(Protocol):
    name: str

    def complete(self, request: LLMRequest, model: str) -> LLMResponse: ...


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------


class AnthropicProvider:
    """Official SDK. Caching and adaptive thinking are on by default.

    Structured output uses strict tool calling rather than free-text JSON: `strict`
    guarantees the arguments validate against the schema, which matters because a
    malformed stated_intent silently degrades the eval rather than failing loudly.
    """

    name = "anthropic"

    def __init__(self, client=None) -> None:
        if client is None:
            import anthropic  # imported lazily so CI can run without the dep
            client = anthropic.Anthropic()
        self.client = client

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        spec = resolve_model(model)

        # Order matters for caching: the stable block carries the breakpoint, and
        # everything volatile goes after it.
        system: list[dict[str, Any]] = [{
            "type": "text",
            "text": request.cacheable_system,
            "cache_control": {"type": "ephemeral"},
        }]
        if request.system:
            system.append({"type": "text", "text": request.system})

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": system,
            "messages": request.messages,
        }

        if request.thinking and spec.supports_adaptive_thinking:
            # budget_tokens is removed on current models -- adaptive replaces it.
            kwargs["thinking"] = {"type": "adaptive"}
        if request.effort:
            kwargs["output_config"] = {"effort": request.effort}

        if request.tool:
            kwargs["tools"] = [{
                "name": request.tool["name"],
                "description": request.tool.get("description", ""),
                "input_schema": request.tool["schema"],
                "strict": True,
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": request.tool["name"]}

        message = self.client.messages.create(**kwargs)

        # Guard before reading content: a refusal returns HTTP 200.
        if getattr(message, "stop_reason", None) == "refusal":
            detail = getattr(message, "stop_details", None)
            raise RuntimeError(
                f"model refused ({getattr(detail, 'category', 'unknown')}): "
                f"{getattr(detail, 'explanation', '')}"
            )

        text_parts, data = [], None
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                # Never string-match serialized tool input; escaping varies by model.
                data = dict(block.input)

        usage = message.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        return LLMResponse(
            text="".join(text_parts),
            data=data,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cost_usd=spec.cost_usd(usage.input_tokens, usage.output_tokens, cache_read),
        )


# --------------------------------------------------------------------------
# OpenRouter
# --------------------------------------------------------------------------


class OpenRouterProvider:
    """OpenRouter over raw HTTP -- it has no official Python SDK.

    Deliberately not routed through an OpenAI-compatible shim for Anthropic models:
    if you want Claude, use AnthropicProvider, which gets caching, adaptive thinking
    and strict tool use. This path exists for swapping in cheaper or open models.
    """

    name = "openrouter"
    BASE = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str | None = None, *, fetch_pricing: bool = True) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OpenRouter needs an API key: set OPENROUTER_API_KEY or pass api_key"
            )
        self._pricing_loaded = False
        if fetch_pricing:
            try:
                self.load_pricing()
            except Exception:
                # Cost accounting degrades to None rather than blocking a run.
                pass

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.BASE}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"OpenRouter {exc.code}: {exc.read().decode()[:400]}"
            ) from exc

    def load_pricing(self) -> int:
        """Populate the registry from OpenRouter's own catalogue.

        Prices are read rather than hardcoded: the catalogue is large, changes, and
        inventing numbers would put fiction into the cost-per-game metric.
        """
        req = urllib.request.Request(
            f"{self.BASE}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            catalogue = json.loads(resp.read())

        count = 0
        for entry in catalogue.get("data", []):
            pricing = entry.get("pricing") or {}
            try:  # OpenRouter quotes USD per token as strings
                prompt = float(pricing.get("prompt", "0")) * 1e6
                completion = float(pricing.get("completion", "0")) * 1e6
            except (TypeError, ValueError):
                continue
            MODELS[entry["id"]] = ModelSpec(
                entry["id"], "openrouter", prompt, completion,
            )
            count += 1
        self._pricing_loaded = True
        return count

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        spec = resolve_model(model)
        system_text = "\n\n".join(p for p in (request.cacheable_system, request.system) if p)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "system", "content": system_text}, *request.messages],
        }
        if request.tool:
            payload["tools"] = [{
                "type": "function",
                "function": {
                    "name": request.tool["name"],
                    "description": request.tool.get("description", ""),
                    "parameters": request.tool["schema"],
                },
            }]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": request.tool["name"]},
            }

        result = self._post("/chat/completions", payload)
        choice = (result.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        data = None
        for call in msg.get("tool_calls") or []:
            try:
                data = json.loads(call["function"]["arguments"])
            except (KeyError, json.JSONDecodeError):
                data = None

        usage = result.get("usage") or {}
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)
        return LLMResponse(
            text=msg.get("content") or "",
            data=data,
            model=model,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=spec.cost_usd(inp, out),
        )


# --------------------------------------------------------------------------
# Determinism wrappers
# --------------------------------------------------------------------------


class RecordingProvider:
    """Wraps a live provider and records every call for later replay."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.name = f"recording:{inner.name}"
        self.calls: list[dict] = []
        self._by_key: dict[str, LLMResponse] = {}

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        response = self.inner.complete(request, model)
        self._by_key[request.cache_key()] = response
        return response

    def record(self, request: LLMRequest, response: LLMResponse, phase: str) -> None:
        self.calls.append(response.as_log_entry(request, phase))


class ReplayProvider:
    """Replays a recorded run with no network.

    This is what makes an LLM game reproducible, and therefore what makes the D4
    comparison and CI possible at all. Lookup is by prompt hash, so a changed prompt
    is a miss rather than a silently wrong answer.
    """

    name = "replay"

    def __init__(self, llm_calls: list[dict], *, strict: bool = True) -> None:
        self.strict = strict
        self.by_hash: dict[str, dict] = {c["prompt_sha256"]: c for c in llm_calls}
        self.misses: list[str] = []

    @classmethod
    def from_log(cls, log: dict, **kwargs) -> "ReplayProvider":
        return cls(log.get("llm_calls", []), **kwargs)

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        key = request.cache_key()
        entry = self.by_hash.get(key)
        if entry is None:
            self.misses.append(key)
            if self.strict:
                raise KeyError(
                    f"no recorded response for {request.role} prompt {key[:12]}... -- "
                    "the prompt changed since recording, so this run is not a replay"
                )
            return LLMResponse(text="", model=model)

        raw = entry.get("response", "")
        data = None
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
        usage = entry.get("usage") or {}
        return LLMResponse(
            text="" if data is not None else raw,
            data=data,
            model=entry.get("model", model),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=entry.get("cache_read_tokens", 0),
            cost_usd=usage.get("cost_usd"),
            call_id=entry.get("call_id", uuid.uuid4().hex),
        )


class MockProvider:
    """Deterministic synthetic responses. No API key, no network, no cost.

    Used by CI and by anyone running the test suite. Responses are derived from the
    prompt hash, so they are stable across processes and vary meaningfully between
    different prompts -- enough to exercise parsing, belief updates and the log
    without pretending to be real model output.
    """

    name = "mock"

    def __init__(self, seed_salt: str = "") -> None:
        self.seed_salt = seed_salt
        self.call_count = 0

    def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        self.call_count += 1
        digest = hashlib.sha256((request.cache_key() + self.seed_salt).encode()).digest()

        data = None
        if request.tool:
            data = self._synth(request.tool["schema"], digest)
            hint = request.mock_hint or {}
            if request.tool["name"] == "submit_orders" and hint.get("legal_orders"):
                data["orders"] = self._pick_orders(hint, digest)
            elif request.tool["name"] == "send_messages" and hint.get("counterparts"):
                data["messages"] = self._pick_messages(hint, digest)

        spec = resolve_model(model)
        inp, out = 1200, 180
        return LLMResponse(
            text=f"[mock:{request.role}] {digest[:4].hex()}",
            data=data,
            model=model,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=spec.cost_usd(inp, out),
        )

    def _pick_orders(self, hint: dict, digest: bytes) -> list[str]:
        """One legal order per location, biased by belief state.

        The bias is what makes the two ablation arms diverge: belief_on supplies
        varying trust values and belief_off supplies a constant, so the same seed
        produces different order choices. Crude, but it exercises the real property.
        """
        trust = hint.get("trust") or {}
        bias = int(sum(round(v * 1000) for v in trust.values())) if trust else 0
        orders = []
        for i, (loc, options) in enumerate(sorted(hint["legal_orders"].items())):
            if not options:
                continue
            idx = (digest[i % len(digest)] + bias) % len(options)
            orders.append(sorted(options)[idx])
        return orders

    def _pick_messages(self, hint: dict, digest: bytes) -> list[dict]:
        """A message to a subset of real counterparts, naming a real province.

        Bodies embed the dyad so they are distinct, as real negotiation messages
        would be. Identical bodies across dyads are handled by the isolation gate
        (finding F7), but a mock should not manufacture that edge case on every run.
        """
        counterparts = sorted(hint["counterparts"])
        provinces = sorted(hint.get("provinces") or ["BEL"])
        out = []
        for i, other in enumerate(counterparts):
            if digest[(i * 3) % len(digest)] % 3 == 0:
                continue
            province = provinces[digest[(i * 5) % len(digest)] % len(provinces)]
            out.append({
                "recipient": other,
                "body": (
                    f"[mock {hint.get('sender', '?')}->{other}] "
                    f"I will not move on {province} this phase."
                ),
                "stated_intent": [{
                    "commitment_type": "non_aggression",
                    "text": f"no move on {province}",
                    "concerns_provinces": [province],
                }],
            })
        return out

    def _synth(self, schema: dict, digest: bytes, depth: int = 0) -> Any:
        """Build a schema-valid value deterministically from the digest."""
        t = schema.get("type")
        if "enum" in schema:
            options = schema["enum"]
            return options[digest[depth % len(digest)] % len(options)]
        if t == "object":
            out = {}
            for i, (key, sub) in enumerate(sorted((schema.get("properties") or {}).items())):
                if key in schema.get("required", []) or digest[(depth + i) % len(digest)] % 2:
                    out[key] = self._synth(sub, digest, depth + i + 1)
            return out
        if t == "array":
            item = schema.get("items") or {"type": "string"}
            n = 1 + digest[depth % len(digest)] % 2
            return [self._synth(item, digest, depth + i + 1) for i in range(n)]
        if t == "integer":
            lo = schema.get("minimum", 1)
            return int(lo) + digest[depth % len(digest)] % 3
        if t == "number":
            lo = schema.get("minimum", 0.0)
            hi = schema.get("maximum", 1.0)
            return round(lo + (hi - lo) * (digest[depth % len(digest)] / 255), 3)
        if t == "boolean":
            return bool(digest[depth % len(digest)] % 2)
        return f"m{digest[depth % len(digest)]:02x}"


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

# Default: the strongest model everywhere. Cost tuning is an explicit decision, not
# a silent default -- but the presets below make it a one-liner.
DEFAULT_ROUTING = {
    "negotiator": "claude-opus-5",
    "belief_evaluator": "claude-opus-5",
    "decision": "claude-opus-5",
}

PRESETS: dict[str, dict[str, str]] = {
    "quality": DEFAULT_ROUTING,
    # The belief evaluator is the reasoning-critical role -- it is the component
    # under test in D4 -- so it keeps the strong model while the rest step down.
    "balanced": {
        "negotiator": "claude-sonnet-5",
        "belief_evaluator": "claude-opus-5",
        "decision": "claude-sonnet-5",
    },
    "cheap": {
        "negotiator": "claude-haiku-4-5",
        "belief_evaluator": "claude-sonnet-5",
        "decision": "claude-haiku-4-5",
    },
}


class Router:
    """Maps a role to a model and the provider that serves it."""

    def __init__(
        self,
        routing: dict[str, str] | str | None = None,
        providers: dict[str, Provider] | None = None,
        *,
        force_provider: Provider | None = None,
    ) -> None:
        if isinstance(routing, str):
            if routing not in PRESETS:
                raise ValueError(f"unknown preset {routing!r}; have {sorted(PRESETS)}")
            routing = PRESETS[routing]
        self.routing = dict(routing or DEFAULT_ROUTING)
        self.providers = providers or {}
        self.force_provider = force_provider

    def model_for(self, role: str) -> str:
        if role not in self.routing:
            raise ValueError(f"no model routed for role {role!r}")
        return self.routing[role]

    def provider_for(self, role: str) -> Provider:
        """A forced provider (mock, replay) overrides routing entirely -- that is how
        a recorded game replays regardless of which providers it originally used."""
        if self.force_provider is not None:
            return self.force_provider
        spec = resolve_model(self.model_for(role))
        if spec.provider not in self.providers:
            self.providers[spec.provider] = (
                AnthropicProvider() if spec.provider == "anthropic" else OpenRouterProvider()
            )
        return self.providers[spec.provider]

    def complete(self, request: LLMRequest) -> LLMResponse:
        return self.provider_for(request.role).complete(request, self.model_for(request.role))

    def describe(self) -> dict[str, str]:
        return dict(self.routing)
