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

from . import agents as ag
from . import belief as bl
from . import bots, engine, isolation as iso, turn_log as tl
from .llm import LLMRequest, MockProvider, RecordingProvider, Router


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
    # Phase 2. When use_llm is False the runner behaves exactly as in Phase 1, which
    # is what keeps the no-cost path available for CI and for the deterministic spine.
    use_llm: bool = False
    routing: dict | str | None = None
    provider: object | None = None      # force a provider (mock / replay)
    effort: str | None = "medium"

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

        self.llm_calls: list[dict] = []
        self.provider_name = "none"
        self.router = None
        self.negotiator = self.evaluator = self.decider = None
        if config.use_llm:
            provider = config.provider if config.provider is not None else MockProvider()
            self.provider_name = getattr(provider, "name", type(provider).__name__)
            self.router = Router(config.routing, force_provider=provider)
            self.negotiator = ag.Negotiator(self.router, effort=config.effort)
            self.evaluator = ag.BeliefEvaluator(self.router, effort=config.effort)
            self.decider = ag.OrderDecider(self.router, effort=config.effort)

    def _record(self, result, phase: str) -> None:
        self.llm_calls.append(result.response.as_log_entry(result.request, phase))

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
        if self.cfg.use_llm:
            return self._negotiate_llm(phase)

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

    def _ingest_message(self, phase: str, message: dict, commitment_province: str | None) -> None:
        """Register a message, give it to both parties, and open it for checking."""
        sender, recipient = message["sender"], message["recipient"]
        self.registry.register_message(message)
        self.stores[sender].observe_message(recipient, phase, message, sent=True)
        self.stores[recipient].observe_message(sender, phase, message)
        if commitment_province:
            self._open_commitments.setdefault(phase, []).append({
                "message_id": message["message_id"], "sender": sender,
                "recipient": recipient, "province": commitment_province,
            })

    def _negotiate_llm(self, phase: str) -> list[dict]:
        """Pipeline steps 2 and 4: LLM negotiation, then independent belief scoring.

        The two halves are separate model calls with separate contexts on purpose.
        The Negotiator drafts from its own goals; the Evaluator scores the incoming
        message knowing nothing of the recipient's plans. See agents.py.
        """
        messages: list[dict] = []
        powers = [p for p in self.cfg.all_powers if p in self.cfg.llm_powers]

        for sender in powers:
            result = self.negotiator.draft(
                self.game, sender, self.stores[sender], list(self.cfg.all_powers)
            )
            self._record(result, phase)

            for i, drafted in enumerate(result.data.get("messages", []) or []):
                recipient = drafted.get("recipient")
                # A model may address a power that is not in this game, or itself.
                if recipient not in self.cfg.all_powers or recipient == sender:
                    continue
                intents = drafted.get("stated_intent", []) or []
                message = {
                    "message_id": f"{phase}-{sender[:3]}{recipient[:3]}-{i}",
                    "sender": sender,
                    "recipient": recipient,
                    "body": drafted.get("body", ""),
                    "stated_intent": intents,
                }

                province = None
                for intent in intents:
                    provinces = intent.get("concerns_provinces") or []
                    if provinces:
                        province = provinces[0]
                        break

                self._ingest_message(phase, message, province)

                # Belief-update gate: the recipient's Evaluator scores it.
                scored = self.evaluator.score(
                    self.game, recipient, sender, message, self.stores[recipient]
                )
                self._record(scored, phase)
                message["evaluation"] = {
                    "predicted_truthfulness": float(
                        scored.data.get("predicted_truthfulness", 0.5)
                    ),
                    "confidence": float(scored.data.get("confidence", 0.0)),
                    "rationale": scored.data.get("rationale", ""),
                    "evaluator_call_id": scored.response.call_id,
                }
                messages.append(message)

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
        legal = engine.possible_orders(self.game)
        flat_legal = {o for opts in legal.values() for o in opts}

        for power in engine.powers_in_order(self.game):
            if power not in self.cfg.all_powers:
                continue

            entry: dict = {"power": power}
            use_llm = self.cfg.use_llm and power in self.cfg.llm_powers

            if use_llm:
                result = self.decider.decide(
                    self.game, power, self.stores[power], list(self.cfg.all_powers)
                )
                self._record(result, phase)
                orders = list(result.data.get("orders", []) or [])
                if not result.tool_called:
                    entry["no_decision"] = True
                if result.data.get("rationale"):
                    entry["rationale"] = result.data["rationale"]
                if result.data.get("broken_commitments"):
                    entry["broken_commitments"] = list(result.data["broken_commitments"])
            else:
                orders = self._policy_for(power).orders(self.game, power, self.rng)

            # Orders-valid gate (pipeline step 6). Scripted policies draw from the
            # legal list and never trip it; LLM orders routinely do, which is why
            # the retry count is logged as a reliability metric rather than hidden.
            retries = 0
            invalid = [o for o in orders if o not in flat_legal]
            if invalid:
                retries = 1
                orders = [o for o in orders if o in flat_legal]
            # An empty order list is CORRECT when a power has nothing orderable --
            # an adjustment phase where it neither gained nor lost centres, say.
            # Counting that as a failed decision made invalid_order_retries report
            # reliability problems that did not happen, which is worse than not
            # measuring it at all.
            orderable = engine.orderable_locations(self.game, power)
            if not orders and orderable:
                # It had something to order and produced nothing usable. Fall back,
                # or the adjudicator treats it as civil disorder and the game drifts
                # for reasons unrelated to the belief layer.
                orders = bots.get_policy("hold").orders(self.game, power, self.rng)
                if use_llm:
                    retries += 1

            self.game.set_orders(power, orders)
            entry["orders"] = sorted(orders)
            entry["invalid_order_retries"] = retries
            if use_llm:
                entry["decision_call_id"] = result.response.call_id
            decisions.append(entry)
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
            models=self.router.describe() if self.router else self.cfg.models,
            provider=self.provider_name,
            turns=self.turns,
            max_phases=self.cfg.max_phases,
            llm_calls=self.llm_calls if self.cfg.use_llm else None,
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
