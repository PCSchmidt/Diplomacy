#!/usr/bin/env python
"""Run every Phase 0/1 gate. Exit non-zero if any fails."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATES = ["tests/test_smoke.py", "tests/test_turn_log.py",
         "tests/test_belief.py", "tests/test_runner.py"]

def main() -> int:
    failed = []
    for gate in GATES:
        if not (ROOT / gate).exists():
            continue
        print(f"\n{'=' * 62}\n== {gate}\n{'=' * 62}")
        r = subprocess.run([sys.executable, str(ROOT / gate)], cwd=ROOT)
        if r.returncode != 0:
            failed.append(gate)
    print(f"\n{'=' * 62}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("ALL GATES PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
