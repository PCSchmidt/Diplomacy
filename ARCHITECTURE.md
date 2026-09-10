# AI Diplomacy — Architecture & Build Plan
## v0.2 — decisions locked

Supersedes the open questions in `diplomacy-tom-scope.md` §10. That document remains
the statement of intent; this one is the build contract.

---

## 0. What this project is optimizing for

Not "an AI that plays Diplomacy well." Not even "a Theory of Mind demo." It is
optimizing for **defensible evidence that the belief layer does something**, packaged
so a hiring manager grasps it in 90 seconds.

Every scoping decision below resolves in favor of that. Where map fidelity, unit
animation, or power count compete with the eval harness, they lose.

---

## 1. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Adjudicator | `diplomacy` PyPI lib (1.1.2), standard map | **Verified — see §8.** Zero rules-engine risk. Existing SVG map assets. Same engine lineage as Meta's CICERO. Buys back ~1 week for belief modeling. |
| D2 | Power count | 4 LLM powers + 3 scripted bots | Bounds token cost and pairwise message blowup while keeping the standard map. |
| D3 | Demo delivery | Replay-first, fully static | Site is Astro `output: 'static'` on GitHub Pages — cannot host Python. Free, no API keys, never down. |
| D4 | Ablation | Hard v1 requirement | The answer to "how do you know it does anything?" Constrains architecture from day one. |
| D5 | Portfolio restructure | In scope, final phase | Shipping as card #14 of 14 converts nobody. |
| D6 | Meridian relationship | Pattern, not code | See §2. |

---

## 2. Correcting the Meridian framing

`diplomacy-tom-scope.md` §4 describes "extending Meridian's memory schema." **Meridian
has no importable runtime** — it is 53 bash scripts, markdown, YAML gate graphs, and
JSONL memory files. Its single `.py` file is a test fixture. There is nothing to
import into a Python game engine.

The claim is therefore reframed, not retreated from:

> The same invariant — *a generator must not be able to talk its own evaluator into
> approving its work* — is implemented twice, in two languages, against two unrelated
> failure modes: an agent grading its own code, and an agent grading its own ally.

This is a stronger interview position than code reuse, because it is an
architecture-level claim rather than a packaging one. What carries over is the
*design*: schema-validated tiered memory, structural generator/evaluator isolation,
and gates that fail closed. What is written fresh is all of the Python.

**Rule:** no README, portfolio card, or commit message may imply Diplomacy imports
Meridian.

---

## 3. The turn log is the product

D3 and D4 converge on one artifact. The eval harness and the demo viewer are two
consumers of the same file, not two systems.

```
Game runner  ──emits──>  turn log (JSON)  ──consumed by──>  eval harness (metrics)
                                          └─────────────>  static viewer (demo)
```

Consequences, all binding:

- The log is **complete and self-describing**. A game must be fully reconstructible —
  board, messages, belief snapshots, orders — from the log alone, with no access to
  the runner.
- Runs are **seeded and deterministic** given fixed model outputs. LLM calls are
  recorded and replayable so both ablation arms run on identical conditions.
- The log schema is **versioned and validated on write**, Meridian-style. A schema
  break is a gate failure, not a runtime surprise.

Write this schema in Phase 0, before anything depends on it.

---

## 4. Belief store

Composite key from scope doc §4.3, retained as-is:

```
belief:{observer_power}:{subject_power}:{tier}
```

Three tiers — semantic (rules/geography shared, treaty beliefs power-scoped),
episodic (strictly what `observer` has seen of `subject`), corrections (dyadic
stated-intent-vs-actual-orders log).

**Isolation is the experiment.** A leak does not merely look bad; it invalidates every
metric downstream. So it is enforced mechanically, not by convention: the
context-assembly gate scans each outgoing prompt and hard-fails if any other power's
private content appears. That gate has its own test suite, and a deliberate-leak
fixture that must fail.

**Injection seam (required by D4):** the belief layer is resolved through an interface
with at least two implementations — the real Bayesian store, and a stub returning
static or random trust. Nothing in the negotiation or decision layer may reference the
concrete implementation.

---

## 5. Cost architecture

Betrayal-prediction accuracy needs tens of games, not three. Naive implementation
does not survive that. Designed in from the start, not bolted on:

- **Prompt caching** against the stable prefix — rules, map, accumulated game history.
  This shapes how prompts are *structured*, so it cannot be retrofitted cheaply.
  Note this interacts with F3 below: an unsorted legal-move list churns the prompt
  prefix on every run and silently destroys the cache hit rate.
- **Model routing** — cheapest viable model for scripted powers and filler; the strong
  model reserved for live negotiators and belief evaluators.
- **Belief math in Python**, never delegated to the LLM. Bayesian updates and trust
  scoring are deterministic code. (Already correct in scope doc §7.)
