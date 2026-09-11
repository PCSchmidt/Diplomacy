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
| D2 | Power count | ~~4 LLM + 3 scripted~~ **7 LLM powers (§18)** | Bounds token cost and pairwise message blowup while keeping the standard map. |
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

Write this schema in Phase 0, before anything depends on it. **Done — see §9.**

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
- [x] `diplomacy` smoke test (§8)
- [x] Turn-log schema + validator (§9)
- [x] Belief schema, power-indexed store, 3-power synthetic prototype (§10)
- [x] Isolation gate + deliberate-leak fixture (§10)
- [x] Promote `possible_orders()` into engine module; fingerprint check into CI (§11)

**Phase 0 complete.**

- Smoke-test `diplomacy` 1.1.2: drive a full game to completion **programmatically**
  on Python 3.14. Install resolving is not sufficient evidence. *If this fails, D1
  reopens and the mini-map fallback is live.*
- Turn-log + belief schema, versioned, with validators.
- Power-indexed belief store in isolation: 3 powers, synthetic messages, no LLM.
- Isolation gate + deliberate-leak fixture.

**Gate:** leak fixture fails as designed; schema validates; a real game runs headless.

### Phase 1 — Deterministic spine ✅ **complete (§11)**
- [x] Full game loop, scripted bots only, no LLM.
- [x] Complete replay JSON emitted and re-validated.

### Phase 2 — Agents
- LLM negotiation layer; structurally separate belief evaluator.
- Structured/tool-call output for machine-parseable orders; orders-valid gate re-prompts.
- One full game, end to end.
- *Showable: the demo exists.*

### Phase 3 — Viewer ✅ **complete (§13)**
- [x] Static replay viewer: board, trust network, transcript, mental-model inspector
- [x] Licence boundary established (D7)
- [ ] Deploy to Pages

### Phase 4 — Evidence ✅ **harness complete (§14)**
- [x] Batch runner, matched seeds across both arms
- [x] Calibration, betrayal lead time, alliance stability, cost per game
- [x] Metrics verified against known inputs
- [x] Run it against a real model — **done, result is negative (§15)**
- [x] Fix the ground-truth validity problem, re-run (§19)

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


---

## 9. Turn-log schema v1.0.0 — shipped

`schemas/turn_log.schema.json` (JSON Schema 2020-12), `scripts/turn_log.py`,
`scripts/test_turn_log.py`. Gate: **PASSED**.

### Design: embed, don't translate

The `diplomacy` saved-game format is embedded **verbatim** under `game`. Our layers
(`turns`, `llm_calls`) sit alongside it rather than replacing it.

Rationale: adjudication data stays canonical, so there is no translation layer to
carry bugs between what the engine resolved and what we logged; the embedded subtree
still loads via `from_saved_game_format()` (asserted by the test, check 4); and our
schema versions independently of the library's. Cost is one level of nesting.

### Two-layer verification

JSON Schema proves each piece is well-formed. It cannot express relationships
*between* pieces, so `check_alignment()` covers those separately — turn/phase
correspondence, `board_hash` matching its phase's zobrist hash, corrections citing
real messages, and modelling errors like a power holding beliefs about itself or
messaging itself. **Both must pass for a log to be trustworthy.**

Ten negative fixtures are asserted to be *rejected*, on the same principle as the
deliberate-leak fixture: a validator that has only ever seen valid input proves
nothing.

### Decisions embedded in the schema

- **`run.seed` and `run.arm` are required.** D4 is structurally impossible to run
  wrong — a log that cannot say which arm it belongs to or what seed it used will not
  validate.
- **`rules` must not contain `NO_PRESS`.** The library's default rules are
  `['NO_PRESS', 'POWER_CHOICE']`; a negotiation game must not record itself as
  no-press. `build_log()` strips it and the schema rejects it.
- **`message.stated_intent` is structured, not prose.** Without a machine-comparable
  commitment there is no ground truth for betrayal, and the whole eval collapses into
  vibes. This is the field the post-adjudication diff reads.
- **`llm_calls` records prompt hashes, responses and cache-read tokens** so runs
  replay without hitting the API, and so cost-per-game (§5) is derivable from the
  artifact rather than measured separately.
- **`invalid_order_retries`** on each decision — how often the orders-valid gate had
  to re-prompt is an agent-reliability metric worth having for free.

### F4 — zobrist_hash supersedes the ad-hoc fingerprint

The library exposes `state.zobrist_hash`: a canonical board-position identity,
verified stable across processes. `replay_fingerprint()` is built from the sequence
of these rather than the md5-of-repr improvised in §8.

Verified: identical `a876178894f6d1b7…` under `PYTHONHASHSEED` 0, 1 and 12345, and
sensitive to seed change. This is the primitive that proves two ablation arms played
the same game.

