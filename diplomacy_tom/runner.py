"""Phase 1: the deterministic spine.

Runs a full game with scripted policies, driving every gate in the turn-processing
pipeline (ARCHITECTURE.md section 5) and emitting a validated turn log.

No LLM calls. The point is that the whole skeleton -- game loop, belief updates,
isolation enforcement, log assembly, schema validation -- is exercised and proven
before any of it depends on a model. Phase 2 replaces the negotiation and decision
layers behind the interfaces already in place here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import belief as bl
from . import bots, engine, isolation as iso, turn_log as tl


@dataclass
class GameConfig:
    seed: int = 42
    arm: str = "belief_on"
    max_phases: int = 40
    llm_powers: tuple[str, ...] = ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY")
    scripted_powers: tuple[str, ...] = ("ITALY", "RUSSIA", "TURKEY")
    # Phase 1 has no LLM, so the "llm" powers run a policy too. Phase 2 swaps this
    # for real negotiators without touching the loop.
    llm_stand_in: str = "greedy_expansion"
    scripted_policy: str = "random"
    models: dict[str, str] = field(
        default_factory=lambda: {"negotiator": "none-phase1", "belief_evaluator": "none-phase1"}
    )

    @property
    def all_powers(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.llm_powers) | set(self.scripted_powers)))


class GameRunner:
    """Drives one game end to end and produces a turn log."""

    def __init__(self, config: GameConfig) -> None:
        self.cfg = config
        self.rng = random.Random(config.seed)
        self.game = engine.new_game()
        self.registry = iso.IsolationRegistry()
        self.stores = {
            p: bl.make_store(config.arm, p, config.all_powers)
            for p in config.all_powers
        }
        self.turns: list[dict] = []
        # Commitments awaiting post-adjudication check, keyed by phase.
        self._open_commitments: dict[str, list[dict]] = {}

    # -- policies -------------------------------------------------------

    def _policy_for(self, power: str):
        name = (
            self.cfg.llm_stand_in if power in self.cfg.llm_powers
            else self.cfg.scripted_policy
        )
        return bots.get_policy(name)

    # -- pipeline steps -------------------------------------------------

    def _negotiate(self, phase: str) -> list[dict]:
        """Pipeline step 2, scripted.

        Phase 1 emits one synthetic non-aggression pledge per ordered pair of LLM
        powers, so the belief and correction machinery has real traffic to process.
        Phase 2 replaces the body and stated_intent with model output; everything
        downstream is unchanged.
        """
        messages: list[dict] = []
        powers = [p for p in self.cfg.all_powers if p in self.cfg.llm_powers]
        for sender in powers:
            for recipient in powers:
                if sender == recipient:
                    continue
                if self.rng.random() > 0.35:
                    continue
                province = self.rng.choice(sorted(self.game.map.scs))
                mid = f"{phase}-{sender[:3]}{recipient[:3]}-{len(messages)}"
                message = {
                    "message_id": mid,
                    "sender": sender,
                    "recipient": recipient,
                    "body": (
                        f"{sender} to {recipient}: I will not move on {province} "
                        f"during {phase}, provided you do the same."
                    ),
                    "stated_intent": [{
                        "commitment_type": "non_aggression",
                        "text": f"no move on {province}",
                        "concerns_provinces": [province],
                    }],
                }
                messages.append(message)
                self.registry.register_message(message)

                # Both parties record it; nobody else can (store enforces this).
                self.stores[sender].observe_message(recipient, phase, message, sent=True)
                self.stores[recipient].observe_message(sender, phase, message)

                self._open_commitments.setdefault(phase, []).append({
                    "message_id": mid, "sender": sender,
                    "recipient": recipient, "province": province,
                })
        return messages

    def _assemble_and_gate(self, phase: str) -> None:
        """Pipeline step 1: the context-assembly gate.

        Runs on every dyad context every phase. In Phase 1 the contexts are not sent
        anywhere, but the gate runs anyway -- it is cheap, and a leak introduced now
        should fail now rather than the first time a prompt is built.
        """
        for observer in self.cfg.all_powers:
            store = self.stores[observer]
            for subject in self.cfg.all_powers:
                if subject == observer:
                    continue
                iso.enforce(store.context_for_prompt(subject), observer, self.registry)

    def _collect_orders(self, phase: str) -> list[dict]:
        """Pipeline steps 5 and 6."""
        decisions = []
        for power in engine.powers_in_order(self.game):
            if power not in self.cfg.all_powers:
                continue
            orders = self._policy_for(power).orders(self.game, power, self.rng)
            retries = 0
            # Orders-valid gate. Policies draw from the legal-move list so this
            # should never fire; it exists because Phase 2's LLM orders will.
            legal = engine.possible_orders(self.game)
            flat_legal = {o for opts in legal.values() for o in opts}
            invalid = [o for o in orders if o not in flat_legal]
            while invalid and retries < 3:
                retries += 1
                orders = [o for o in orders if o in flat_legal]
                invalid = []
            self.game.set_orders(power, orders)
            decisions.append({
                "power": power,
                "orders": sorted(orders),
                "invalid_order_retries": retries,
            })
        return decisions

    def _revise_beliefs(self, phase: str) -> list[dict]:
        """Pipeline step 8: diff stated intent against what actually happened."""
        corrections: list[dict] = []
        resolved = engine.public_orders(self.game, phase)

        for commitment in self._open_commitments.pop(phase, []):
            sender = commitment["sender"]
            recipient = commitment["recipient"]
            province = commitment["province"]
            actual = resolved.get(sender, [])
            # Did the promiser move on the province it pledged to leave alone?
            broke = any(
                o.rsplit(" - ", 1)[-1].split("/")[0] == province
                for o in actual if " - " in o
            )
            observer_store = self.stores[recipient]
            observer_store.record_outcome(
                sender, phase, commitment["message_id"], kept=not broke,
                stated=f"no move on {province}",
                actual="; ".join(actual[:3]) if actual else "(no orders)",
            )
            dyad_corrections = getattr(observer_store, "dyads", {})
            if dyad_corrections:
                last = dyad_corrections[sender].corrections[-1]
                corrections.append({
                    "observer": recipient, "subject": sender,
                    "message_id": commitment["message_id"], "kept": not broke,
                    "stated": last["stated"], "actual": last["actual"],
                    "trust_before": last["trust_before"],
                    "trust_after": last["trust_after"],
                })
            else:  # stub store keeps no corrections
                corrections.append({
                    "observer": recipient, "subject": sender,
                    "message_id": commitment["message_id"], "kept": not broke,
                })

        # Adjudicated orders are public -- every power may observe them.
        for observer in self.cfg.all_powers:
            for subject, orders in resolved.items():
                if subject == observer or subject not in self.cfg.all_powers:
                    continue
                self.stores[observer].observe_public_orders(subject, phase, orders)

        return corrections

    # -- main loop ------------------------------------------------------

    def run(self) -> dict:
        while not self.game.is_game_done and len(self.turns) < self.cfg.max_phases:
            phase = self.game.get_current_phase()
            board = engine.board_hash(self.game)

            messages = self._negotiate(phase)
            self._assemble_and_gate(phase)

            snapshots = [
                s for p in self.cfg.all_powers for s in self.stores[p].snapshot()
            ]
            decisions = self._collect_orders(phase)

            self.game.process()

            corrections = self._revise_beliefs(phase)
            for store in self.stores.values():
                store.end_phase()

            self.turns.append({
                "phase": phase,
                "board_hash": board,
                "messages": messages,
                "beliefs": snapshots,
                "decisions": decisions,
                "corrections": corrections,
            })

        saved = engine.export_game(self.game)
        log = tl.build_log(
            saved,
            seed=self.cfg.seed,
            arm=self.cfg.arm,
            llm_powers=self.cfg.llm_powers,
            scripted_powers=self.cfg.scripted_powers,
            models=self.cfg.models,
            turns=self.turns,
            max_phases=self.cfg.max_phases,
        )
        tl.validate(log)
        problems = tl.check_alignment(log)
        if problems:
            raise ValueError(
                "turn log failed structural alignment:\n  " + "\n  ".join(problems)
            )
        return log


def run_game(**kwargs) -> dict:
    return GameRunner(GameConfig(**kwargs)).run()
