# Diplomacy: Evidence Notes

Companion to Diplomacy.md. Labels: Confirmed, Ran it, Per the docs, My reading, Ask the author, Author says. All runs were made in a scratch copy of the repository (a `git archive` export, with a fresh virtual environment holding diplomacy 1.1.2 and jsonschema 4.26.0, Python 3.14.6, Node 24). The clone was never written to. No `.env` was read; key names only: ANTHROPIC_API_KEY, OPENROUTER_API_KEY. No paid API call was made.

## E1 Fact sheet

| Fact | Value | Label |
| --- | --- | --- |
| Name, address, licence | Diplomacy (AI Diplomacy, "diplomacy_tom" package); github.com/PCSchmidt/Diplomacy; public; AGPL-3.0-or-later for `diplomacy_tom/`, `tests/`, `schemas/`; MIT for `viewer/` (see NOTICE; GitHub reports agpl-3.0) | Confirmed |
| Kind | Research harness: multi-agent LLM game player with a belief layer, an ablation harness and a static replay viewer | Confirmed |
| Status | Declared a deliberate stopping point after a negative result; no releases | Per the docs |
| Size | about 3,200 lines Python in the package, about 1,500 in tests, about 440 in the viewer JS; 65 tracked files | Confirmed |
| Commits | 23, first 2026-09-10 16:01, last 2026-09-11 10:59 (author timezone -0400); all by "Chris Schmidt" | Confirmed |
| Building tool | Named only as "AI coding agents" in the guide, per the author's standing instruction | Per author instruction |
| Tests | 8 gates (7 Python scripts + viewer JS); 53 numbered checks in Python (5+8+9+8+11+8+4) plus 7 in the viewer = 60; all pass | Ran it |
| Fresh install | pip install diplomacy jsonschema (anthropic is imported lazily; the tests ran without it); no requirements file, no pins | Ran it |
| Needs | Paid key (OpenRouter or Anthropic) only for live games; none for tests | Confirmed |
| CI | 23 recorded runs: 21 "gates" (success), 1 "pages" (success), 1 run of an unidentified workflow not among the repo's workflow files (success) | Ran it (gh run list) |
| Deployed | GitHub Pages static viewer; HTTP 200 on one request; nothing else checked | Ran it |
| Users | GitHub shows 0 stars, 0 forks; no other use known | Confirmed / Ask the author |

## E2 Reading and running log

Read: README, ARCHITECTURE.md (all 20 sections), diplomacy-tom-scope.md, NOTICE, LICENSE header, .gitignore, .env.example (names only), both workflows, all of `diplomacy_tom/` except the body of `turn_log.py` and the mock provider internals, `tests/test_eval.py` (opening), `viewer/app.js` (metadata lines), reports, run logs.

Ran (scratch copy): all seven test scripts and the viewer script individually (each ended "GATE PASSED"); `python run_tests.py` (ALL GATES PASSED); analysis scripts over `runs/haiku7` (see E3, E4); edge probes (E4). Not run: any live model call, batch run, the Pages deploy, the viewer in a browser. Git status of the clone: clean (no tracked changes).

## E3 Claims check