### F5 — a second volatile field
`message.time_sent` is volatile in the same way as `state.timestamp` (F1).
`normalize_volatile()` strips both, plus — under `drop_identity` — the per-instance
game ids, which differ by construction between two runs of the same seed and would
otherwise defeat arm-to-arm comparison.


---

## 10. Belief layer v1.0.0 — shipped

`schemas/belief.schema.json`, `scripts/belief.py`, `scripts/isolation.py`,
`scripts/test_belief.py`. Gate: **PASSED**.

Implements the scope doc's first next-step — the power-indexed schema prototyped in
isolation, 3 powers and synthetic messages, before the engine is built on it.

### Trust is a Beta posterior, not a scalar

`Beta(α, β)` over promise-keeping. Conjugate, so updates are exact and cheap, and
**confidence falls out of the distribution** rather than being bolted on — which the
Phase 4 calibration metric needs and a scalar would have forced us to retrofit.

- Prior `Beta(1,1)`: uniform. The honest turn-one position is no opinion.
- `confidence = 1 - 2·sd`, derived from the posterior itself rather than an arbitrary
  observation-count threshold. Uniform prior → 0.42; ten kept promises → 0.85.
- **Betrayals weigh double** (`DEFAULT_BETRAYAL_WEIGHT`). Diplomacy trust is
  asymmetric — alliances take many turns to build and one stab to destroy — and a
  symmetric model lags every betrayal it sees. Measured: after 10 kept promises, a
  weighted stab drops trust to 0.786 where an unweighted one gives 0.846.
- Mild per-phase decay toward the prior so ancient evidence stops dominating.

### Isolation is enforced twice, on purpose

**By construction:** a store belongs to exactly one observer, and `observe_message`
rejects any message that observer was not party to. There is no method that would
admit another power's private channel.

**By inspection:** `isolation.py` scans assembled prompts against a registry of
private items and their entitlement sets, then fails closed. This exists because the
first line depends on every future caller staying disciplined.

The deliberate-leak fixture is the centrepiece, and it is asserted to *fail*:

| Fixture | Result |
|---|---|
| Third-party message planted in France's context | caught |
| `enforce()` on that context | raised, failed closed |
| Same leak reformatted (whitespace + case) | caught |
| Same leak buried in a nested structure | caught |
| Germany shown its own message | correctly silent (no false positive) |
| 6 legitimate dyad contexts + 3 full-store audits | 0 false positives |

The false-positive column matters as much as the true-positive one. A gate that cries
wolf gets disabled, which is worse than the leaks it was meant to prevent — hence the
`MIN_MATCH_LENGTH` floor.

Verified end to end: England promises France support, privately tells Germany it is
taking the Channel, then stabs. France's trust in England drops 0.500 → 0.250 and its
`predicted_betrayal` rises to 0.750. **Germany's trust in England stays at 0.500** —
it observed no betrayal, and belief is relational, not global.

### The D4 seam is real, not aspirational

`BeliefStore` is a runtime-checkable Protocol with two implementations.
`make_store(arm, ...)` is the only place either class is named; nothing in the
negotiation or decision layer may reference a concrete type.

`StubBeliefStore` is deliberately inert — fixed trust, no accumulation, empty context
— but emits **the same snapshot shape**, so the rest of the system cannot tell the
arms apart structurally. Any measured difference is attributable to the belief layer
and nothing else. Verified: identical betrayal input leaves `belief_on` at 0.250 and
`belief_off` at 0.500.

### F6 — validate untrusted data, not your own invariants

A negative-fixture crash exposed a confusion worth recording. Corrupting a live
store's Beta parameters produced an opaque `ZeroDivisionError` from the derived
statistics; adding a domain guard then made corrupt state unserializable, so schema
validation could never report on it at all.

The resolution is that these are two different jobs. The class enforces its own
invariants and **fails fast and legibly** on corruption (`_check_domain`). The schema
defends against belief JSON arriving from **outside** the process — loaded from disk,
or reconstructed from a turn log — which is what `validate_export()` is for. Writing
a fixture that corrupted a live object was testing the wrong path; the realistic
threat is untrusted input, and that is what is now tested.


---

## 11. Phase 0 closed, Phase 1 shipped

`diplomacy_tom/` (package), `tests/` (four gates), `run_tests.py`,
`.github/workflows/ci.yml`. **All gates pass.**

### Layout

Code moved out of `scripts/` into a real package before more files accumulated —
the cheapest moment to do it.

```
diplomacy_tom/   engine.py  bots.py  runner.py  belief.py  isolation.py  turn_log.py
schemas/         turn_log.schema.json  belief.schema.json
tests/           test_smoke.py  test_turn_log.py  test_belief.py  test_runner.py
run_tests.py     runs all four gates
```

No `pyproject.toml`. This is a runnable project, not a distributable library, and an
editable-install step would be friction for no benefit.

### engine.py — the F3 choke-point, now permanent

