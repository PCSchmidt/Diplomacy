"""Phase 0 gate: prove `diplomacy` 1.1.2 can be driven programmatically on Python 3.14.

Checks, in order:
  1. A full game runs to completion with random legal orders (all phase types).
  2. Phase history is captured (the replay substrate).
  3. to_saved_game_format / from_saved_game_format round-trips faithfully.
  4. Adjudication is deterministic given identical orders.
"""

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import random
import sys

from diplomacy import Game
from diplomacy.utils.export import to_saved_game_format, from_saved_game_format

# `timestamp` is wall-clock, stamped at serialization time rather than being game
# data. It differs across an otherwise faithful round-trip. Our turn-log schema
# must therefore never depend on it -- see ARCHITECTURE.md section 3.
VOLATILE_KEYS = ("timestamp",)


def normalize(saved):
    """Strip serialization-time noise so replay comparisons are meaningful."""
    out = dict(saved)
    out["phases"] = []
    for phase in saved.get("phases", []):
        phase = dict(phase)
        state = phase.get("state")
        if isinstance(state, dict):
            phase["state"] = {k: v for k, v in state.items() if k not in VOLATILE_KEYS}
        out["phases"].append(phase)
    return out


from diplomacy_tom.engine import possible_orders  # the F3 choke-point


def play_random_game(seed, max_phases=200):
    rng = random.Random(seed)
    game = Game()
    phases_seen = []
    while not game.is_game_done and len(phases_seen) < max_phases:
        phases_seen.append(game.get_current_phase())
        possible = possible_orders(game)
        for power in sorted(game.powers):
            locs = sorted(game.get_orderable_locations(power))
            orders = [
                rng.choice(possible[loc])
                for loc in locs
                if possible.get(loc)
            ]
            game.set_orders(power, orders)
        game.process()
    return game, phases_seen


def main():
    failures = []

    # --- 1. full game to completion -------------------------------------
    game, phases = play_random_game(seed=42)
    print(f"[1] ran {len(phases)} phases, ended at {game.get_current_phase()}")
    print(f"    game_done={game.is_game_done}")

    kinds = {p[-1] for p in phases if p != "COMPLETED"}
    print(f"    phase types exercised: {sorted(kinds)}")
    if "M" not in kinds:
        failures.append("never exercised a Movement phase")
    if not {"R", "A"} & kinds:
        failures.append("never exercised Retreat or Adjustment phases")

    centers = {p: len(game.get_centers(p)) for p in sorted(game.powers)}
    print(f"    final centers: {centers}")
    if sum(centers.values()) == 0:
        failures.append("no supply centers owned at end - adjudication suspect")

    # --- 2. history captured --------------------------------------------
    hist = game.get_phase_history()
    print(f"[2] phase history entries: {len(hist)}")
    if len(hist) < 2:
        failures.append("phase history too short to replay")
    else:
        sample = hist[0]
        has_orders = bool(getattr(sample, "orders", None))
        has_state = bool(getattr(sample, "state", None))
        print(f"    first entry: name={sample.name} orders={has_orders} state={has_state}")
        if not (has_orders and has_state):
            failures.append("phase history missing orders or state")

    # --- 3. save/load round-trip ----------------------------------------
    saved = to_saved_game_format(game)
    restored = from_saved_game_format(saved)
    resaved = to_saved_game_format(restored)
    print(f"[3] saved keys: {sorted(saved.keys())}")
    print(f"    saved phases: {len(saved.get('phases', []))}")

    if saved == resaved:
        print("    round-trip: byte-identical")
    elif normalize(saved) == normalize(resaved):
        print("    round-trip: faithful (differs only in volatile timestamp)")
    else:
        print("    round-trip: DIFFERS in game data")
        failures.append("save/load round-trip not faithful")

    # --- 4. determinism --------------------------------------------------
    g1, p1 = play_random_game(seed=7)
    g2, p2 = play_random_game(seed=7)
    same = (p1 == p2 and
            {p: sorted(g1.get_centers(p)) for p in g1.powers} ==
            {p: sorted(g2.get_centers(p)) for p in g2.powers})
    print(f"[4] identical seed -> identical outcome: {same}")
    if not same:
        failures.append("adjudication not deterministic under identical orders")

    import hashlib
    fp = hashlib.md5(
        repr((phases, sorted((p, tuple(sorted(game.get_centers(p)))) for p in game.powers)))
        .encode()
    ).hexdigest()
    print(f"[5] cross-process fingerprint (seed=42): {fp}")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GATE PASSED - D1 holds, library is drivable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