- **Token accounting per game**, logged. Cost-per-game is itself a portfolio metric —
  it demonstrates the cost-awareness the target role screens for.

---

## 6. Phases

Each ends in something showable.

### Phase 0 — De-risk
- Smoke-test `diplomacy` 1.1.2: drive a full game to completion **programmatically**
  on Python 3.14. Install resolving is not sufficient evidence. *If this fails, D1
  reopens and the mini-map fallback is live.*
- Turn-log + belief schema, versioned, with validators.
- Power-indexed belief store in isolation: 3 powers, synthetic messages, no LLM.
- Isolation gate + deliberate-leak fixture.

**Gate:** leak fixture fails as designed; schema validates; a real game runs headless.

### Phase 1 — Deterministic spine
- Full game loop, scripted bots only, no LLM.
- Complete replay JSON emitted and re-validated.
- *Showable: "I built a testable engine."*

### Phase 2 — Agents
- LLM negotiation layer; structurally separate belief evaluator.
- Structured/tool-call output for machine-parseable orders; orders-valid gate re-prompts.
- One full game, end to end.
- *Showable: the demo exists.*

### Phase 3 — Viewer
- Static React/D3 replay viewer: board, trust network, transcript, mental-model inspector.
- Deployed to Pages, scrubbing recorded games.
- *Showable: the demo is visitable.*

### Phase 4 — Evidence ← **the phase that matters**
- Batch runner, N games, both ablation arms on identical seeds.
- Belief calibration, betrayal-prediction accuracy, alliance stability.
- Cost-per-game table.
- *Showable: Tier 1. This is the phase that gets you hired.*

### Phase 5 — Funnel
- Restructure `projects.astro`: one hero (Diplomacy, live embedded artifact), three
  supporting, remainder collapsed into an index.
- Currently all 13 projects are `status: 'featured'`. When everything is featured,
  nothing is.

---

## 7. Standing risks

| Risk | Mitigation |
|---|---|
| ~~`diplomacy` 1.1.2 may not drive cleanly on 3.14~~ | **Retired — gate passed, see §8.** Mini-map fallback stood down. |
| Enumeration-order nondeterminism reintroduced by a new caller | Single choke-point helper + cross-process fingerprint test in CI (F3). |
| Belief layer is theater | D4 ablation. Non-negotiable. |
| Token cost blocks statistical n | §5, designed in from Phase 0. |
| Isolation leak invalidates results | Mechanical gate + leak fixture, own test suite. |
| Ships as card #14 of 14 | Phase 5 is in scope, not optional. |


---

## 8. Phase 0 gate result — D1 verified

Run `scripts/smoke_test.py`. Status: **PASSED**.

Evidence: `diplomacy` 1.1.2 installs on Python 3.14 (builds from source — no 3.14
wheel is published), drives a full game to completion headlessly, exercises Movement,
Retreat and Adjustment phases, and terminates on the correct victory condition (an
18-centre solo). Phase history carries both orders and state, so it is a sufficient
replay substrate. **The mini-map fallback is stood down.**

Three findings that constrain the build:

### F1 — Save/load is faithful except for one volatile field
`to_saved_game_format` → `from_saved_game_format` round-trips every game field
exactly. The sole difference is a wall-clock `timestamp` on the in-progress phase,
stamped at serialization time rather than being game data.

**Constraint:** the turn-log schema (§3) must not include or depend on that field.
Comparison and replay-verification code normalizes it away.

### F2 — Adjudication is deterministic
Identical orders produce identical outcomes. The engine itself is a sound basis for
the D4 ablation.

### F3 — `get_all_possible_orders()` is order-nondeterministic across processes ⚠️
The highest-value finding, and it would have been expensive to discover late.

The API returns set-derived lists. Their *contents* are identical every run; their
*sequence* varies with `PYTHONHASHSEED`, so it changes between processes. Two runs of
the same seed in one process agree — which is exactly why a naive determinism check
passes and hides the bug. Across processes the same seed diverged from an Austrian
solo in 184 phases to a no-winner game at the 200-phase cap.

Left unfixed this would have:
- **invalidated D4** — ablation arms run as separate processes, so "belief layer on"
  and "belief layer off" would not have been running the same game;
- **silently degraded prompt caching (§5)** — a reshuffled legal-move list churns the
  prompt prefix on every run;
- surfaced only as unreproducible results after the eval harness existed, i.e. at the
  point where it is most expensive to diagnose.

**Constraint:** every consumer goes through one sorting choke-point
(`possible_orders()` in `scripts/smoke_test.py`, to be promoted into the engine
module). Never call `game.get_all_possible_orders()` directly. Iteration over powers
and orderable locations is likewise sorted.

Verified fixed: identical cross-process fingerprint `0f9e0213…` under
`PYTHONHASHSEED` of 0, 1, and 12345. That fingerprint check belongs in CI — it is the
regression test for the whole determinism property.