Every interaction with the adjudicator goes through `engine.py`.
`get_all_possible_orders()` and `get_orderable_locations()` are wrapped and sorted;
calling either directly is now the documented mistake. `new_game()` also strips
`NO_PRESS` at the source rather than relying on `build_log()` to clean up after it.

### Phase 1 result

A 16-turn game, scripted policies, no API calls: 68 messages, 68 commitments checked
(65 kept, 3 broken), 672 belief snapshots, 112 decisions. Trust spread across dyads
reached 0.397 — the belief layer is demonstrably doing something on real game data,
not just on the synthetic fixture. Zero isolation leaks across all 7 powers for the
whole game. Log round-trips at 373 KB.

Every pipeline gate in §5 now runs each phase, including context-assembly on contexts
that Phase 1 never sends anywhere. It is cheap, and a leak introduced now should fail
now rather than the first time a real prompt is built.

### CI

Two jobs. The gate matrix runs all four gates under `PYTHONHASHSEED` 0, 1, 12345 and
random. A separate `fingerprint` job asserts the same seed yields the same game
across four different hash seeds — this is the permanent regression test for F3, and
it needs its own job because the property is cross-process and no single matrix entry
can demonstrate it. Verified locally: `05e48b916f102527…` under all four.

### ⚠ One assertion must invert in Phase 2

`test_runner.py` check 6 asserts both ablation arms play an **identical** game.
That is correct only while scripted policies ignore beliefs. Once the decision layer
reads belief state, the arms are *supposed* to diverge — that divergence is the D4
result itself. What must stay identical then is the seed and initial conditions, not
the outcome.

Flagged in the test body as well as here, because the failure mode is someone
"fixing" a legitimately failing check by forcing the arms back into agreement, which
would silently disable the ablation.


---

## 12. Phase 2 — LLM negotiation

`llm.py`, `agents.py`, extended `runner.py`, `tests/test_phase2.py`. Gate: **PASSED**
(11 checks). Runs entirely on `MockProvider` — no API key, no network, no cost — so
it works in CI.

### API shapes verified against current docs, not memory

Several patterns in my working memory were stale. Corrected here and asserted by a
stub-client test (check 11) so a shape error surfaces free rather than on a paid call:

| | Stale | Current |
|---|---|---|
| Thinking | `{type: "enabled", budget_tokens: N}` | `{type: "adaptive"}` — `budget_tokens` is a **400** on current models |
| Effort | top-level | inside `output_config` |
| Structured output | `output_format` | `output_config.format`, or strict tool use |
| Default model | assorted | `claude-opus-5` |

Pricing per MTok: Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5.

### Provider abstraction

`Provider` is the seam; nothing above `llm.py` knows which provider, or whether a
call is live, recorded, replayed or mocked.

- **`AnthropicProvider`** — official SDK. Prompt caching with an explicit breakpoint,
  adaptive thinking, strict tool use, refusal handling (`stop_reason: "refusal"`
  returns HTTP 200 and must raise rather than be read as content).
- **`OpenRouterProvider`** — raw HTTP; it has no official Python SDK, and an
  OpenAI-compatible shim is the wrong way to call Claude. Prices are **fetched from
  OpenRouter's own catalogue**, never invented — a made-up number would put fiction
  into cost-per-game.
- **`ReplayProvider` / `RecordingProvider`** — determinism. Recording is a
  first-class provider, not a test hack: it is what makes an LLM game reproducible,
  and therefore what makes D4 and CI possible at all. Lookup is by prompt hash, so a
  changed prompt is a loud miss rather than a silently wrong answer.
- **`MockProvider`** — deterministic synthetic responses derived from the prompt hash.

Routing presets: `quality` (Opus 5 throughout), `balanced`, `cheap`. **Every preset
keeps the strongest model on the belief evaluator** — it is the component under test
in D4, so degrading it would confound the result being measured.

### Caching is designed in, not retrofitted

`LLMRequest` separates `cacheable_system` from `system` so breakpoint placement is
explicit rather than accidental. Check 8 asserts each role's prefix is byte-identical
across calls and contains no volatile tokens — a year, a seed, a phase name in the
prefix would silently drop the hit rate to zero.

### The separation test

The integrity property is asserted the way the leak fixture is — by planting content
that must not appear. A message the observer **sent** is planted, then:

- the Negotiator's context contains it (correct — it is that power's own reasoning);
- `evaluator_context()` does **not**;
- the **assembled evaluator prompt** does not either (context shape is one thing;
  what reaches the model is what matters).

### F7 — the isolation gate's false-positive class

Wiring the mock surfaced a real defect. Two dyads sent byte-identical bodies, and the
scan flagged a power's *own* legitimate message as someone else's leak.

This is not a mock artifact: real powers send identical short messages ("Agreed.",
"I will hold in Munich"). Left alone it would have produced steady false alarms —
and by the project's own reasoning, a gate that cries wolf gets switched off, which
is worse than the leaks it prevents.

