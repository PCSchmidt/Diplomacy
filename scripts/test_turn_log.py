"""Phase 0 gate: the turn-log schema holds against a real game.

Negative cases matter as much as positive ones here. A validator that has only ever
seen valid input proves nothing, so each rejection case below is a fixture that MUST
fail -- same discipline as the deliberate-leak fixture for the isolation gate.
"""

from __future__ import annotations

import copy
import json
import random
import sys

from diplomacy import Game
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

import turn_log as tl


def possible_orders(game):
    """Sorted at the boundary. See finding F3 in ARCHITECTURE.md -- the library's
    enumeration order varies with PYTHONHASHSEED across processes."""
    return {loc: sorted(orders) for loc, orders in game.get_all_possible_orders().items()}


def play(seed: int, phases: int = 8) -> dict:
    rng = random.Random(seed)
    game = Game()
    for _ in range(phases):
        if game.is_game_done:
            break
        po = possible_orders(game)
        for power in sorted(game.powers):
            locs = sorted(game.get_orderable_locations(power))
            game.set_orders(power, [rng.choice(po[l]) for l in locs if po.get(l)])
        game.process()
    return to_saved_game_format(game)


def make_log(seed: int = 42) -> dict:
    saved = play(seed)
    return tl.build_log(
        saved,
        seed=seed,
        arm="belief_on",
        llm_powers=["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY"],
        scripted_powers=["ITALY", "RUSSIA", "TURKEY"],
        models={"negotiator": "claude-sonnet-5", "belief_evaluator": "claude-sonnet-5"},
        turns=tl.turns_from_saved_game(saved),
    )


def expect_rejected(log: dict, label: str, failures: list[str]) -> None:
    errors = tl.validate(log, strict=False)
    if errors:
        print(f"    rejected as designed: {label}")
    else:
        print(f"    ACCEPTED BUT SHOULD NOT BE: {label}")
        failures.append(f"schema accepted invalid log: {label}")


def main() -> int:
    failures: list[str] = []

    # --- 1. a real game produces a valid log ----------------------------
    log = make_log()
    tl.validate(log)
    print(f"[1] real game validates: {len(log['game']['phases'])} phases, "
          f"{len(log['turns'])} turns")
    print(f"    rules: {log['game']['rules']} (NO_PRESS stripped)")
    print(f"    code_version: {log['run']['code_version']}")

    problems = tl.check_alignment(log)
    print(f"[2] structural alignment: {'clean' if not problems else problems}")
    if problems:
        failures.append(f"alignment problems on a clean log: {problems}")

    # --- 3. save/load round-trip through the validator -------------------
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        path = tl.save(log, pathlib.Path(td) / "game.json")
        reloaded = tl.load(path)
    if tl.normalize_volatile(reloaded) == tl.normalize_volatile(log):
        print("[3] save/load round-trip: faithful")
    else:
        print("[3] save/load round-trip: DIFFERS")
        failures.append("turn log did not survive save/load")

    # --- 4. the embedded game subtree is still a valid saved game --------
    # This is the payoff of embedding verbatim rather than translating.
    try:
        restored = from_saved_game_format(copy.deepcopy(log["game"]))
        print(f"[4] embedded subtree still loads in `diplomacy`: "
              f"phase={restored.get_current_phase()}")
    except Exception as exc:  # noqa: BLE001 - gate should report, not crash
        print(f"[4] embedded subtree FAILED to load: {exc}")
        failures.append(f"embedded game subtree not loadable by library: {exc}")

    # --- 5. fingerprint is stable and seed-sensitive ---------------------
    fp_a = tl.replay_fingerprint(make_log(42))
    fp_b = tl.replay_fingerprint(make_log(42))
    fp_c = tl.replay_fingerprint(make_log(43))
    print(f"[5] fingerprint seed42={fp_a[:16]}  stable={fp_a == fp_b}  "
          f"differs_on_seed43={fp_a != fp_c}")
    if fp_a != fp_b:
        failures.append("replay fingerprint unstable for identical seed")
    if fp_a == fp_c:
        failures.append("replay fingerprint insensitive to seed")

    # --- 6. normalization actually strips the volatile fields ------------
    raw = json.dumps(log)
    norm = json.dumps(tl.normalize_volatile(log))
    if '"timestamp"' in raw and '"timestamp"' not in norm:
        print("[6] volatile timestamp present raw, absent after normalize")
    else:
        print("[6] normalization did not behave as expected")
        failures.append("normalize_volatile did not strip timestamp")

    # --- 7. negative fixtures: these MUST be rejected --------------------
    print("[7] negative fixtures:")

    bad = copy.deepcopy(log)
    bad["game"]["rules"].append("NO_PRESS")
    expect_rejected(bad, "NO_PRESS in a negotiation game", failures)

    bad = copy.deepcopy(log)
    bad["run"]["arm"] = "belief_maybe"
    expect_rejected(bad, "unknown ablation arm", failures)

    bad = copy.deepcopy(log)
    del bad["run"]["seed"]
    expect_rejected(bad, "missing seed (D4 needs it)", failures)

    bad = copy.deepcopy(log)
    bad["turns"][0]["beliefs"] = [
        {"observer": "FRANCE", "subject": "ENGLAND", "trust": 1.7}
    ]
    expect_rejected(bad, "trust outside [0,1]", failures)

    bad = copy.deepcopy(log)
    bad["turns"][0]["phase"] = "X9999Z"
    expect_rejected(bad, "malformed phase name", failures)

    bad = copy.deepcopy(log)
    bad["turns"][0]["unexpected_field"] = True
    expect_rejected(bad, "unknown field on a turn", failures)

    bad = copy.deepcopy(log)
    bad["schema_version"] = "1.0"
    expect_rejected(bad, "non-semver schema_version", failures)

    # --- 8. alignment catches what the schema cannot ---------------------
    print("[8] structural fixtures (beyond schema reach):")

    bad = copy.deepcopy(log)
    bad["turns"][0]["board_hash"] = "0"
    if tl.check_alignment(bad):
        print("    caught: board_hash not matching its phase")
    else:
        failures.append("alignment missed a board_hash mismatch")

    bad = copy.deepcopy(log)
    bad["turns"][0]["beliefs"] = [
        {"observer": "FRANCE", "subject": "FRANCE", "trust": 0.5}
    ]
    if tl.check_alignment(bad):
        print("    caught: power holding beliefs about itself")
    else:
        failures.append("alignment missed observer == subject")

    bad = copy.deepcopy(log)
    bad["turns"][0]["corrections"] = [
        {"observer": "FRANCE", "subject": "ENGLAND",
         "message_id": "does-not-exist", "kept": False}
    ]
    if tl.check_alignment(bad):
        print("    caught: correction citing an unknown message")
    else:
        failures.append("alignment missed a dangling message_id")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GATE PASSED - turn-log schema v%s holds." % tl.SCHEMA_VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
