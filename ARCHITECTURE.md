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
- [ ] Fix the ground-truth validity problem, then re-run

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