Fixed by checking whether the matched text is attributable to something the viewer
**is** entitled to before flagging. The residual blind spot is documented in the
code: a genuine leak whose text exactly duplicates an entitled message is invisible.
That trade is accepted deliberately. Both directions are now fixtures.

### F8 — a mock that never exercises the thing under test

The first mock produced schema-valid but *illegal* orders, so all 16 LLM decisions
failed the orders-valid gate and fell back to holding. The decision layer was never
exercised, and both ablation arms played identical games — **D4 was untestable in
CI while appearing to pass.**

Fixed with `mock_hint`: a structured echo of data already in the prompt, read only by
`MockProvider`, excluded from `cache_key` so it cannot affect hashing or replay. The
mock now returns legal orders biased by belief state. The arms diverge (check 9), and
`belief_off` stays inert at a single trust value.

The general lesson is worth keeping: a test double that cannot fail the way
production fails is not testing anything.


---

## 13. Phase 3 — replay viewer, and a licensing correction

`viewer/`, `LICENSE`, `NOTICE`, `README.md`. Gate: **PASSED** (7 checks, `node
viewer/test-viewer.mjs`, wired into `run_tests.py`).

### D7 — the licence constraint I missed at D1

**`diplomacy` is AGPL-3.0-or-later, and its bundled `standard.svg` is GPL (jDip).**
D1 was decided on rules-engine risk and CICERO lineage without checking the licence.
That was an omission, and it constrains what the finished project can be.

The repo is private and unlicensed today, so nothing has triggered — AGPL attaches on
distribution. Resolved before first publication:

| Path | Licence | Why |
| --- | --- | --- |
| `diplomacy_tom/`, `tests/`, `schemas/` | AGPL-3.0-or-later | imports `diplomacy` — inherited, not chosen |
| `viewer/` | MIT | consumes turn-log JSON only |

The viewer is separable because **program output is not a derivative of the program**.
The boundary is exactly the turn-log schema, and two things would collapse it:
importing engine code from `viewer/`, or bundling the GPL jDip map. `NOTICE` states
both. The viewer therefore draws its own schematic board.

### Viewer design

Static, no build step, no framework — GitHub Pages serves it as-is. Four panels on one
phase scrubber: board, directional trust network, transcript, mental-model inspector.

Two choices worth naming. **Trust edges are directional and bowed** — A's trust in B
is not B's trust in A, and drawing one line per pair would have hidden half the data.
And the transcript shows **prediction before verdict**: the evaluator's truthfulness
score sits next to each message, with the kept/broken outcome resolved by looking
*ahead* to the correction that cites it. That ordering is the eval story in miniature.

### F9 — hand-authored data needs a canonical diff

The province coordinates are authored for this project rather than extracted from the
GPL map. Testing them against one sample game passed while three defects survived,
because that game never visited the affected provinces:

- `NRG` should be `NWG` (Norwegian Sea) — a unit there rendered invisibly;
- `SWI` (Switzerland) missing entirely;
- **`ARM` wrongly marked a supply centre** — 35 instead of the standard 34.

Fixed, and the test now diffs the *whole* province and supply-centre set against
`viewer/data/provinces.json`, emitted by the engine. Checking only what one run
touched is not coverage — it is a sample.

### Still unverified

Everything runs on `MockProvider`. **No live API call has been made**, so prompt
quality is unvalidated: whether the evaluator produces calibrated scores rather than
saying 0.7 to everything is unknown. The 59% scorecard in the sample is mock noise and
means nothing. That validation is the cheapest remaining de-risking step and should
precede Phase 4.


---

## 14. Phase 4 — the eval harness (and why it has no results yet)

`evaluation.py`, `batch.py`, `tests/test_eval.py`, `.github/workflows/pages.yml`.
Gate: **PASSED** (8 checks). Seven gates now run in CI.

### Metrics, and why these ones

| Metric | Question | Chance level |
| --- | --- | --- |
| **Evaluator AUC** | Ranked by predicted truthfulness, do kept promises sort above broken ones? | 0.5 |
| Evaluator Brier | Are the probabilities themselves right, not just ordered? | 0.25 |
| Calibration bins | Does "0.7" mean 70%, or is it said to everything? | — |
| **Betrayal lead** | Did belief move *before* the stab, or only record it after? | 0 |
| Alliance span | How long do high-trust dyads survive? | — |
| Cost per game | What does the evidence cost to produce? | — |

AUC rather than accuracy: accuracy depends on threshold and class balance, and with
promises mostly kept it would look impressive while meaning nothing. Lead time is the
metric that separates a belief model from a scoreboard — a system that updates only
after the betrayal scores 0, and that is precisely the failure worth catching.

Metrics are verified against **known inputs**, not real games: a perfect evaluator
must score 1.0, one that says 0.5 to everything must score 0.5, and a system that
never anticipates must score lead 0. A harness that merely produces a number from a
real game tells you nothing about whether the number is right.

