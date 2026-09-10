# AI Diplomacy — Theory of Mind Portfolio Project
## Scope & Architecture Document — v0.1

---

## 1. Project Overview

**What it is:** A Diplomacy-playing multi-agent system where AI powers negotiate, form alliances, and betray each other — with each agent maintaining an explicit, inspectable model of what it believes the other powers want and intend. The point of the project is not "an AI that plays Diplomacy well," it's a demonstration of Theory of Mind (ToM) engineering: recursive belief modeling, trust calibration, and betrayal prediction, built on infrastructure extended from [Meridian](#4-meridian-integration).

**Why Diplomacy:** It's a recognized hard benchmark in the LLM/ToM research space (see Meta's CICERO), it combines natural-language negotiation with deception detection and alliance-tracking, and — unlike most ToM toy benchmarks — it produces a naturally visual, demoable artifact (a live map plus a negotiation feed) rather than just a benchmark score.

**Portfolio tier:** Tier 1 (agentic system + evals). Secondary payoff: ties directly into the existing defense/intel portfolio narrative (AeroIntel, Hard Power Intelligence) via the intent-inference / belief-under-partial-observability angle.

---

## 2. Scope Decision

Full 7-power Diplomacy with every rules edge case (convoy paradoxes, retreat phases, build/disband bookkeeping) is a multi-month rules-engine exercise before the interesting part even starts.

**Decision: scope to 4 powers on a reduced map.** Either a custom 15–20 province mini-map or the standard map with the remaining powers played by simple scripted bots. This bounds the rules-engine work (roughly a week) so effort goes into belief modeling and negotiation, which is the actual portfolio signal — not into re-deriving Diplomacy adjudication from scratch.

---

## 3. High-Level Architecture

Each AI power runs three logically separate components:

1. **Belief layer (the ToM core)** — maintains a structured belief state over every other power: estimated goals, estimated alliance commitments, and a per-counterpart trust score, updated via Bayesian-style revision on (a) their public messages, (b) their actual revealed orders, (c) the discrepancy between the two.
2. **Negotiation layer** — LLM-driven message generation (proposals, threats, alliance offers) between powers. Structurally separate from belief-update logic (see Meridian mapping below) so an agent's own wishful thinking can't contaminate its trust model of an ally.
3. **Decision layer** — combines positional board evaluation (heuristic/minimax scoring) with the belief state to choose actual orders, including whether to honor or betray a stated commitment — the single most interesting behavior to expose and measure.

---

## 4. Meridian Integration

Meridian's three core mechanisms — Generator/Evaluator separation, DAG gate checkpoints, and schema-validated three-tier memory — map onto Diplomacy's structure directly. This is not reuse for its own sake: the underlying problem (prevent an agent from grading or believing its own story) is the same problem in both domains.

### 4.1 Generator/Evaluator → Negotiation/Belief split

- **Generator** = the negotiation agent drafting a message or proposing an order, reasoning from its own goals.
- **Evaluator** = a structurally separate agent that sees *only* the counterpart's messages and historical order record — never the Generator's private strategy — and outputs a belief-consistency judgment (does this message match their track record, how plausible is it given their board position, what's the confidence).

This preserves the same integrity property Meridian was built for: the belief evaluator can't be talked into trusting an ally by the negotiator's own confident framing, just as Meridian's Evaluator can't be talked into approving bad code by the Generator's confident tone.

### 4.2 DAG gate checkpoints → turn-phase gating

Diplomacy already has a hard phase structure (negotiate → orders → adjudicate → retreat → build) with real preconditions — the same shape Meridian's gates enforce. See [Section 5](#5-turn-processing-pipeline) for the full gate sequence.

### 4.3 Three-tier memory → power-indexed belief schema

**The problem with the singleton schema:** Meridian's original schema assumes one Generator/Evaluator pair over one shared context. Diplomacy breaks this immediately — belief is relational. With N powers there are N×(N-1) belief relationships, not N, and each one must be strictly information-isolated from the others (a leak here doesn't just look bad, it invalidates the whole experiment).

**Schema change:** move from a flat tier key to a composite key with an observer/subject pair:

```
belief:{observer_power}:{subject_power}:{tier}
```

| Tier | Scope | Contents |
|---|---|---|
| **Semantic** | Mostly global, with a power-scoped overlay | Map geography and rules (shared); "treaties I believe are in effect" (power-specific — two powers can hold contradictory beliefs here) |
| **Episodic** | Strictly power-scoped | Only what `observer` has actually seen about `subject` — messages received, publicly adjudicated orders. Never another power's private channel. |
| **Corrections** | Dyadic (trust-revision log) | Every time `subject`'s stated intent diverged from their actual orders, as observed by `observer` — schema-identical to how Meridian logs a Generator mistake the Evaluator caught. |

