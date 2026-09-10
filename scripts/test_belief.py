"""Phase 0 gate: power-indexed belief store and isolation gate.

Implements the scope doc's first next-step -- prototype the schema in isolation with
3 powers and synthetic messages, before wiring it into the full engine.

The deliberate-leak fixture is the centrepiece. A gate that has only ever seen clean
input proves nothing, so this asserts the gate FAILS on a planted leak.
"""

from __future__ import annotations

import sys

import belief as bl
import isolation as iso
import turn_log as tl


def msg(mid, sender, recipient, body, intent=None):
    m = {"message_id": mid, "sender": sender, "recipient": recipient, "body": body}
    if intent:
        m["stated_intent"] = intent
    return m


def main() -> int:
    failures: list[str] = []
    P = ["FRANCE", "ENGLAND", "GERMANY"]

    # --- 1. construction and self-modelling guard -----------------------
    stores = {p: bl.BayesianBeliefStore(p, P) for p in P}
    print(f"[1] built stores for {P}")
    for p, s in stores.items():
        if p in s.dyads:
            failures.append(f"{p} holds a dyad about itself")
    print(f"    dyad keys: {{{', '.join(f'{p}:{sorted(s.dyads)}' for p, s in stores.items())}}}")

    try:
        stores["FRANCE"]._dyad("FRANCE")
        failures.append("self-dyad access was permitted")
        print("    self-modelling: NOT BLOCKED")
    except ValueError:
        print("    self-modelling: blocked as designed")

    # --- 2. Beta trust behaves sensibly ---------------------------------
    t = bl.BetaTrust()
    print(f"[2] prior: mean={t.mean:.3f} confidence={t.confidence:.3f}")
    if abs(t.mean - 0.5) > 1e-9:
        failures.append("uniform prior is not centred at 0.5")

    kept_only = bl.BetaTrust()
    for _ in range(10):
        kept_only.update(True)
    broken_once = bl.BetaTrust()
    for _ in range(10):
        broken_once.update(True)
    broken_once.update(False, bl.DEFAULT_BETRAYAL_WEIGHT)
    print(f"    10 kept          -> mean={kept_only.mean:.3f} conf={kept_only.confidence:.3f}")
    print(f"    10 kept + 1 stab -> mean={broken_once.mean:.3f} conf={broken_once.confidence:.3f}")
    if not broken_once.mean < kept_only.mean:
        failures.append("a betrayal did not reduce trust")

    sym = bl.BetaTrust()
    for _ in range(10):
        sym.update(True)
    sym.update(False, 1.0)
    if not broken_once.mean < sym.mean:
        failures.append("betrayal weighting had no asymmetric effect")
    else:
        print(f"    asymmetry holds: weighted stab {broken_once.mean:.3f} "
              f"< unweighted stab {sym.mean:.3f}")

    if not kept_only.confidence > t.confidence:
        failures.append("confidence did not grow with evidence")

    # --- 3. synthetic game: England promises, then stabs France ---------
    print("[3] synthetic 3-power sequence:")
    m1 = msg("m1", "ENGLAND", "FRANCE", "I will support your move to Belgium, and I will not enter the Channel this year.",
             [{"commitment_type": "support", "text": "support F->BEL"}])
    m2 = msg("m2", "FRANCE", "ENGLAND", "Agreed. I will keep Burgundy empty in exchange for that support.",
             [{"commitment_type": "dmz", "text": "BUR empty"}])
    # A private channel France must never see.
    m3 = msg("m3", "ENGLAND", "GERMANY", "Ignore what I told Paris. I am taking the Channel and moving on Brest.",
             [{"commitment_type": "move", "text": "ENG->BRE"}])

    registry = iso.IsolationRegistry()
    for m in (m1, m2, m3):
        registry.register_message(m)

    stores["FRANCE"].observe_message("ENGLAND", "S1901M", m1)
    stores["ENGLAND"].observe_message("FRANCE", "S1901M", m1, sent=True)
    stores["ENGLAND"].observe_message("FRANCE", "S1901M", m2)
    stores["ENGLAND"].observe_message("GERMANY", "S1901M", m3, sent=True)
    stores["GERMANY"].observe_message("ENGLAND", "S1901M", m3)

    before = stores["FRANCE"].trust("ENGLAND")
    stores["FRANCE"].observe_public_orders("ENGLAND", "S1901M", ["F LON - ENG", "F EDI - NTH"])
    stores["FRANCE"].record_outcome(
        "ENGLAND", "S1901M", "m1", kept=False,
        stated="support F->BEL", actual="F LON - ENG",
    )
    after = stores["FRANCE"].trust("ENGLAND")
    print(f"    FRANCE trust in ENGLAND: {before:.3f} -> {after:.3f} (promise broken)")
    if not after < before:
        failures.append("recorded betrayal did not move trust")

    g_trust = stores["GERMANY"].trust("ENGLAND")
    print(f"    GERMANY trust in ENGLAND: {g_trust:.3f} (saw no betrayal -- correctly unmoved)")
    if abs(g_trust - 0.5) > 1e-6:
        failures.append("Germany's trust moved on evidence it never observed")

    pb = stores["FRANCE"].dyads["ENGLAND"].predicted_betrayal()["probability"]
    print(f"    FRANCE predicted_betrayal(ENGLAND) = {pb:.3f}")

    # --- 4. store cannot ingest a third party's private message ---------
    try:
        stores["FRANCE"].observe_message("ENGLAND", "S1901M", m3)
        failures.append("store ingested a message France was not party to")
        print("[4] third-party ingestion: NOT BLOCKED")
    except ValueError as exc:
        print(f"[4] third-party ingestion blocked: {str(exc)[:70]}...")

    # --- 5. clean contexts pass the gate --------------------------------
    print("[5] isolation gate on legitimate contexts:")
    clean = 0
    for observer in P:
        for subject in P:
            if subject == observer:
                continue
            ctx = stores[observer].context_for_prompt(subject)
            v = iso.scan(ctx, observer, registry)
            if v:
                failures.append(f"false positive for {observer}->{subject}: {v}")
            else:
                clean += 1
    print(f"    {clean} dyad contexts scanned clean, 0 false positives")

    for observer in P:
        v = iso.audit_store(stores[observer], registry)
        if v:
            failures.append(f"store audit flagged {observer}: {v}")
    print("    full-store audits clean for all 3 powers")

    # --- 6. THE DELIBERATE LEAK FIXTURE -- must fail --------------------
    print("[6] deliberate-leak fixtures (each MUST be caught):")

    leaked = stores["FRANCE"].context_for_prompt("ENGLAND")
    leaked["episodic"].append({
        "phase": "S1901M", "kind": "message_received",
        "message_id": "m3", "body": m3["body"],   # England->Germany, planted
    })
    v = iso.scan(leaked, "FRANCE", registry)
    if v:
        print(f"    caught planted private message: {v[0][:78]}...")
    else:
        print("    LEAK NOT CAUGHT -- planted private message")
        failures.append("gate missed a planted private message")

    try:
        iso.enforce(leaked, "FRANCE", registry)
        print("    enforce() did NOT raise")
        failures.append("enforce() failed to fail closed")
    except iso.IsolationViolation:
        print("    enforce() failed closed as designed")

    # Reformatted leak: whitespace and case changed, substance identical.
    sneaky = {"prompt": "  IGNORE WHAT I TOLD PARIS.   I AM TAKING THE CHANNEL AND MOVING ON BREST.  "}
    if iso.scan(sneaky, "FRANCE", registry):
        print("    caught reformatted leak (whitespace + case)")
    else:
        print("    LEAK NOT CAUGHT -- reformatted")
        failures.append("gate missed a whitespace/case-reformatted leak")

    # Leak buried in a nested structure rather than a top-level string.
    nested = {"turns": [{"notes": [{"deep": {"text": m3["body"]}}]}]}
    if iso.scan(nested, "FRANCE", registry):
        print("    caught leak nested inside a structure")
    else:
        print("    LEAK NOT CAUGHT -- nested")
        failures.append("gate missed a nested leak")

    # Germany IS entitled to m3 -- this must NOT be flagged.
    if iso.scan({"prompt": m3["body"]}, "GERMANY", registry):
        print("    FALSE POSITIVE: flagged Germany for its own message")
        failures.append("gate flagged an entitled viewer")
    else:
        print("    correctly silent for GERMANY (entitled to m3)")

    # --- 7. schema validation -------------------------------------------
    for observer in P:
        stores[observer].validate()
    print(f"[7] all 3 stores validate against belief schema v{bl.SCHEMA_VERSION}")

    # Untrusted belief JSON -- the schema's actual threat model. A live store keeps
    # its own invariants, so this is what protects against state loaded from disk.
    hostile = {
        "schema_version": "1.0.0",
        "observer": "FRANCE",
        "semantic": {"treaties_believed": []},
        "dyads": [{
            "subject": "ENGLAND",
            "trust": {"alpha": -1.0, "beta": 3.0, "mean": -0.5, "confidence": 0.9},
            "episodic": [], "corrections": [],
        }],
    }
    if bl.validate_export(hostile, strict=False):
        print("    negative alpha in external JSON rejected as designed")
    else:
        failures.append("schema accepted a negative Beta parameter from outside")

    hostile2 = {
        "schema_version": "1.0.0", "observer": "FRANCE",
        "semantic": {"treaties_believed": []},
        "dyads": [{"subject": "FRANCE",
                   "trust": {"alpha": 1.0, "beta": 1.0, "mean": 0.5, "confidence": 0.4},
                   "episodic": [], "corrections": []}],
    }
    # Schema cannot express observer != subject, so this is alignment's job.
    if not bl.validate_export(hostile2, strict=False):
        print("    note: self-dyad passes schema (structural check covers it)")

    # Degenerate: not serializable at all, so it must fail legibly rather than
    # with a ZeroDivisionError pointing at arithmetic instead of the real problem.
    degenerate = bl.BetaTrust(alpha=-1.0, beta=1.0)
    try:
        degenerate.mean
        print("    degenerate Beta did NOT raise")
        failures.append("degenerate Beta parameters produced a value")
    except ValueError as exc:
        if "corrupt" in str(exc):
            print(f"    degenerate Beta raises legibly: {str(exc)[:58]}...")
        else:
            failures.append(f"degenerate Beta raised the wrong error: {exc}")
    except ZeroDivisionError:
        print("    degenerate Beta raised ZeroDivisionError")
        failures.append("degenerate Beta still fails opaquely")

    # --- 8. snapshots drop into the turn log unchanged -------------------
    snaps = [s for observer in P for s in stores[observer].snapshot()]
    saved = __import__("test_turn_log").play(seed=5, phases=2)
    log = tl.build_log(
        saved, seed=5, arm="belief_on",
        llm_powers=P, scripted_powers=[], models={"negotiator": "claude-sonnet-5"},
        turns=tl.turns_from_saved_game(saved),
    )
    log["turns"][0]["beliefs"] = snaps
    tl.validate(log)
    problems = tl.check_alignment(log)
    print(f"[8] {len(snaps)} belief snapshots embedded in a turn log: "
          f"schema OK, alignment {'clean' if not problems else problems}")
    if problems:
        failures.append(f"belief snapshots broke turn-log alignment: {problems}")

    # --- 9. the D4 seam --------------------------------------------------
    on = bl.make_store("belief_on", "FRANCE", P)
    off = bl.make_store("belief_off", "FRANCE", P)
    print("[9] ablation seam:")
    print(f"    both satisfy BeliefStore protocol: "
          f"{isinstance(on, bl.BeliefStore) and isinstance(off, bl.BeliefStore)}")
    if not (isinstance(on, bl.BeliefStore) and isinstance(off, bl.BeliefStore)):
        failures.append("an implementation does not satisfy the BeliefStore protocol")

    for store in (on, off):
        store.observe_message("ENGLAND", "S1901M", m1)
        store.record_outcome("ENGLAND", "S1901M", "m1", kept=False)
    print(f"    after identical betrayal: on={on.trust('ENGLAND'):.3f}  "
          f"off={off.trust('ENGLAND'):.3f}")
    if on.trust("ENGLAND") >= 0.5:
        failures.append("belief_on arm did not learn from betrayal")
    if off.trust("ENGLAND") != 0.5:
        failures.append("belief_off arm was not inert")

    off_snap = off.snapshot()
    if len(off_snap) != len([p for p in P if p != "FRANCE"]):
        failures.append("stub snapshot shape differs from real store")
    else:
        print("    stub emits same snapshot shape -- arms differ only in behaviour")

    print()
    if failures:
        print("GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"GATE PASSED - belief store v{bl.SCHEMA_VERSION} and isolation gate hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