### Matched seeds

The batch runs both arms on identical seeds and pairs them. Game outcomes vary
enormously between seeds, so unpaired comparison would drown the belief layer's
effect in seed noise long before N grew large enough to matter.

### F10 — a log that lies about its own provenance

The sample game recorded `models: claude-opus-5` while having been produced entirely
by `MockProvider`. Nothing in the artifact said so. That is how fabricated evidence
gets made — not by intent, but by a plausible-looking file outliving the context that
explains it.

Fixed at three levels: `provider` is now **required** by the schema (v1.1.0), the
runner records the real provider, and `Report.is_evidence` is false whenever either
arm is synthetic. The markdown report then leads with a refusal rather than a table:

> **These numbers are not evidence.** At least one arm was produced by a synthetic
> provider, whose responses are uncorrelated with the outcomes they are scored
> against.

One synthetic arm poisons the whole comparison, and that is asserted as a fixture.

### Status: no findings

**The harness has produced no evidence, because no live model has run.** There are no
API credentials on this machine. Every number currently obtainable is mock noise, and
the code says so rather than presenting it.

To produce real results:

```bash
export ANTHROPIC_API_KEY=...
python -m diplomacy_tom.batch --games 20 --provider anthropic --routing cheap        --out runs/ --report reports/ablation.md
```

### Pages

`.github/workflows/pages.yml` publishes **only `viewer/`**, and asserts the licence
boundary before deploying: no engine imports, no SVG assets, no jDip copyright
header. The first version of that check flagged `board.js` for containing the word
"jDip" — in a comment explaining it deliberately does *not* use that map. Narrowed to
match the asset rather than the word, for the same reason as F7: a check loose enough
to flag its own documentation is a check people learn to ignore. Both directions are
tested with a planted fixture.


---

## 15. First live ablation — a negative result, and why it is the useful kind

6 seeds x 2 arms, 8 phases, `z-ai/glm-5.3-flash` via OpenRouter. 12/12 games
completed, $0.07/game. Report: `reports/ablation.md`, logs in `runs/glm/`.

### The headline

**Evaluator AUC 0.470, 95% CI [0.321, 0.616].** 0.5 sits comfortably inside that
interval, so the honest statement is **no detectable signal in either direction** —
not "the evaluator is inverted". With 89 resolved messages and only 16 negatives this
run is badly underpowered, and the interval says so.

Betrayal anticipation is similarly empty: 1 of 16 betrayals had any lead, mean lead
0.19 phases. On these numbers the belief layer is a scoreboard, not a predictor.

### But the measurement is broken, so the model is not what was tested

Three facts, in order of how much they matter:

| | |
|---|---|
| Base rate of "kept" | **82%** (73/89) |
| Pledged province **not occupied** by the promiser | **77 of 89** |
| Contested subset (promiser had a unit there) | **12 cases, 12 kept, AUC undefined** |

Almost every commitment was of the form *"I will not move on X"* where X was
somewhere the promiser had no unit and no intention of going. **A promise not to
enter the English Channel when you have no fleet that can reach it is kept by
default.** The label is satisfied trivially, carries no information, and scoring a
predictor against it measures noise.

The contested subset — the only place where "kept" is informative — contains twelve
cases and zero violations, so AUC is undefined rather than bad.

**Conclusion: this run does not show the belief layer fails. It shows the ground
truth is invalid.** Those are very different findings, and reporting the first when
the second is true would have been the most damaging thing this project could
publish: a confident number resting on a label that means nothing.

### A confound worth naming separately

`belief_on` resolved 89 messages, `belief_off` only 28. The arms produced very
different volumes of negotiation traffic, so even a clean metric would not be
comparing like with like. Matched seeds control the *board*, not the amount of talk.

### What has to change before re-running

1. **Score only falsifiable commitments.** A promise counts as evidence only when the
   promiser could actually have broken it — a unit in or adjacent to the pledged
   province. Everything else is excluded from the metric, not counted as "kept".
2. **Elicit checkable commitments.** The negotiator prompt should require promises
   about provinces the speaker can actually reach this turn.
3. **Longer games.** Eight phases is not enough for trust to develop or for a stab to
   become attractive.
4. **More games.** The CI above is the argument: n=89 with 16 negatives cannot resolve
   an effect of any plausible size. At $0.07/game, 50 seeds per arm is affordable.
5. **Control the traffic confound**, or report per-message rather than per-game.

### Why this is recorded rather than quietly fixed

The eval harness did its job. It was built to answer "does the belief layer do
anything?", and the first thing it did was refuse to let a meaningless positive
through — the calibration table exposed an 82% base rate and the contested-subset
check found twelve unanimous cases. A harness that had only reported AUC would have
printed 0.470 and looked like a modest failure of the model, and the real defect
would have survived into the next run.


---

## 16. Model selection: why the cheap model was not cheaper

