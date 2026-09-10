"""Phase 1 gate: the deterministic spine.

Proves a full game runs end to end with no LLM, drives every pipeline gate, and
emits a turn log that satisfies both schema and structural validation.

The cross-process determinism check here is the regression test for finding F3 --
the one that would otherwise have invalidated the D4 ablation silently.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import subprocess
import sys

from diplomacy_tom import belief as bl, isolation as iso, turn_log as tl
from diplomacy_tom.runner import GameConfig, GameRunner


def fingerprint_in_subprocess(seed: int, arm: str) -> str:
    """Run a game in a FRESH process and return its replay fingerprint.

    In-process comparison cannot detect F3-class bugs: PYTHONHASHSEED is fixed for
    the life of a process, so two runs inside one always agree. Only a separate
    process exercises the property that matters.
    """
    code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(_ROOT)!r});"
        "from diplomacy_tom.runner import run_game;"
        "from diplomacy_tom import turn_log as tl;"
        f"print(tl.replay_fingerprint(run_game(seed={seed}, arm={arm!r}, max_phases=12)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{out.stderr[-1500:]}")
    return out.stdout.strip().splitlines()[-1]


def main() -> int:
    failures: list[str] = []

    # --- 1. a full game runs and validates ------------------------------
    cfg = GameConfig(seed=42, arm="belief_on", max_phases=16)
    runner = GameRunner(cfg)
    log = runner.run()  # run() validates schema + alignment, raises on failure
    print(f"[1] game ran {len(log['turns'])} turns, "
          f"{len(log['game']['phases'])} phases, schema + alignment OK")
    print(f"    final phase: {runner.game.get_current_phase()}")

    centers = {p: len(runner.game.get_centers(p)) for p in sorted(runner.game.powers)}
    print(f"    centers: {centers}")

    # --- 2. the pipeline actually produced traffic ----------------------
    msgs = sum(len(t["messages"]) for t in log["turns"])
    corr = sum(len(t["corrections"]) for t in log["turns"])
    beliefs = sum(len(t["beliefs"]) for t in log["turns"])
    decisions = sum(len(t["decisions"]) for t in log["turns"])
    print(f"[2] traffic: {msgs} messages, {corr} corrections, "
          f"{beliefs} belief snapshots, {decisions} decisions")
    for label, n in (("messages", msgs), ("corrections", corr), ("beliefs", beliefs)):
        if n == 0:
            failures.append(f"pipeline produced no {label} -- nothing was exercised")

    kept = sum(1 for t in log["turns"] for c in t["corrections"] if c["kept"])
    broken = corr - kept
    print(f"    commitments: {kept} kept, {broken} broken")
    if broken == 0:
        failures.append("no commitment was ever broken -- trust dynamics untested")

    # --- 3. trust actually moved ----------------------------------------
    trusts = {
        (b["observer"], b["subject"]): b["trust"]
        for t in log["turns"] for b in t["beliefs"]
    }
    spread = max(trusts.values()) - min(trusts.values())
    print(f"[3] trust spread across dyads: {spread:.3f} "
          f"(min={min(trusts.values()):.3f} max={max(trusts.values()):.3f})")
    if spread < 1e-6:
        failures.append("all trust values identical -- belief layer inert")

    # --- 4. isolation held for the whole game ---------------------------
    leaks = []
    for observer, store in runner.stores.items():
        leaks += iso.audit_store(store, runner.registry)
    print(f"[4] full-game isolation audit across {len(runner.stores)} powers: "
          f"{len(leaks)} leaks")
    if leaks:
        failures.append(f"isolation leaked during a real game: {leaks[:3]}")

    # --- 5. cross-process determinism (the F3 regression test) ----------
    fp_a = fingerprint_in_subprocess(42, "belief_on")
    fp_b = fingerprint_in_subprocess(42, "belief_on")
    fp_c = fingerprint_in_subprocess(43, "belief_on")
    print(f"[5] cross-process fingerprint: {fp_a[:16]}")
    print(f"    stable across processes: {fp_a == fp_b}")
    print(f"    sensitive to seed:       {fp_a != fp_c}")
    if fp_a != fp_b:
        failures.append("F3 REGRESSION: same seed diverged across processes")
    if fp_a == fp_c:
        failures.append("fingerprint insensitive to seed")

    # --- 6. both ablation arms play the same game -----------------------
    # PHASE 1 ONLY. Scripted policies do not consult beliefs, so swapping the belief
    # layer changes what agents believe and nothing else -- identical games.
    #
    # THIS ASSERTION MUST INVERT IN PHASE 2. Once the decision layer reads the belief
    # state, the arms are SUPPOSED to diverge; that divergence is the D4 result. What
    # must stay identical then is the seed and initial conditions, not the outcome.
    # Do not "fix" a failing version of this check in Phase 2 -- rewrite it.
    fp_on = fingerprint_in_subprocess(42, "belief_on")
    fp_off = fingerprint_in_subprocess(42, "belief_off")
    print(f"[6] ablation arms on identical seed:")
    print(f"    belief_on  {fp_on[:16]}")
    print(f"    belief_off {fp_off[:16]}")
    if fp_on == fp_off:
        print("    same game played by both arms -- comparison is clean")
    else:
        print("    ARMS DIVERGED")
        failures.append("ablation arms played different games on the same seed")

    # --- 7. the stub arm is genuinely inert -----------------------------
    off_log = GameRunner(GameConfig(seed=42, arm="belief_off", max_phases=16)).run()
    off_trusts = {b["trust"] for t in off_log["turns"] for b in t["beliefs"]}
    print(f"[7] belief_off distinct trust values: {sorted(off_trusts)}")
    if len(off_trusts) != 1:
        failures.append("belief_off arm was not inert")

    # --- 8. the log survives a save/load round-trip ----------------------
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = tl.save(log, _Path(td) / "phase1.json")
        reloaded = tl.load(path)
        size = path.stat().st_size
    if tl.normalize_volatile(reloaded) == tl.normalize_volatile(log):
        print(f"[8] log round-trips faithfully ({size:,} bytes on disk)")
    else:
        failures.append("Phase 1 log did not survive save/load")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GATE PASSED - Phase 1 deterministic spine holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