| ID | Claim (source) | Check | Verdict |
| --- | --- | --- | --- |
| CL-01 | Definitive AUC 0.497, CI [0.453, 0.542], n=667 (README, ARCH 19) | L3: recomputed from the committed logs, paired on seed: AUC 0.4967, n=667, 236 broken. CI not reproduced exactly: message bootstrap 0.448 to 0.544, game bootstrap 0.460 to 0.542 | Supported |
| CL-02 | Calibration table (README: 15% said, 80% kept) | L3: bands match report; 0.148 predicted, 0.804 kept, n=51 | Supported |
| CL-03 | 10 matched pairs from 22 completed games (README) | L3: seeds 1901-1911 (on) and 1902-1912 (off); paired 1902-1911 | Supported |
| CL-04 | About $25 (README) | L3: sum of recorded usage over all 22 logs = $24.52; 20 paired = $22.2 | Supported (as recorded; not invoiced) |
| CL-05 | 8 gates, offline, no key (README) | L2: 7 + 1, all pass without network | Supported |
| CL-06 | Cross-process determinism job in CI (README) | L1: workflow present; local fingerprint 0f9e0213... printed by smoke gate; CI runs succeeded | Supported |
| CL-07 | 42/42 belief dyads exercised in live play (README, ARCH 18) | Not re-checkable without a live run; the haiku7 logs hold 7 powers' beliefs | Per the docs |
| CL-08 | "A second gate re-scans every assembled prompt and fails closed" (README) | Code: `iso.enforce` is called only in `runner._assemble_and_gate`, on `store.context_for_prompt(subject)` for every dyad, once per phase, after `_negotiate` and before `_collect_orders`. Not on final prompt strings | Partly (My reading) |
| CL-09 | "Everything is seeded and replayable... what makes the ablation possible at all" (README) | Replay is real and tested (test_phase2 check 5). But in live games the seed feeds only fallback/scripted policies; the provider payload has no seed or temperature; belief-on and belief-off prompts differ, so replay cannot supply identical replies to both arms. Matched seeds therefore pair nothing in live LLM runs | Partly (My reading) |
| CL-10 | "All 7 LLM-driven" (README) | Config in the haiku7 logs: llm_powers 7, scripted [] | Supported |
| CL-11 | "Betrayals weigh double" (ARCH 10) | `DEFAULT_BETRAYAL_WEIGHT = 2.0`; probe: 11/3 -> 0.786 vs 11/2 -> 0.846 | Supported |
| CL-12 | Live demo is a "replay viewer" (README) | True, but the committed sample game is a mock-provider game with the older 4 AI + 3 scripted config and header models "claude-opus-5"; the viewer shows no mock flag | Partly (see E14) |
| CL-13 | GLM fails tool calls on ~60% of decisions, ~75% of evaluations (README, ARCH 16) | 5/12 and 2/8 succeeded in the notes' four-position test; small sample; not re-run (needs paid calls) | Per the docs |
| CL-14 | "Every number in Results is a committed, regenerable artifact" (README) | Headline and calibration yes; the CI figure comes from a script not committed; the GLM-run logs (runs/glm) are not committed | Partly |
| CL-15 | The AUC correction note (README, ARCH 19) | Commit b7146f3 message matches; report file is right | Supported |

Claims counted: 15 listed; 2 partly (CL-08, CL-09 matter most), 1 partly (CL-12), 1 partly (CL-14).

## E4 Rule attacks and probes (scratch copy)

| Rule or input | Probe | Result |
| --- | --- | --- |
| R1 No cross-pair private messages | `observe_message` with a message between two other powers | ValueError "ISOLATION VIOLATION" |
| R1 gate, exact long leak | 58-character private text in a context for another viewer | caught (1 violation) |
| R1 gate, paraphrase | same idea reworded | missed (0 violations) |
| R1 gate, short text | 18-character private text | missed (below MIN_MATCH_LENGTH 24) |
| Self-belief | `trust("FRANCE")` on France's store | ValueError |
| Corrupt Beta | alpha=-1 | ValueError (clear message) |
| Model output range | `_unit(1.5)`, `_unit("abc")`, `_unit(None)` | 1.0, 0.5, 0.5 (the 0.5 is a silent default) |
| Bad weights | update weight 0, decay 0 | ValueError both |
| Reachability | France to BUR in 1901 / to MOS | True / False |
| Opportunity | `commitment_pressure(FRANCE, ZZZ)` unknown province | returns all-false dict without error |
| R3 scoring vs pledge type | Analysis of 667 scored pledges (E13) | Every pledge scored as "no move on <first province>" regardless of `commitment_type`; Italy "A ROM - APU" after promising to move A ROM to APU scored as broken |

## E5 Code map

`diplomacy_tom/engine.py` wrapper of the diplomacy library (sorted enumerations, `can_reach`, `commitment_pressure`); `belief.py` BetaTrust, BayesianBeliefStore, StubBeliefStore, `make_store`; `isolation.py` registry, `scan`, `enforce`, `audit_store`; `agents.py` Negotiator, BeliefEvaluator, OrderDecider, three tool schemas, three prompts; `llm.py` providers (Anthropic, OpenRouter via urllib, Recording, Replay, Mock), model registry, routing presets, Router; `runner.py` GameRunner pipeline; `evaluation.py` auc, brier, calibration_bins, betrayal_events, alliance_spans, cost_summary, Report; `batch.py` matched-seed batch with process pool; `turn_log.py` schema build, validate, alignment, fingerprint; `config.py` stdlib `.env` loader (not read here). `viewer/` static page (app.js, board.js, provinces.json, sample-game.json). Entry points: `run_game()`, `python -m diplomacy_tom.batch`, `run_tests.py`.

## E6 Model call sites