A worked example of a measurement trap, kept in full because the wrong answer was
defensible at every step.

### The claim under test

`z-ai/glm-5.3-flash` costs $0.15/$0.50 per MTok against `claude-haiku-4.5` at
$1.00/$5.00 — nominally **10x cheaper**. Running tens of games makes that difference
decisive, so it was adopted for the first live batch.

### What went wrong

A third of LLM "decisions" in that batch were not decisions. The model wrote prose —
*"Let me analyze the situation..."* — until it hit `max_tokens`, and never emitted the
tool call. The runner substituted hold orders.

My first diagnosis was **"the cheap model cannot do forced tool calls."** That was
wrong, and reached badly. I ran an A/B test where the improved prompt *replaced* the
whole prefix, including the phase guidance added earlier — two changes at once. It
scored worse, I attributed the failure to the model, and stopped.

Prepending the output contract to the existing prompt instead gave **8/8** on the
position I happened to test. The verbosity was mine: `DECIDER_PREFIX` opened with
*"Weigh board position against what you believe other powers will do"* and mentioned
the tool only at the end. **The model did exactly what it was told.**

### But one position is not a measurement

Re-run across four positions at different game stages:

| Model | decisions | evaluations | $/success | s/success |
| --- | --- | --- | --- | --- |
| glm-5.3-flash | **5/12** | **2/8** | $0.00244 | 29.1 |
| claude-haiku-4.5 | **11/12** | **8/8** | $0.00321 | 2.6 |

The 8/8 was position-specific luck. glm fails on ~60% of decisions and ~75% of
evaluations regardless of prompt.

### The number that actually decides it

Cost per **successful** call, not per call. At one point glm measured *more*
expensive than Haiku ($0.0033 vs $0.0029), because a failure burns the full token
budget and then triggers a retry. Even at its best it saves ~25% while being 11x
slower — and headline token prices mislead by an order of magnitude whenever
reliability differs.

### Reliability here is correctness, not cost

A failed tool call means that power **passes its turn**. A game where powers pass
60% of the time is not Diplomacy, and an ablation measured on it is meaningless. The
bar is therefore "high enough not to distort the experiment", which no amount of
saving can substitute for.

**Decision: `anthropic/claude-haiku-4.5` for all three roles, routed through
OpenRouter** so one key serves everything. `glm-unreliable` is retained as a preset
purely so the finding stays reproducible.

### F11 — the failure was invisible because the fallbacks were plausible

Three separate silent fallbacks had to be removed before any of this was measurable:

1. `OrderDecider` returned `{"orders": []}` → runner substituted holds.
2. The `no_decision` fix checked `data is None`, but the model returns `{}` — not
   None — so the guard never fired. **A fix that did not work, reported as working.**
3. `BeliefEvaluator` substituted `predicted_truthfulness 0.5 / confidence 0.0`.
   In the last batch that was **304 of 642 evaluations — 47% exactly 0.500**.

Point 3 invalidates §15's AUC 0.470 for a second, independent reason: roughly half
the inputs to that metric were constants, which dilute toward chance by construction.
The §15 ground-truth problem and this are separate defects that happened to point the
same direction.

All three are the same failure family as F8: **a failure quietly becoming a
believable value.** Every one survived a full batch and a write-up precisely because
the substituted values looked reasonable in the log. Nothing now substitutes a
plausible default — an unscored message carries no `evaluation` field at all, and the
eval harness excludes it.

### The transferable lesson

Benchmark on **cost per successful call**, on **several inputs**, with **failures
that announce themselves**. Any of those three missing produces a confident, cheap,
wrong answer — and this project produced exactly that, twice, before measuring
properly.


---

## 17. Both §15 confounds fixed, verified on live games

### Reliability (the F11 family)

Routing to `claude-haiku-4.5` and removing every silent fallback, verified end to end
on live games rather than isolated calls:

| | first batch | now |
| --- | --- | --- |
| `no_decision` rate | ~34% | **0/16, both arms** |
| Evaluations that were real model output | 53% | **47/47 and 48/48** |
| Message volume, belief_on vs belief_off | 89 vs 28 | **47 vs 48** |

The third row settles a question §15 left open. The volume asymmetry was flagged
there as a possible confound — perhaps the belief layer caused more negotiation. It
was **an artifact of the unreliable model**, and disappeared entirely once tool calls
stopped failing. Worth noting because the plausible causal story was wrong.

### Ground truth (the §15 validity problem)

A commitment now records, **at the moment it is made**, whether the speaker could
legally have moved into the pledged province — `engine.can_reach()`. The eval scores
only those, and reports the rest as excluded rather than silently counting them kept.

`can_reach` deliberately consults the legal-order list rather than raw adjacency: a
fleet beside an inland province is adjacent but cannot enter it, and counting that as
an opportunity would reintroduce the same false positive in subtler form.

The negotiator prompt now also asks for testable pledges — *"a promise nobody could
break is not a promise"*.

