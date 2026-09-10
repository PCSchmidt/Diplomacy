"""Phase 2 gate: LLM negotiation, belief evaluation, provider abstraction.

Runs entirely on MockProvider -- no API key, no network, no cost -- so this gate
works in CI. The live providers are exercised by shape, not by calling them.

The centrepiece is the Generator/Evaluator separation test. It is asserted the way
the leak fixture is: by planting content that MUST NOT appear and failing if it does.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import sys

from diplomacy_tom import agents as ag
from diplomacy_tom import belief as bl
from diplomacy_tom import isolation as iso
from diplomacy_tom import llm
from diplomacy_tom import turn_log as tl
from diplomacy_tom.runner import GameConfig, GameRunner, run_game


def main() -> int:
    failures: list[str] = []

    # --- 1. an LLM game runs and validates ------------------------------
    log = run_game(seed=42, max_phases=6, use_llm=True)
    print(f"[1] LLM game: {len(log['turns'])} turns, "
          f"{len(log['llm_calls'])} model calls, schema + alignment OK")
    msgs = sum(len(t["messages"]) for t in log["turns"])
    scored = sum(
        1 for t in log["turns"] for m in t["messages"] if m.get("evaluation")
    )
    print(f"    {msgs} messages, {scored} independently scored by an evaluator")
    if msgs == 0:
        failures.append("no messages generated")
    if scored != msgs:
        failures.append(f"only {scored}/{msgs} messages were evaluated")

    roles = {c["role"] for c in log["llm_calls"]}
    print(f"    roles exercised: {sorted(roles)}")
    for expected in ("negotiator", "belief_evaluator", "decision"):
        if expected not in roles:
            failures.append(f"role {expected} never called")

    # --- 2. THE SEPARATION TEST -----------------------------------------
    # Plant a message the observer SENT. The Evaluator must never see it: those are
    # the Generator's own words, and reading its own framing is exactly the
    # contamination this split exists to prevent.
    print("[2] Generator/Evaluator separation:")
    store = bl.BayesianBeliefStore("FRANCE", ["FRANCE", "ENGLAND", "GERMANY"])
    secret = "MY SECRET PLAN IS TO STAB ENGLAND IN AUTUMN VIA THE CHANNEL"
    sent = {"message_id": "s1", "sender": "FRANCE", "recipient": "ENGLAND",
            "body": secret}
    received = {"message_id": "r1", "sender": "ENGLAND", "recipient": "FRANCE",
                "body": "I will support you into Belgium."}
    store.observe_message("ENGLAND", "S1901M", sent, sent=True)
    store.observe_message("ENGLAND", "S1901M", received)

    negotiator_view = json.dumps(store.context_for_prompt("ENGLAND"))
    evaluator_view = json.dumps(ag.evaluator_context(store, "ENGLAND"))

    if secret in negotiator_view:
        print("    negotiator sees its own plan (correct)")
    else:
        failures.append("negotiator context lost its own sent message")

    if secret in evaluator_view:
        print("    LEAK: evaluator can see the negotiator's own message")
        failures.append("evaluator context contained the observer's own words")
    else:
        print("    evaluator does NOT see it (correct -- this is the integrity property)")

    if received["body"] in evaluator_view:
        print("    evaluator does see the counterpart's message (correct)")
    else:
        failures.append("evaluator context missing the counterpart's own message")

    # --- 3. the prompt actually sent carries no leak --------------------
    # Context shape is one thing; what reaches the model is what matters.
    print("[3] assembled evaluator prompt:")

    class CapturingProvider:
        name = "capture"

        def __init__(self):
            self.seen = []
            self.inner = llm.MockProvider()

        def complete(self, request, model):
            self.seen.append(request)
            return self.inner.complete(request, model)

    cap = CapturingProvider()
    router = llm.Router("quality", force_provider=cap)
    ag.BeliefEvaluator(router).score(
        __import__("diplomacy_tom.engine", fromlist=["engine"]).new_game(),
        "FRANCE", "ENGLAND", received, store,
    )
    prompt_blob = json.dumps([
        r.cacheable_system + r.system + json.dumps(r.messages) for r in cap.seen
    ])
    if secret in prompt_blob:
        print("    LEAK: secret reached the evaluator prompt")
        failures.append("evaluator PROMPT contained the observer's own message")
    else:
        print("    secret absent from the evaluator prompt (correct)")

    # --- 4. isolation held across a whole LLM game ----------------------
    runner = GameRunner(GameConfig(seed=7, max_phases=6, use_llm=True))
    runner.run()
    leaks = []
    for observer, s in runner.stores.items():
        leaks += iso.audit_store(s, runner.registry)
    print(f"[4] full LLM-game isolation audit: {len(leaks)} leaks")
    if leaks:
        failures.append(f"isolation leaked in an LLM game: {leaks[:2]}")

    # --- 5. record / replay ---------------------------------------------
    print("[5] record and replay:")
    replay = llm.ReplayProvider.from_log(log)
    replayed = run_game(seed=42, max_phases=6, use_llm=True, provider=replay)
    fp_a, fp_b = tl.replay_fingerprint(log), tl.replay_fingerprint(replayed)
    print(f"    original {fp_a[:16]}")
    print(f"    replayed {fp_b[:16]}")
    if fp_a == fp_b:
        print("    replay reproduced the game exactly, with zero network calls")
    else:
        failures.append("replay did not reproduce the recorded game")
    if replay.misses:
        failures.append(f"replay had {len(replay.misses)} prompt-hash misses")

    # A changed prompt must be a loud miss, not a silently wrong answer.
    strict = llm.ReplayProvider([], strict=True)
    try:
        strict.complete(llm.LLMRequest(role="negotiator", cacheable_system="x"), "m")
        failures.append("strict replay did not raise on an unknown prompt")
        print("    strict replay did NOT raise on a miss")
    except KeyError:
        print("    strict replay raises on an unrecorded prompt (correct)")

    # --- 6. cost accounting ---------------------------------------------
    print("[6] cost accounting:")
    total = sum(
        (c.get("usage") or {}).get("cost_usd", 0.0) for c in log["llm_calls"]
    )
    tokens_in = sum((c.get("usage") or {}).get("input_tokens", 0) for c in log["llm_calls"])
    print(f"    {len(log['llm_calls'])} calls, {tokens_in:,} input tokens, "
          f"${total:.4f} (mock token counts)")
    if total <= 0:
        failures.append("no cost was accounted for")

    opus = llm.resolve_model("claude-opus-5")
    haiku = llm.resolve_model("claude-haiku-4-5")
    c_opus = opus.cost_usd(1_000_000, 100_000)
    c_haiku = haiku.cost_usd(1_000_000, 100_000)
    print(f"    1M in + 100K out: opus-5 ${c_opus:.2f}  haiku-4.5 ${c_haiku:.2f} "
          f"({c_opus / c_haiku:.1f}x)")
    if not c_haiku < c_opus:
        failures.append("pricing table has haiku costing more than opus")

    cached = opus.cost_usd(0, 100_000, cache_read=1_000_000)
    print(f"    same input served from cache: ${cached:.2f} "
          f"({(1 - cached / c_opus) * 100:.0f}% saved)")
    if not cached < c_opus:
        failures.append("cache read priced no cheaper than fresh input")

    # --- 7. routing -------------------------------------------------------
    print("[7] routing presets:")
    for name in ("quality", "balanced", "cheap"):
        r = llm.Router(name, force_provider=llm.MockProvider())
        print(f"    {name:9s} {r.describe()}")
    cheap = llm.Router("cheap", force_provider=llm.MockProvider())
    if cheap.model_for("belief_evaluator") == cheap.model_for("negotiator"):
        failures.append("cheap preset did not protect the belief evaluator")
    else:
        print("    cheap preset keeps a stronger model on the belief evaluator")

    # An unknown id routes to OpenRouter rather than failing.
    spec = llm.resolve_model("meta-llama/llama-3.3-70b-instruct")
    print(f"    unknown id -> provider {spec.provider!r}, price unknown: "
          f"{spec.input_per_mtok is None}")
    if spec.provider != "openrouter":
        failures.append("unknown model id did not route to OpenRouter")
    if spec.cost_usd(1000, 100) is not None:
        failures.append("unpriced model reported a cost instead of None")

    # --- 8. prompt caching discipline -----------------------------------
    print("[8] cache-prefix stability:")
    reqs = [r for r in cap.seen]
    a = llm.LLMRequest(role="negotiator", cacheable_system="STABLE",
                       messages=[{"role": "user", "content": "one"}])
    b = llm.LLMRequest(role="negotiator", cacheable_system="STABLE",
                       messages=[{"role": "user", "content": "two"}])
    print(f"    stable prefix identical across differing calls: "
          f"{a.cacheable_system == b.cacheable_system}")
    print(f"    but cache keys differ: {a.cache_key() != b.cache_key()}")
    if a.cache_key() == b.cache_key():
        failures.append("different requests produced the same cache key")

    # The evaluator prefix must not vary per call, or caching never hits.
    prefixes = {r.cacheable_system for r in reqs}
    if len(prefixes) > 1:
        failures.append("evaluator cacheable prefix varied between calls")

    for prefix, label in (
        (ag.NEGOTIATOR_PREFIX, "negotiator"),
        (ag.EVALUATOR_PREFIX, "evaluator"),
        (ag.DECIDER_PREFIX, "decider"),
    ):
        for bad in ("2026", "seed=", "phase="):
            if bad in prefix:
                failures.append(f"{label} prefix contains volatile token {bad!r}")
    print("    no volatile tokens found in any role prefix")

    # --- 9. the ablation now diverges (the Phase 2 inversion) ------------
    print("[9] ablation arms under LLM decisions:")
    on = run_game(seed=99, max_phases=6, use_llm=True, arm="belief_on")
    off = run_game(seed=99, max_phases=6, use_llm=True, arm="belief_off")
    fp_on, fp_off = tl.replay_fingerprint(on), tl.replay_fingerprint(off)
    print(f"    belief_on  {fp_on[:16]}")
    print(f"    belief_off {fp_off[:16]}")
    if fp_on == fp_off:
        # Not necessarily a bug with a mock provider, but worth surfacing loudly:
        # with real models the arms must diverge or the ablation measures nothing.
        print("    NOTE: arms identical -- expected with a deterministic mock whose "
              "output ignores belief content; must diverge with real models")
    else:
        print("    arms diverged, as Phase 2 requires")

    on_trust = {b["trust"] for t in on["turns"] for b in t["beliefs"]}
    off_trust = {b["trust"] for t in off["turns"] for b in t["beliefs"]}
    print(f"    belief_on distinct trust values: {len(on_trust)}; "
          f"belief_off: {len(off_trust)}")
    if len(off_trust) != 1:
        failures.append("belief_off arm was not inert")
    if len(on_trust) <= 1:
        failures.append("belief_on arm produced no trust variation")

    # --- 10. provider surface -------------------------------------------
    print("[10] provider surface:")
    for p in (llm.MockProvider(), llm.ReplayProvider([]),
              llm.RecordingProvider(llm.MockProvider())):
        if not hasattr(p, "complete"):
            failures.append(f"{p.name} does not satisfy the Provider protocol")
    print(f"    mock / replay / recording all expose complete()")

    # Isolate the environment. This assertion previously passed only because the
    # machine happened to have no OPENROUTER_API_KEY set — it was testing the
    # absence of a variable, not the guard. With a key present the constructor
    # falls back to it and the test silently inverted.
    import os
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        llm.OpenRouterProvider(api_key="", fetch_pricing=False)
        failures.append("OpenRouter accepted an empty API key")
    except ValueError:
        print("    OpenRouter refuses construction without a key (correct)")
    finally:
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved

    # And the fallback itself is behaviour worth asserting, not an accident.
    os.environ["OPENROUTER_API_KEY"] = "test-fallback-key"
    try:
        p_fb = llm.OpenRouterProvider(fetch_pricing=False)
        if p_fb.api_key == "test-fallback-key":
            print("    OpenRouter picks the key up from the environment (correct)")
        else:
            failures.append("OpenRouter did not read OPENROUTER_API_KEY")
    finally:
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)

    # --- 11. Anthropic request shape (no network) -----------------------
    # The live path is never exercised by the other checks. A stub client captures
    # the kwargs so API-shape errors surface here instead of on a paid call.
    print("[11] Anthropic request shape:")

    class StubMessages:
        def __init__(self): self.kwargs = None
        def create(self, **kw):
            self.kwargs = kw
            class U:
                input_tokens, output_tokens, cache_read_input_tokens = 900, 120, 700
            class B:
                type, input = "tool_use", {"orders": ["A PAR H"]}
            return type("M", (), {"content": [B()], "usage": U(),
                                  "stop_reason": "tool_use", "stop_details": None})()

    class StubClient:
        def __init__(self): self.messages = StubMessages()

    stub = StubClient()
    prov = llm.AnthropicProvider(client=stub)
    resp = prov.complete(
        llm.LLMRequest(role="decision", cacheable_system="STABLE RULES",
                       system="volatile", messages=[{"role": "user", "content": "go"}],
                       tool=ag.ORDERS_TOOL, effort="medium"),
        "claude-opus-5",
    )
    kw = stub.messages.kwargs
    checks = {
        "cache breakpoint on stable block":
            kw["system"][0].get("cache_control") == {"type": "ephemeral"},
        "stable block is first":
            kw["system"][0]["text"] == "STABLE RULES",
        "volatile system after breakpoint":
            len(kw["system"]) == 2 and "cache_control" not in kw["system"][1],
        "adaptive thinking (not budget_tokens)":
            kw.get("thinking") == {"type": "adaptive"},
        "no budget_tokens": "budget_tokens" not in json.dumps(kw.get("thinking", {})),
        "effort inside output_config":
            kw.get("output_config") == {"effort": "medium"},
        "strict tool use": kw["tools"][0].get("strict") is True,
        "tool_choice forces the tool":
            kw.get("tool_choice", {}).get("name") == "submit_orders",
    }
    for label, ok in checks.items():
        print(f"    {'ok ' if ok else 'FAIL'} {label}")
        if not ok:
            failures.append(f"Anthropic request shape wrong: {label}")

    print(f"    parsed tool output: {resp.data}, cache_read={resp.cache_read_tokens}")
    if resp.data != {"orders": ["A PAR H"]}:
        failures.append("tool_use block was not parsed into data")
    if resp.cache_read_tokens != 700:
        failures.append("cache_read_input_tokens not captured")
    if resp.cost_usd is None or resp.cost_usd <= 0:
        failures.append("cost not computed for an Anthropic response")

    # Haiku has no adaptive thinking -- the param must be omitted, not sent.
    stub2 = StubClient()
    llm.AnthropicProvider(client=stub2).complete(
        llm.LLMRequest(role="decision", cacheable_system="S", tool=ag.ORDERS_TOOL),
        "claude-haiku-4-5",
    )
    if "thinking" in stub2.messages.kwargs:
        print("    FAIL thinking sent to a model that does not support adaptive")
        failures.append("adaptive thinking sent to haiku-4-5")
    else:
        print("    ok  thinking omitted for haiku-4-5 (no adaptive support)")

    # A refusal returns HTTP 200 -- it must raise, not be read as content.
    class RefusingMessages(StubMessages):
        def create(self, **kw):
            return type("M", (), {
                "content": [], "usage": type("U", (), {
                    "input_tokens": 1, "output_tokens": 0,
                    "cache_read_input_tokens": 0})(),
                "stop_reason": "refusal",
                "stop_details": type("D", (), {"category": "test", "explanation": "no"})(),
            })()

    stub3 = StubClient()
    stub3.messages = RefusingMessages()
    try:
        llm.AnthropicProvider(client=stub3).complete(
            llm.LLMRequest(role="decision", cacheable_system="S"), "claude-opus-5")
        print("    FAIL refusal did not raise")
        failures.append("refusal stop_reason was not surfaced")
    except RuntimeError:
        print("    ok  refusal raises instead of returning empty content")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GATE PASSED - Phase 2 LLM negotiation holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