| Role | Where | Model in committed runs | Settings | Per-game volume |
| --- | --- | --- | --- | --- |
| negotiator | agents.Negotiator.draft | anthropic/claude-haiku-4.5 via OpenRouter | forced tool call, max_tokens 1600 | about 56 calls |
| belief_evaluator | agents.BeliefEvaluator.score | same | forced tool call, max_tokens 500 | about 164 calls |
| decision | agents.OrderDecider.decide | same | forced tool call, max_tokens 900; one retry with a terse system line | about 56 calls |

Totals over the 22 haiku7 logs: 6,069 recorded calls (1,232 negotiator, 3,605 evaluator, 1,232 decision), usage cost $24.52, cache_read_tokens 0 on every call. OpenRouter payload carries model, max_tokens, messages, tools and tool_choice only (Confirmed): no temperature, no seed, no effort. `effort` and cache breakpoints exist only on the Anthropic provider path, which no committed run used. Other presets: quality (Opus 5), balanced, cheap, glm-unreliable (GLM 5.3 Flash, retained for reproducibility), haiku. Pricing per the repo: Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku $1/$5 per million tokens; OpenRouter prices fetched from its catalogue at runtime. Not checked against invoices (Ask the author).

## E7 Tests and CI

Per gate numbered checks: smoke 5, turn_log 8, belief 9, runner 8, phase2 11, eval 8, pressure 4, viewer 7. All pass. Spot checks: (1) test_eval: synthetic logs with known AUC (perfect 1.0, constant 0.5, lead 0) and a mock-provider run must be flagged not evidence; (2) test_phase2 separation: a message the observer sent is planted; it is present in the negotiator context, absent from `evaluator_context` and from the assembled evaluator prompt; (3) test_belief leak fixture: third-party message in France's context is caught, `enforce` raises, reformatted and nested leaks are caught, own-message and 6 legitimate contexts raise nothing. No pytest, no coverage tool, no property tests. No test covers the mapping from `commitment_type` to scoring. CI: gate matrix over hash seeds 0, 1, 12345, random (Python 3.12); a fingerprint job over 0, 1, 12345, 99991; neither calls a model. Pages workflow runs the viewer test and three licence-boundary greps before deploying. All recorded runs succeeded.

## E8 Plan versus results, history

Order of commits (author time): architecture and Phase 0 (16:28 to 16:57, Sep 10), Phase 2 (17:36), viewer (17:55), eval harness with metrics and matched seeds (18:03), first live ablation (00:50 Sep 11), silent-default and reliability fixes (07:32 to 07:53), seven-power revision (08:19), definitive ablation (09:27), stop decision (10:23), evaluator-context fix (10:43), README restructure and figure correction (10:59). The metric choice (AUC as primary, calibration, betrayal lead) is in the Phase 4 commit about seven hours before the first live result: a pre-specified measure, but no locked protocol, no success rule and the plan was revised repeatedly. GitHub push times were not retrieved; commit times used. Bulk: no commit is huge except Phase 0 to 4 build commits (each a whole phase).
## E9 Gates and approvals

The project's "gates" are test scripts, not approval steps. No human approval record exists. The evaluator-context fix (commit 254f10d) is documented as not re-validated as a batch.

## E10 Environment

Installed in scratch: diplomacy 1.1.2 (the version named in the docs), jsonschema 4.26.0. The repo records versions in each log (`run.code_version`: diplomacy 1.1.2, Python 3.14.6, git sha). CI uses Python 3.12. No lockfile. The notes say the diplomacy library builds from source on Python 3.14; it installed cleanly in the scratch copy. Model versions are by name only (anthropic/claude-haiku-4.5).

## E11 Security and privacy

Secret scan: `git grep` for OpenRouter and Anthropic key patterns across all revisions: no match. Only `.env.example` is tracked among env files; `.gitignore` covers `.env` and `.env.*`. `runs/` and `reports/` are listed in `.gitignore` but are tracked (force-added). Outside services: OpenRouter (HTTPS POST, bearer key from environment), optional Anthropic SDK, GitHub Pages. No personal data; logs contain model text only. No claim is made about the live site's security state.

## E12 Shortcomings register