Measured on a live game:

| | first batch | now |
| --- | --- | --- |
| Base rate "kept" | 82% | **42%** (10 kept / 14 broken) |
| Unfalsifiable | ~87%, counted as kept | 50%, **excluded** |
| Contested-subset classes | 12 kept, 0 broken (AUC undefined) | balanced |

Near-balanced classes are what make AUC meaningful at all. The first batch could not
have produced a usable number no matter how good the belief layer was.

### What this does not settle

The ablation has not been re-run. §15's negative result stands as withdrawn rather
than reversed — its two known causes are fixed, but nothing yet shows the belief
layer works. Reliability is now ~$0.60/game against glm's $0.07, so a re-run costs
roughly 8x more per seed; that is the price of a game where powers actually play
their turns.


---

## 18. D2 revised: all seven powers are LLM-driven

### What the reference library actually does

Worth recording, because it shows our scripted-bot layer was a third thing with no
precedent. `diplomacy` ships reduced-player variants using an `UNPLAYED` directive,
and they **remove** powers rather than automating them:

```python
Game(map_name="standard_france_austria").powers   # -> ['AUSTRIA', 'FRANCE'] only
get_centers("ENGLAND")                            # -> AttributeError; not a power
```

The removed powers' home centres become unowned and capturable. Only 2-player
standard variants ship; **there is no official 4-power variant**, so our split had no
precedent to follow.

| Approach | Powers in game | Removed powers' centres |
| --- | --- | --- |
| Library variant (`UNPLAYED`) | only the played ones | neutral, capturable |
| Research standard (CICERO) | all 7, all agent-controlled | n/a |
| ~~Ours until now~~ | all 7, 3 scripted | owned and defended |

### Why D2 was wrong

The original justification was cost, and the arithmetic was wrong. It scaled with
**dyads** — 42 vs 12, so 3.5x. But the negotiator is capped at 3 messages per phase,
so evaluator calls scale with **powers x cap**, not dyads:

| LLM powers | calls/phase | $/game (8ph) | 24-game ablation |
| --- | --- | --- | --- |
| 4 | 20 | $0.60 | $15 |
| 7 | 35 | **$1.00 measured** | **$25** |

1.75x, not 3.5x. Ten dollars on the definitive run.

### The distortion it was causing

Ranking all 35 four-power subsets by internal adjacency put the chosen set
{Austria, England, France, Germany} at **rank 16 of 35**. Austria's three real
rivals — Italy, Russia, Turkey — were all scripted, so it modelled only powers it
never contested, while its actual threats were unmodellable. Belief modelling between
powers that never contest territory is close to vacuous, and that is precisely the
signal the ablation is trying to measure.

Choosing a better subset would have reduced this. Using all seven eliminates it, and
removes the subset-selection question entirely.

### Verified live

7 powers, 3 phases: **42/42 belief dyads exercised**, 21 decisions with 0
non-decisions, 62 messages all scored by real calls, $1.00/game at 8 phases — within
6% of estimate.

`scripted_powers` is now empty. `bots.py` is retained: the Phase 1 deterministic
spine still uses it, and it remains the hold-order fallback when a model fails to
decide.


---

## 19. The definitive ablation — a clean, well-powered negative result

12 seeds x 2 arms, 8 phases, **all 7 powers LLM-driven**, `claude-haiku-4.5` via
OpenRouter. 22 of 24 games completed; 2 failed and their partners were dropped to
preserve seed pairing, leaving **10 matched pairs**. ~$25.
Report: `reports/ablation-7power.md`, logs in `runs/haiku7/`.

This is the first run where the measurement itself is sound. §15's result is
superseded, not merely withdrawn.

### The headline: the evaluator has no discriminative signal

| | first run (broken) | this run |
| --- | --- | --- |
| n (falsifiable, scored) | 89 | **747** |
| Evaluator AUC | 0.470 | **0.4993** |
| 95% CI | [0.321, 0.616] | **[0.458, 0.541]** |
| CI width | 0.295 | **0.083** |

0.5 sits almost exactly at the centre of a tight interval. This is no longer
"underpowered, cannot tell" — it rules out any effect larger than about ±0.04.
**Ranked by the evaluator's predicted truthfulness, kept promises do not sort above
broken ones.**

### Calibration shows *why*, and it is not subtle

| predicted band | n | said | actually kept | gap |
| --- | --- | --- | --- | --- |
| 0.0–0.2 | 60 | 0.148 | **0.800** | **+0.652** |
| 0.2–0.4 | 160 | 0.294 | 0.619 | +0.324 |
| 0.4–0.6 | 42 | 0.486 | 0.619 | +0.133 |
| 0.6–0.8 | 345 | 0.715 | 0.626 | −0.088 |
| 0.8–1.0 | 140 | 0.870 | 0.707 | −0.162 |