**Rationale:**
- Preserves the information-hiding boundary that makes belief modeling real rather than simulated (an agent must never have access to another power's private negotiations).
- Enables per-relationship trust tracking, which is what the eval story and the belief-network UI panel both depend on — an aggregate "France's trust level" number is much less interesting than "France's trust in England vs. France's trust in Germany."
- Enables isolated replay/audit per dyad for the belief-visualization inspector.

**Known extension risk:** Meridian's gates were designed around a single Generator/Evaluator pair per task. Diplomacy needs N pairs (one belief-evaluator per opposing power) running per turn. The gate/memory schema must be generalized to be power-indexed rather than singleton — this is a real generalization, not a relabeling exercise, and should be prototyped in isolation before the full engine is built on top of it.

---

## 5. Turn-Processing Pipeline

1. **Context-assembly gate** — for each power, assemble negotiation context from only `belief:{self}:*:episodic` and `:semantic`. Gate check: automated scan confirming no other power's private content is present before the prompt is sent.
2. **Negotiation phase** — Generator agents exchange messages pairwise; each message is written to both `belief:sender:receiver:episodic` and `belief:receiver:sender:episodic`.
3. **Negotiation-closed gate** — all powers have passed or the round timer expired.
4. **Belief-update gate (pre-orders)** — for every ordered pair, the Evaluator scores this turn's messages against that dyad's episodic + corrections history, writes a belief-delta, schema-validates it.
5. **Orders phase** — each power's Decision layer picks orders from its own belief state + board evaluation.
6. **Orders-valid gate** — reject and re-prompt on illegal/malformed orders before adjudication.
7. **Adjudication** — deterministic resolution; all orders become public.
8. **Post-adjudication revision gate** — for each dyad, diff stated intent (from negotiation) against actual orders; write the correction event (promise kept/broken); recompute trust score.
9. **Turn-complete gate** — verify every power's episodic + corrections memory is fully written and consistent before the next negotiation window opens. This is what makes it structurally impossible for an agent to enter round N+1 negotiation on stale belief data from an unprocessed betrayal in round N.

---

## 6. UI / UX Design

- **Board panel** — standard Diplomacy-style SVG map (adapt an existing open-source Diplomacy SVG map rather than drawing from scratch) with animated unit movement/dislodgement on turn resolution.
- **Belief-network panel** (the differentiator) — force-directed trust-network graph (D3) between all powers; edge thickness/color reflects current trust score; updates turn-by-turn.
- **Per-power mental model inspector** — click a power, see what your agent currently believes that power's goals and alliances are, versus what actually turns out to be true a few turns later. This is the eval story made visible.
- **Negotiation transcript panel** — messages shown alongside the Evaluator's real-time "predicted truthfulness" score, then a post-hoc "was it kept?" marker once orders resolve.

---

## 7. Suggested Tech Stack

- **Engine/backend:** Python. Either the open-source `diplomacy` (webdiplomacy-derived) adjudication library, or a hand-rolled adjudicator if the map is scoped down. FastAPI over websockets for live state updates.
- **Agents:** Direct Anthropic API calls (not Claude Code — see [Section 9](#9-build-tooling-notes)) for negotiation dialogue and order reasoning; structured/tool-call output for machine-parseable orders. Belief-state math (Bayesian updates, trust scoring) handled in plain Python — not delegated to the LLM.
- **Frontend:** React, SVG for the board, D3 for the trust-network graph, websocket stream for live turn updates.
- **Persistence:** log every turn's full state (orders, messages, belief snapshots) so games can be replayed and the eval harness built from logged data rather than live-only.

---

## 8. Eval Story / Success Metrics

The quantifiable layer that turns this from "cool demo" into a defensible Tier 1 piece:

- **Belief calibration** — how far off was a power's estimated trust score from that counterpart's actual subsequent behavior, tracked turn over turn.
- **Betrayal-prediction accuracy** — did the agent's belief state shift toward "this ally will betray me" before the betrayal actually happened, or only after?
- **Alliance stability** — aggregate metrics across many simulated games (how long alliances hold, what belief-state signatures precede a break).

---

## 9. Build-Tooling Notes

Two different layers are easy to conflate here, and conflating them wastes build time.

**Runtime (the game itself) vs. Claude Code (the dev tool):** The game's actual runtime — negotiation agents, belief evaluators — will be a standalone service making direct Anthropic API calls. It does not run inside a Claude Code session. Claude Code's native orchestration primitives (Hooks for PreToolUse/PostToolUse enforcement, Subagents, experimental Agent Teams) are scoped to software-engineering sessions — coding, editing, testing — not to production multi-agent runtimes. So the game's belief-modeling harness is genuinely novel work; it isn't something Claude Code's feature set already covers.

**Where the overlap is real: building the thing.** Some of what Meridian's custom DAG-gate plumbing does at build-time — "don't let a change pass until X validates" — is now something Claude Code's native Hooks do out of the box (e.g., a `PostToolUse` hook running the schema validator whenever the adjudication module changes, or a `PreToolUse` hook blocking a commit until tests pass). Using Meridian's own gate machinery to govern the coding workflow *while also* hand-building a separate gate system for the game's runtime would be duplicating the same pattern at two layers, when one layer already has a shipped tool doing the job.

**The clean split:**
- Use Claude Code's Hooks/Subagents natively as build-time discipline while writing the engine in VS Code.
- Reserve Meridian's actual gate/memory architecture — extended with the power-indexed schema in Section 4.3 — for the one thing nothing else provides: governing the belief-modeling behavior of the in-game agents themselves.

---

## 10. Open Questions / Next Steps

- [ ] Prototype the power-indexed memory schema in isolation (2-3 powers, synthetic messages) before wiring it into the full engine.
- [ ] Define the negotiation-message schema (what a message object contains so the Evaluator has something structured to score).
- [ ] Define the belief-network visualization data feed contract (what the backend emits per turn for the D3 trust graph).
- [ ] Decide: hand-rolled adjudicator vs. adapting the open-source `diplomacy` library.
- [ ] Decide: custom reduced map vs. standard map with scripted bot powers.
