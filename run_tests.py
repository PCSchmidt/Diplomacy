#!/usr/bin/env python
"""Run every Phase 0/1 gate. Exit non-zero if any fails."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATES = ["tests/test_smoke.py", "tests/test_turn_log.py",
         "tests/test_belief.py", "tests/test_runner.py",
         "tests/test_phase2.py", "tests/test_eval.py",
         "tests/test_pressure.py"]

def main() -> int:
    failed = []
    # The viewer is JS and licence-separate, so it gets its own runner rather than
    # being imported. Skipped (not failed) when node is unavailable.
    for gate in GATES:
        if not (ROOT / gate).exists():
            continue
        print(f"\n{'=' * 62}\n== {gate}\n{'=' * 62}")
        r = subprocess.run([sys.executable, str(ROOT / gate)], cwd=ROOT)
        if r.returncode != 0:
            failed.append(gate)
    import shutil
    if shutil.which("node") and (ROOT / "viewer" / "test-viewer.mjs").exists():
        print(f"\n{'=' * 62}\n== viewer/test-viewer.mjs\n{'=' * 62}")
        r = subprocess.run(["node", "viewer/test-viewer.mjs"], cwd=ROOT)
        if r.returncode != 0:
            failed.append("viewer/test-viewer.mjs")
    else:
        print("\n(node not found - skipping viewer gate)")

    print(f"\n{'=' * 62}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("ALL GATES PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