The evaluator's **confident predictions are backwards**. When it says a promise has a
15% chance of being kept, it is kept **80%** of the time. The base rate is 0.65, and
a constant 0.65 predictor scores AUC 0.500 by definition — which is, within noise,
exactly what the evaluator achieves.

### Metrics that look favourable but are not evidence

`belief_on` shows 54 anticipated betrayals (mean lead 0.75 phases) and 26 alliance
spans; `belief_off` shows **0 and 0**. That comparison is vacuous: the stub holds
trust constant at 0.5 by construction, so it *cannot* register a lead or a span. The
contrast shows the belief layer moves, not that it moves *correctly* — and the AUC
says it does not. Reporting these as a win would be exactly the kind of
meaningless-positive the harness was built to refuse.

### What this does and does not establish

**Establishes:** with this prompt, this model and this commitment-extraction, the
belief layer produces trust scores uncorrelated with whether promises are kept. The
ToM claim is **not supported**.

**Does not establish:** that the approach cannot work. Untested alternatives include
a stronger evaluator model (haiku-4.5 is the cheapest tier), richer evidence in the
evaluator's context (it currently sees message text and order history, not board
pressure), longer games (8 phases is short for reputations to form), and better
commitment extraction (58% are still discarded as unfalsifiable).

The honest one-line summary: **the machinery is sound and the result is negative.**

### F12 — `strict` is not enforced end to end

Two games died on `AttributeError: 'str' object has no attribute 'get'`. The model
returned `messages` as bare strings rather than objects. Tool schemas set
`strict: true`, but **that is enforced by the Anthropic API and not by OpenRouter**,
so routing through a gateway silently drops the guarantee the schema appears to give.

Fixed by validating shape at the boundary: malformed entries are skipped and counted
rather than crashed on. Batch-level failure isolation meant this cost 2 games instead
of 24 — the robustness work paid for itself on its first real outing.

### Scope decision: stopping here

The four follow-ups above (stronger evaluator, richer context, longer games, better
commitment extraction) are real and would each cost real money to test — a stronger
evaluator alone is roughly $60 for a comparable 12-seed run. Deliberately not funding
that chase for this portfolio piece.

That is a scope call, not a resignation. The project's deliverable was never "prove
the belief layer works" — it was **build a harness rigorous enough that its answer,
whichever way it comes out, can be trusted.** That bar is met: three rounds of fixing
the measurement itself (§15–§18) before a result that finally has a tight enough
confidence interval to mean something (§19). A negative result from a sound harness
is a complete, honest deliverable. Chasing a positive from here would be optimizing
the finding rather than the engineering, which was never the point.

Anyone who wants to spend the $60 has exactly what they need to do it: the routing
preset, the batch command, and the eval harness all take a model swap as a one-line
change.

---

## 20. Free architectural fix: opportunity, not just position

Investigated whether a bigger/smarter evaluator model would resolve the AUC 0.4993
result before spending anything (a "top-10 leaderboard" model was proposed). Answer:
plausibly partial, not guaranteed, because leaderboard rank predicts general
reasoning capability, not calibration on this specific structured task — and half of
the four candidate causes in section 19 (missing board context, short games) are
architectural, not fixable by a bigger model at all. Testing a frontier model against
the same impoverished context would be an uninformative experiment: a null result
couldn't distinguish "the approach doesn't work" from "the evaluator still can't see
the board."

So the free one first. `engine.commitment_pressure(game, subject, province)` computes,
for each pledged province, what a human player would actually use to judge a promise:
is it a supply centre, who owns it, can the subject reach it this turn, could a rival
also contest it, and — the composite signal — would breaking the promise be an
uncontested free gain. This is wired into the evaluator's prompt and its instructions
now explicitly say to weigh computed opportunity above message wording: a pledge with
a real capture available is a genuine test of character; a pledge about an
unreachable or contested province is nearly unfalsifiable and should sit near the
prior regardless of how sincere it sounds.

All public board information — no isolation concern, verified by the same fixture
discipline as F7: `commitment_pressure` is tested against known 1901 positions rather
than trusted on inspection, and the evaluator prompt is asserted to actually contain
the computed data, not just callable in isolation.

**A one-call live smoke test shows the model engaging with the new variable
correctly**, which is necessary but not sufficient — it is not evidence the AUC
moves, only evidence the mechanism reaches the model as intended:

> *"NTH uncontested but not a free gain — no supply centre... No opportunity cost
> makes promise weakly testable."*
>
> *"Sevastopol is geographically distant... commitment is nearly unfalsifiable but
> requires no sacrifice."*

**Not yet re-run as a batch.** This closes one of the two architectural gaps from
section 19 (missing opportunity context); the other (8-phase games being short for
reputations to form) is untouched. Whether AUC moves at all requires the same paired,
seeded, well-powered batch discipline as section 19 — a small-n positive here would
be exactly the kind of unreliable signal this project exists to catch, not evidence.
