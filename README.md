# AI Diplomacy — Theory of Mind engineering

Seven AI powers negotiate, form alliances, and betray each other. Each keeps an
explicit, inspectable model of what it believes the others intend — updated on what
they *say* and, separately, on what they actually *do*.

The point is not an AI that plays Diplomacy well. It is a demonstration that belief
modelling can be built as **engineering rather than prompting**: recursive belief
state, calibrated trust, and mechanically enforced information isolation, with
falsifiable evidence that the belief layer does something.

> **Status: Phase 3 of 5.** The engine, belief layer, LLM agents and replay viewer
> work end to end. Every gate is green in CI. What is *not* done is the part that
> matters most — the ablation and calibration metrics (Phase 4). See
> [ARCHITECTURE.md](ARCHITECTURE.md) for the plan and every decision behind it.

---

## The idea in one screen

A power's trust in another is a **Beta posterior over promise-keeping**, not a score
an LLM makes up. Every message carries a structured commitment; after adjudication
the engine diffs what was promised against what was ordered, and that diff is the
evidence the posterior updates on. Betrayals weigh double, because Diplomacy trust is
asymmetric — alliances take many turns to build and one stab to destroy.

Two properties are enforced mechanically rather than by instruction:

**Information isolation.** A belief store belongs to exactly one power and has no
method that could admit another power's private channel. A second gate re-scans every
assembled prompt and fails closed. A leak here would not merely look bad — it would
invalidate every metric downstream while still producing plausible numbers.

**Generator/Evaluator separation.** The negotiator drafts from its own goals and is
allowed to be self-serving. A structurally separate evaluator scores incoming
messages and sees *only* the counterpart's words and public order record — never its
own side's plans. A confident framing cannot talk it into trusting an ally.

Both are asserted by fixtures that must *fail*: planted leaks, a planted secret the
evaluator must not see. A gate that has only ever seen clean input proves nothing.

---

## Try it

```bash
python -m venv .venv && .venv/bin/pip install diplomacy jsonschema anthropic

python run_tests.py                     # all five gates, no API key needed
node viewer/test-viewer.mjs             # viewer data contract

python -c "from diplomacy_tom.runner import run_game; \
           from diplomacy_tom import turn_log as tl; \
           tl.save(run_game(seed=1901, max_phases=14, use_llm=True), \
                   'viewer/data/sample-game.json')"

python -m http.server -d viewer 8000    # then open http://localhost:8000
```

That runs on a deterministic mock provider — no API key, no network, no cost. To use
real models, set `ANTHROPIC_API_KEY` (or `OPENROUTER_API_KEY`) and pass a routing
preset:

```python
run_game(seed=1901, use_llm=True, routing="cheap", provider=AnthropicProvider())
```

---

## How it fits together

```text
engine.py    deterministic boundary around the `diplomacy` adjudicator
belief.py    power-indexed belief store; Beta trust; the D4 injection seam
isolation.py context-assembly gate — fails closed on a leak
agents.py    Negotiator / BeliefEvaluator / OrderDecider (the G/E split)
llm.py       provider abstraction, model routing, cost accounting, record/replay
runner.py    the turn pipeline; emits one turn log per game
viewer/      static replay viewer — board, trust network, transcript, inspector
```

**The turn log is the product.** The eval harness and the viewer are two consumers of
one artifact, not two systems. It embeds the adjudicator's own saved-game format
verbatim rather than translating it, so there is no layer to carry bugs between what
the engine resolved and what was logged.

Everything is seeded and replayable. LLM calls are recorded and replayed by prompt
hash, which is what makes the Phase 4 ablation possible at all: both arms must run on
identical conditions, and a changed prompt is a loud miss rather than a silently
wrong answer.

---

## Engineering notes worth reading

The interesting parts of this repo are the mistakes it caught. Full write-ups in
[ARCHITECTURE.md](ARCHITECTURE.md) §8–12:

- **F3** — the adjudicator's legal-move enumeration is order-nondeterministic *across
  processes*. The naive determinism check passes, because two runs inside one process
  agree. Unfixed, the two ablation arms would not have been playing the same game,
  and it would have surfaced as unreproducible results months later.
- **F7** — the isolation gate flagged a power's *own* message as someone else's leak
  when two powers sent identical text. A gate that cries wolf gets switched off,
  which is worse than the leaks it prevents.
- **F8** — the first mock returned schema-valid but *illegal* orders, so every LLM
  decision silently fell back to holding. The ablation was untestable while appearing
  to pass. A test double that cannot fail the way production fails is not testing
  anything.

---

## Licence

Deliberately split — see [NOTICE](NOTICE).

| Path | Licence | Why |
| --- | --- | --- |
| `diplomacy_tom/`, `tests/`, `schemas/` | AGPL-3.0-or-later | imports `diplomacy`, which is AGPL — an inherited obligation |
| `viewer/` | MIT | reads turn-log JSON only; imports no engine code |

The boundary is exactly the turn-log schema. The viewer draws its own schematic board
rather than bundling the GPL jDip map, which is what keeps it permissive.