| # | Shortcoming | Evidence | Severity | Disclosed? | Options | Recommendation | Effort / payoff |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | Scoring treats every pledge as "no move on the first named province", ignoring commitment type | `runner._ingest_message`, `_revise_beliefs`; E13 counts | High | No | (A) Rescore saved logs with type-aware rules (free; can mis-handle alliance and support types). (B) Constrain the negotiator to testable non-move pledges and rerun (about $17 per arm of 12 games at recorded cost). (C) Document and leave. | A now, then B if the subset result moves | Small / High |
| S2 | No simple baseline (power's past kept rate) | evaluation.py | Medium | No | Add baseline to report; or leave | Add | Small / Medium |
| S3 | Gate described as scanning every assembled prompt; it audits stored contexts once per phase after negotiation | CL-08 | Medium | No | (A) Call `enforce` on final prompt strings before every model call. (B) Fix the README wording | Both | Small / Medium |
| S4 | Matched seeds do not control model output in live games | CL-09 | Medium | No | (A) Pass provider seeds where supported. (B) Treat arms as independent and say so; use more games | B, plus more games | Small / Medium |
| S5 | Prompt caching designed but unused (cache reads 0) | E6 | Low | Partly | Use Anthropic provider path or OpenRouter cache hints | Optional | Medium / Low |
| S6 | Non-numeric evaluator score becomes 0.5 | `_unit` default | Low | No | Return no score instead | Fix | Small / Low |
| S7 | Demo is a mock game with real-model names, no label | sample-game.json, app.js | Medium | Partly (ARCH 13 says sample is mock) | Replace with a real game from `runs/haiku7`, or label | Do both | Small / High |
| S8 | Only one model, 8 phases, 10 pairs | README | Medium | Yes | Stronger evaluator, longer games (about $60 for a comparable run per ARCH 19) | Leave unless funded | Large / Medium |
| S9 | Only the first province of the first province-bearing intent is scored | runner | Medium | No | Score all named provinces | With S1 | Small / Medium |
| S10 | No dependency file or pins | repo | Low | No | Add requirements | Add | Small / Low |

## E13 Math and method detail

Beta trust: alpha, beta start 1, 1. Kept: alpha += 1. Broken: beta += 2. Mean = alpha/(alpha+beta). Variance = alpha*beta / ((alpha+beta)^2 (alpha+beta+1)). Confidence = clamp(1 - 2 sqrt(var)). Decay: alpha = 1 + (alpha-1)*0.98, same for beta, each phase. Probe values: one stab 0.25 (confidence 0.613); ten kept 0.917 (0.847); then stab 0.786; unweighted 0.846; one decay step from (11,3) gives (10.8, 2.96), mean 0.7849. AUC: Mann-Whitney over pairs, ties 0.5. Brier: mean squared error. Complexity of AUC: O(P x N), fine here (431 x 236). Always-0.646 predictor Brier = 0.646 x 0.354 = 0.2286 (derived; not in the repo). Evaluator Brier 0.2945, trust Brier 0.2469.

Pledge-type analysis (scratch, belief-on paired games 1902-1911, falsifiable and scored rows, type = first intent with provinces): move 188 (107 kept, 81 broken), dmz 143 (97/46), non_aggression 136 (85/51), alliance 105 (67/38), hold 72 (57/15), support 13 (11/2), none 10 (7/3); total 667. Matching subset (dmz + non_aggression) n=279, kept 182, broken 97, AUC 0.561, row-bootstrap 95% range 0.487 to 0.629; others n=388, AUC 0.451, range 0.392 to 0.505. Post hoc, row-level resampling (understates uncertainty from clustering by game). Per-game AUC over the 10 games: 0.603, 0.492, 0.564, 0.529, 0.388, 0.450, 0.495, 0.515, 0.510, 0.423. Example: Austria to Russia, message S1901M-AUSRUS-1, intent non_aggression naming GAL, WAR, RUM; evaluator 0.7 / confidence 0.4; actual orders "A BUD - RUM; A VIE - GAL; F TRI - VEN"; scored broken on GAL; trust 0.5 to 0.25.

Totals: 1,622 messages in the 10 belief-on games, all with an evaluation; 1,593 resolved pledges of which 926 unfalsifiable (58.1%); no_decision 0 of 560 decisions per arm.

## E14 Discrepancies

1. README "re-scans every assembled prompt" versus code (CL-08).
2. README "recorded and replayed... what makes the ablation possible" versus live arms with different prompts and no seed (CL-09).
3. README Tests row says "8 gates" while the path table says "7 offline gates" (the 8th is the viewer; consistent once explained).
4. ARCHITECTURE section 8 says smoke test and `scripts/` files; the package moved later (stale paths in early sections).
5. Demo sample is a mock game with models listed as claude-opus-5 and the older 4+3 config (ARCH 13 and 14 acknowledge mock origin; README does not).
6. `.gitignore` ignores `runs/` and `reports/`, yet both are committed.
7. ARCH 15 and README say the GLM batch logs are in `runs/glm/`; that folder is not in the repository.
8. README says cost ~$25 for the run; per-arm paired costs are $1.41 and $0.81 per game, while ARCH 18 estimated $1.00 per game.

## E15 Production readiness

Traits: runnable from clean start (Yes for tests; versions not pinned); automatic checks block bad change (Partly: tests yes, quality evaluation no); quality measured against a baseline (Partly: coin flip and base rate yes, simple predictor no); safe failure (Partly: retries, batch isolation, fail-loud; no cost cap in the live run path); human in the loop (No); prompts and models versioned (Partly: git history and per-log model names); logs good for diagnosis (Yes: every call, cost, prompt hash); data and secrets safe (Yes by scan; no sensitive data). Placement: Works locally, plus a static demo. Gap list: service wrapper, auth, quotas, monitoring, rollback, hosted keys, security review, runbook, legal review of the AGPL obligation if offered as a service.

## E16 Review dispositions

Accuracy review run 2026-10-28; see Diplomacy.review.md. Figures re-derived from the committed logs (AUC 0.4967, n=667; type split 279/388 = 0.561/0.451; 60 numbered checks); wording fixes applied to the guide.

## E17 Completeness and backlog

Promised versus built: D1 engine (done, tested); D2 all seven LLM (done, tested live per docs); D3 replay-first demo (done; sample is mock); D4 ablation (done, run once); D5 portfolio restructure (planned in ARCH; not part of this repository); D7 licence split (done, enforced in Pages workflow); Phase 5 funnel (outside repo). Backlog: Finish (replace demo sample, S7); Fix (S1, S3, S6, S9); Improve (S2, S4, S10); Add (stronger evaluator, longer games, richer extraction, a pre-registered protocol). Milestone 1: type-aware rescoring of the 22 saved games with a report of both results (exit test: new report committed with the pledge-type split). Milestone 2: relabel or replace the demo. Milestone 3: one funded rerun under a written protocol.

## Diagram sources

Images are rendered by a matplotlib script (kept outside the repo): Diplomacy-parts.png (one turn, fixed versus learned), Diplomacy-learned-vs-rules.png, Diplomacy-results.png (calibration bands: 0.148/0.804/51, 0.295/0.610/146, 0.484/0.615/39, 0.713/0.626/313, 0.872/0.686/118; kept rate line 0.646), Diplomacy-pledge-types.png (counts in E13). Chart numbers match the text.


## Revision log (v1 draft to v2, reader-check fixes, 2026-10-28)

Archived the earlier text as Diplomacy.v1draft.md (6,692 words). All ten reader-check fixes applied:
1. The guide now opens with the plain finding (judge no better than a coin flip), explains the pick-one-kept-one-broken test before giving AUC 0.497 on 667 promises, and states the scoring flaw (every pledge scored as "did not move there", only about 42% are that kind, may hide a signal) next to it.
2. Harness, arm, seed, round (the game software's "phase"), tool call, prompt and AUC are each defined at first use; "turn" no longer used.
3. Trust number (arithmetic from outcomes) versus evaluator guess (AI forecast) separated in one paragraph before the Austria example.
4. Beta distribution name and the 2% drift sentence removed; counting explained with the toy example only.
5. Leak-check details (24-character floor, paraphrase probe), GLM comparison figures (only 5 of 12 vs 11 of 12 kept), hash-seed and CI details cut to short prose.
6. Testing edge-case table replaced by prose.
7. Scoring flaw tied to the picture at first mention of 42%.
8. "Gate" now means nothing in the body: "leak check" for the privacy check, "test scripts" for the eight scripts. Pictures regenerated with "leak check".
9. Meridian, CICERO and the defense-interest detour removed (one clause on defense interest kept in the problem chapter).
10. Repetition of the finding reduced; recruiter requirements table dropped; Likely questions split into short Q&A lines (five kept).
Also: "fails closed" replaced with a plain description of the leak check; the guide names the builder only as "AI coding agents". Study-component model names (Claude Haiku 4.5, GLM) stay. Pictures regenerated: Diplomacy-parts.png and Diplomacy-learned-vs-rules.png (results and pledge-types unchanged). Dropped from the body only, facts unchanged above: E3 prompt versioning, caching-unused finding, README-versus-code leak-scan discrepancy, hash-seed CI detail, Brier score (0.294 versus 0.25 and about 0.23).
