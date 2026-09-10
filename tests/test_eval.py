"""Phase 4 gate: the eval harness.

Tests the metrics against *known* inputs — a harness that computes a number from a
real game tells you nothing about whether the number is right. Synthetic fixtures
with known answers do.

The most important assertion here is check 7: the harness must refuse to present
mock-derived results as evidence. Every other metric in this file is computed on
mock data and is therefore noise; the gate proves the machinery, not the finding.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import sys

from diplomacy_tom import batch
from diplomacy_tom import evaluation as ev
from diplomacy_tom import turn_log as tl
from diplomacy_tom.runner import run_game


def synth_log(arm="belief_on", provider="anthropic", pairs=(), betrayal_lead=None):
    """A minimal schema-shaped log with known metric answers."""
    turns, phases = [], []
    names = ["S1901M", "F1901M", "S1902M", "F1902M"]
    for i, name in enumerate(names):
        turns.append({"phase": name, "board_hash": f"h{i}", "messages": [],
                      "beliefs": [], "decisions": [], "corrections": []})
        phases.append({"name": name, "state": {"zobrist_hash": f"h{i}",
                       "units": {}, "centers": {}}, "orders": {}, "results": {}})

    for j, (score, kept) in enumerate(pairs):
        mid = f"m{j}"
        turns[0]["messages"].append({
            "message_id": mid, "sender": "FRANCE", "recipient": "ENGLAND",
            "body": f"promise {j}",
            "evaluation": {"predicted_truthfulness": score, "confidence": 0.8},
        })
        turns[1]["corrections"].append({
            "observer": "ENGLAND", "subject": "FRANCE", "message_id": mid,
            "kept": kept, "trust_before": score,
        })

    if betrayal_lead is not None:
        # Rising betrayal estimate, then the stab in the final phase.
        for i, name in enumerate(names):
            pb = 0.2 + (0.3 if i >= betrayal_lead else 0.0)
            turns[i]["beliefs"].append({
                "observer": "ENGLAND", "subject": "GERMANY", "trust": 1 - pb,
                "predicted_betrayal": {"probability": pb, "horizon_phases": 1},
            })
        turns[-1]["messages"].append({
            "message_id": "bm", "sender": "GERMANY", "recipient": "ENGLAND",
            "body": "trust me"})
        turns[-1]["corrections"].append({
            "observer": "ENGLAND", "subject": "GERMANY",
            "message_id": "bm", "kept": False})

    return {
        "schema_version": tl.SCHEMA_VERSION,
        "run": {"run_id": "t", "created_utc": "2026-01-01T00:00:00+00:00",
                "seed": 1, "arm": arm,
                "config": {"llm_powers": ["FRANCE"], "scripted_powers": [],
                           "models": {"negotiator": "claude-opus-5"},
                           "provider": provider},
                "code_version": {"git_sha": "x", "diplomacy_version": "1.1.2"}},
        "game": {"id": "g", "map": "standard", "rules": ["POWER_CHOICE"],
                 "phases": phases},
        "turns": turns,
    }


def main() -> int:
    failures: list[str] = []
    close = lambda a, b, t=1e-6: a is not None and abs(a - b) < t

    # --- 1. primitives against known answers ----------------------------
    print("[1] metric primitives:")
    cases = [
        ("perfect separation", ev.auc([(0.9, True), (0.8, True), (0.2, False), (0.1, False)]), 1.0),
        ("inverted", ev.auc([(0.1, True), (0.9, False)]), 0.0),
        ("all ties = chance", ev.auc([(0.5, True), (0.5, False)]), 0.5),
        ("brier always-0.5", ev.brier([(0.5, True), (0.5, False)]), 0.25),
        ("brier perfect", ev.brier([(1.0, True), (0.0, False)]), 0.0),
    ]
    for label, got, want in cases:
        ok = close(got, want)
        print(f"    {'ok ' if ok else 'FAIL'} {label}: {got} (expected {want})")
        if not ok:
            failures.append(f"{label}: got {got}, expected {want}")

    if ev.auc([(0.9, True), (0.8, True)]) is not None:
        failures.append("AUC returned a number with only one class present")
    else:
        print("    ok  one-class AUC is None, not 0 (undefined, not bad)")

    # --- 2. end-to-end on a log with a known answer ---------------------
    print("[2] harness on a synthetic log with a known answer:")
    perfect = synth_log(pairs=[(0.95, True), (0.9, True), (0.1, False), (0.05, False)])
    tl.validate(perfect)
    rep = ev.evaluate_arm([perfect], "belief_on")
    print(f"    resolved={rep.resolved} broken={rep.broken} AUC={rep.evaluator_auc}")
    if rep.resolved != 4:
        failures.append(f"expected 4 resolved messages, got {rep.resolved}")
    if rep.broken != 2:
        failures.append(f"expected 2 broken, got {rep.broken}")
    if not close(rep.evaluator_auc, 1.0):
        failures.append(f"perfect evaluator should score AUC 1.0, got {rep.evaluator_auc}")
    else:
        print("    ok  a perfect evaluator scores AUC 1.0 end to end")

    useless = synth_log(pairs=[(0.5, True), (0.5, False), (0.5, True), (0.5, False)])
    rep_u = ev.evaluate_arm([useless], "belief_on")
    if not close(rep_u.evaluator_auc, 0.5):
        failures.append(f"a useless evaluator should score 0.5, got {rep_u.evaluator_auc}")
    else:
        print("    ok  an evaluator that says 0.5 to everything scores AUC 0.5")

    # --- 3. betrayal lead time ------------------------------------------
    print("[3] betrayal lead time:")
    early = ev.betrayal_events(synth_log(betrayal_lead=1))
    late = ev.betrayal_events(synth_log(betrayal_lead=3))
    print(f"    belief rising at phase 1 -> lead {early[0]['lead']}")
    print(f"    belief rising at phase 3 -> lead {late[0]['lead']}")
    if not (early[0]["lead"] > late[0]["lead"]):
        failures.append("earlier belief shift did not produce a longer lead")
    else:
        print("    ok  anticipating earlier yields a longer lead")

    flat = synth_log(betrayal_lead=99)   # never rises
    if ev.betrayal_events(flat)[0]["lead"] != 0:
        failures.append("a system that never anticipates should score lead 0")
    else:
        print("    ok  never anticipating scores lead 0 (reacts, never predicts)")

    # --- 4. calibration bins --------------------------------------------
    print("[4] calibration:")
    honest = [(0.9, True)] * 9 + [(0.9, False)] * 1 + [(0.1, False)] * 9 + [(0.1, True)]
    bins = [b for b in ev.calibration_bins(honest) if b["n"]]
    for b in bins:
        print(f"    {b['lo']:.1f}-{b['hi']:.1f}: n={b['n']} "
              f"predicted={b['predicted']} actual={b['actual']}")
    for b in bins:
        if abs(b["predicted"] - b["actual"]) > 0.15:
            failures.append(f"well-calibrated input landed in a mismatched bin: {b}")

    # --- 5. alliance spans ----------------------------------------------
    print("[5] alliance spans:")
    log = synth_log()
    for i, t in enumerate(log["turns"]):
        trust = [0.9, 0.9, 0.9, 0.2][i]
        t["beliefs"].append({"observer": "FRANCE", "subject": "ITALY", "trust": trust})
    spans = ev.alliance_spans(log)
    print(f"    high trust for 3 phases then collapse -> spans {spans}")
    if spans != [3]:
        failures.append(f"expected a single 3-phase span, got {spans}")

    # --- 6. matched-seed batch ------------------------------------------
    print("[6] matched-seed batch:")
    report = batch.run_batch(games=2, max_phases=6, provider="mock",
                             seed0=555, progress=lambda *_: None)
    print(f"    belief_on games={report.on.games} "
          f"belief_off games={report.off.games}")
    if report.on.games != 2 or report.off.games != 2:
        failures.append("batch did not produce equal games per arm")
    else:
        print("    ok  arms are paired on identical seeds")

    # --- 7. THE HONESTY GATE --------------------------------------------
    print("[7] synthetic results must not be reported as evidence:")
    if report.is_evidence:
        print("    FAIL mock-derived report claimed to be evidence")
        failures.append("harness presented synthetic results as evidence")
    else:
        print("    ok  mock-derived report is flagged: is_evidence=False")

    md = report.to_markdown()
    if "not evidence" not in md.lower():
        failures.append("markdown report omits the synthetic-data warning")
    else:
        print("    ok  markdown leads with the warning, not the numbers")

    real = ev.Report(
        on=ev.evaluate_arm([synth_log(provider="anthropic")], "belief_on"),
        off=ev.evaluate_arm([synth_log(arm="belief_off", provider="anthropic")], "belief_off"),
    )
    if not real.is_evidence:
        failures.append("a real-provider report was wrongly flagged synthetic")
    else:
        print("    ok  a real-provider report is not flagged")

    mixed = ev.Report(
        on=ev.evaluate_arm([synth_log(provider="anthropic")], "belief_on"),
        off=ev.evaluate_arm([synth_log(arm="belief_off", provider="mock")], "belief_off"),
    )
    if mixed.is_evidence:
        failures.append("a half-synthetic comparison was accepted as evidence")
    else:
        print("    ok  one synthetic arm poisons the comparison (correct)")

    # --- 8. provenance is recorded by real runs --------------------------
    print("[8] provenance:")
    live = run_game(seed=3, max_phases=3, use_llm=True)
    prov = live["run"]["config"]["provider"]
    print(f"    a mock run records provider={prov!r}, synthetic={tl.is_synthetic(live)}")
    if prov != "mock" or not tl.is_synthetic(live):
        failures.append("mock run did not record itself as mock")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GATE PASSED - eval harness holds (metrics verified against known inputs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
