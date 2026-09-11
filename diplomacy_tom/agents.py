"""The three LLM roles: Negotiator, BeliefEvaluator, OrderDecider.

The Generator/Evaluator split (ARCHITECTURE.md section 4.1) is the point of this
module, and it is structural rather than instructional:

* The **Negotiator** reasons from its own power's goals and drafts messages. It is
  the Generator, and it is allowed to be self-serving.
* The **BeliefEvaluator** scores how truthful a counterpart's message looks. It sees
  ONLY that counterpart's words and public order record. It never sees the
  Negotiator's private strategy, its goals, or its planned orders -- so a confident
  framing cannot talk it into trusting an ally, exactly as Meridian's Evaluator
  cannot be talked into approving bad code.
* The **OrderDecider** combines board position with belief state and chooses orders,
  including whether to honour or break a stated commitment.

The isolation this relies on is enforced upstream: a belief store holds no strategy
of its own, only what its observer has seen of others, so there is no path by which
the Negotiator's reasoning could reach the Evaluator. `evaluator_context()` below
narrows that further and is asserted in tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import engine
from .llm import LLMRequest, LLMResponse, Router

POWER_ENUM = list(engine.POWERS)

# --------------------------------------------------------------------------
# Structured output contracts
#
# Tool schemas rather than free-text JSON: strict tool use guarantees the arguments
# validate, and a malformed stated_intent would degrade the eval silently rather
# than failing loudly. additionalProperties:false + required is what makes `strict`
# legal.
# --------------------------------------------------------------------------

NEGOTIATION_TOOL = {
    "name": "send_messages",
    "description": "Send negotiation messages to other powers this phase.",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["messages"],
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["recipient", "body", "stated_intent"],
                    "properties": {
                        "recipient": {"type": "string", "enum": POWER_ENUM},
                        "body": {"type": "string"},
                        "stated_intent": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["commitment_type", "text"],
                                "properties": {
                                    "commitment_type": {
                                        "type": "string",
                                        "enum": ["move", "support", "hold", "dmz",
                                                 "non_aggression", "alliance", "none"],
                                    },
                                    "text": {"type": "string"},
                                    "concerns_provinces": {
                                        "type": "array", "items": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

EVALUATION_TOOL = {
    "name": "score_message",
    "description": "Judge how likely this power is to do what it just said.",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["predicted_truthfulness", "confidence", "rationale"],
        "properties": {
            # NOTE: no `minimum`/`maximum` here. Anthropic strict tool use rejects
            # numeric range keywords ("For 'number' type, properties maximum, minimum
            # are not supported"), so the bound is stated in the description and
            # enforced by _unit() on the way in. The schema was never the real
            # guarantee anyway — a model can always return 1.5.
            "predicted_truthfulness": {
                "type": "number",
                "description": "Probability in [0,1] that this commitment is kept.",
            },
            "confidence": {
                "type": "number",
                "description": "How much evidence supports the judgement, in [0,1].",
            },
            "rationale": {"type": "string"},
        },
    },
}

ORDERS_TOOL = {
    "name": "submit_orders",
    "description": "Submit this power's orders for the current phase.",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["orders"],
        "properties": {
            "orders": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
            "broken_commitments": {"type": "array", "items": {"type": "string"}},
        },
    },
}

# --------------------------------------------------------------------------
# Prompts
#
# The cacheable half is written to be byte-identical across every call in a run:
# rules, the output contract, no timestamps, no per-call ids. Everything volatile
# goes in the message body, after the breakpoint. See ARCHITECTURE.md section 5.
# --------------------------------------------------------------------------

RULES_PREFIX = """You are playing Diplomacy (standard map, 1901 start).

Rules that matter here:
- Orders are secret until adjudication, then fully public.
- Units are Armies (A) and Fleets (F). Order syntax: "A PAR - BUR", "F BRE S A PAR - PIC", "A MUN H".
- Supply centres are captured in Autumn. 18 centres wins.
- Nothing binds a power to its word. Promises are information, not contracts.

You negotiate in private, bilateral channels. Other powers cannot see what you say
to anyone else, and you cannot see what they say to each other."""

NEGOTIATOR_PREFIX = """OUTPUT CONTRACT - THIS OVERRIDES EVERYTHING BELOW.

Your entire response must be a single send_messages tool call. Do not narrate your
reasoning, do not write analysis, do not write any text before or after the call.
Think silently, then emit the call. Prose outside the tool call is a failure.

---
""" + RULES_PREFIX + """

You are a negotiator. Draft private messages advancing your power's position.
Be concrete: name provinces and units. A message that commits to nothing is wasted.
You may deceive, but remember every order becomes public after adjudication, and
counterparts remember.

MAKE COMMITMENTS THAT CAN BE TESTED. Pledge about provinces your units can
actually reach this turn. "I will not enter the Channel" means nothing if you have
no fleet that can get there, and a promise nobody could break is not a promise.
Name the province in concerns_provinces.

BREVITY IS REQUIRED. Write at most 3 messages this phase. Each body must be one or
two sentences, under 40 words. Do not explain your reasoning, do not restate the
board, do not write preamble. Return messages via the send_messages tool."""

EVALUATOR_PREFIX = """OUTPUT CONTRACT - THIS OVERRIDES EVERYTHING BELOW.

Your entire response must be a single score_message tool call. Do not narrate your
reasoning, do not write analysis, do not write any text before or after the call.
Think silently, then emit the call. Prose outside the tool call is a failure.

---
""" + RULES_PREFIX + """

You are a belief evaluator. You judge whether a power will do what it says.

You see only: what this power has said to the power you serve, and its publicly
adjudicated orders. You do NOT see your own side's plans, goals, or orders -- and
you must not speculate about them. Judge the counterpart on its own record alone:
does this message fit what it has actually done, and is it plausible given its
board position?

A promise costs nothing to make and nothing to keep when there is no temptation to
break it. Weigh the computed opportunity data above the message text: a pledge with
a concrete, uncontested capture available (would_be_a_free_gain) is a real test --
low truthfulness is warranted unless their record says otherwise. A pledge about a
province with no opportunity is nearly unfalsifiable and should sit near your prior
regardless of how sincere the wording sounds.

predicted_truthfulness is the probability it keeps this specific commitment.
confidence is how much evidence you have. Little history means low confidence, not
a middling score.

BREVITY IS REQUIRED. The rationale must be under 30 words: state the decisive
evidence and stop. Return your judgement via the score_message tool."""

DECIDER_PREFIX = """OUTPUT CONTRACT - THIS OVERRIDES EVERYTHING BELOW.

Your entire response must be a single submit_orders tool call. Do not narrate your
reasoning, do not write analysis, do not write any text before or after the call.
Think silently, then emit the call. Prose outside the tool call is a failure.

---
""" + RULES_PREFIX + """

You choose orders. Weigh board position against what you believe other powers will
do. You are not obliged to honour commitments -- betrayal is legitimate when the
position warrants it -- but list any commitment you are breaking in
broken_commitments so it is recorded.

Every order must be legal. Choose only from the legal moves supplied.

Diplomacy has three kinds of phase, and they take different orders:
- Movement (S1901M, F1901M): one order per unit - move, hold, support or convoy.
- Retreat (S1901R, F1901R): dislodged units retreat or disband.
- Adjustment (W1901A): BUILD new units in your home centres if you gained centres,
  or DISBAND if you lost them. These are not moves. You may also be able to do
  nothing at all, in which case return an empty order list.

The legal-order list supplied below is authoritative for whichever phase this is.
Copy strings from it verbatim. Never invent an order, never reformat one, and never
submit a movement order during an adjustment phase.

BREVITY IS REQUIRED. The rationale must be under 25 words.
Return orders via the submit_orders tool."""


def _board_summary(game, power: str) -> str:
    units = {p: sorted(game.get_units(p)) for p in engine.powers_in_order(game)}
    centers = {p: sorted(game.get_centers(p)) for p in engine.powers_in_order(game)}
    return json.dumps(
        {"phase": game.get_current_phase(), "you": power,
         "units": units, "centers": centers},
        sort_keys=True, indent=1,
    )


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def _no_orders(data) -> bool:
    """True when the model did not actually submit orders.

    Checking `data is None` is not enough: a model that answers in prose can still
    come back as an empty dict, which is not None, so the guard never fired and the
    non-decision was silently converted into a hold. Absence of the `orders` key is
    the real signal.
    """
    return not isinstance(data, dict) or "orders" not in data


def _unit(value, default: float = 0.5) -> float:
    """Coerce a model-supplied probability into [0,1].

    Belief maths and the turn-log schema both require the unit interval, and a model
    that returns 1.5 or "0.8" must not be able to poison the belief store or fail
    validation three phases later.
    """
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


@dataclass
class AgentResult:
    """A role's output plus the call record, so the runner can log both."""

    data: dict
    request: LLMRequest
    response: LLMResponse
    tool_called: bool = True     # False when the model answered in prose instead


class Negotiator:
    """The Generator. Reasons from its own power's interests."""

    role = "negotiator"

    def __init__(self, router: Router, *, effort: str | None = "medium") -> None:
        self.router = router
        self.effort = effort

    def draft(self, game, power: str, store, counterparts: list[str]) -> AgentResult:
        views = {
            other: store.context_for_prompt(other)
            for other in counterparts if other != power
        }
        body = (
            f"Board:\n{_board_summary(game, power)}\n\n"
            f"What you believe about each counterpart (trust 0=expects betrayal, "
            f"1=fully trusted):\n{json.dumps(views, sort_keys=True, indent=1)}\n\n"
            f"Draft messages for this phase. You need not write to everyone."
        )
        request = LLMRequest(
            role=self.role,
            cacheable_system=NEGOTIATOR_PREFIX,
            messages=[{"role": "user", "content": body}],
            tool=NEGOTIATION_TOOL,
            effort=self.effort,
            max_tokens=1600,
            mock_hint={
                "sender": power,
                "counterparts": [c for c in counterparts if c != power],
                # Reachable provinces only, so mock-generated commitments are
                # falsifiable too and the eval path is exercised end to end.
                "provinces": sorted(
                    p for p in game.map.scs if engine.can_reach(game, power, p)
                ) or sorted(game.map.scs),
            },
        )
        response = self.router.complete(request)
        raw = response.data if isinstance(response.data, dict) else {}
        if "messages" not in raw:
            return AgentResult({"messages": []}, request, response, tool_called=False)
        return AgentResult(raw, request, response, tool_called=True)


def evaluator_context(store, subject: str) -> dict:
    """Exactly what the Evaluator is allowed to see about `subject`.

    Narrower than the Negotiator's view on purpose. Messages the observer SENT are
    stripped: they are the Generator's own words, and letting the Evaluator read its
    own side's framing is precisely the contamination this split exists to prevent.
    What remains is the counterpart's words, its public orders, and the dyad's
    correction history.
    """
    full = store.context_for_prompt(subject)
    return {
        "subject": subject,
        "their_messages_to_you": [
            e for e in full.get("episodic", []) if e.get("kind") == "message_received"
        ],
        "their_public_orders": [
            e for e in full.get("episodic", []) if e.get("kind") == "public_orders"
        ],
        "promise_record": full.get("corrections", []),
        "current_trust": full.get("trust"),
    }


class BeliefEvaluator:
    """Structurally separate from the Negotiator. See module docstring."""

    role = "belief_evaluator"

    def __init__(self, router: Router, *, effort: str | None = "medium") -> None:
        self.router = router
        self.effort = effort

    def score(self, game, observer: str, subject: str, message: dict, store) -> AgentResult:
        # What a human player would actually use to judge this: is breaking THIS
        # pledge currently tempting? Computed per pledged province rather than left
        # for the model to infer from raw units/centers alone.
        pressure = [
            engine.commitment_pressure(game, subject, prov)
            for intent in (message.get("stated_intent") or [])
            for prov in (intent.get("concerns_provinces") or [])
        ]
        body = (
            f"Power under judgement: {subject}\n\n"
            f"Their message just now:\n{json.dumps(message.get('body', ''))}\n\n"
            f"Their stated commitment:\n"
            f"{json.dumps(message.get('stated_intent', []), sort_keys=True)}\n\n"
            f"Concrete opportunity to break it, computed from the board (not their "
            f"claim):\n{json.dumps(pressure, sort_keys=True, indent=1)}\n\n"
            f"Their record with you:\n"
            f"{json.dumps(evaluator_context(store, subject), sort_keys=True, indent=1)}\n\n"
            f"Board:\n{_board_summary(game, subject)}"
        )
        request = LLMRequest(
            role=self.role,
            cacheable_system=EVALUATOR_PREFIX,
            messages=[{"role": "user", "content": body}],
            tool=EVALUATION_TOOL,
            effort=self.effort,
            max_tokens=500,
        )
        response = self.router.complete(request)
        raw = response.data if isinstance(response.data, dict) else {}
        called = "predicted_truthfulness" in raw
        if not called:
            # Substituting 0.5/0.0 here is what made 47% of one run's "evaluator
            # scores" constants rather than model output, while looking entirely
            # plausible in the log. The caller is told instead.
            return AgentResult({}, request, response, tool_called=False)
        data = {
            "predicted_truthfulness": _unit(raw.get("predicted_truthfulness"), 0.5),
            "confidence": _unit(raw.get("confidence"), 0.0),
            "rationale": str(raw.get("rationale", "") or "")[:2000],
        }
        return AgentResult(data, request, response, tool_called=True)


class OrderDecider:
    """Combines board evaluation with belief state to choose orders."""

    role = "decision"

    def __init__(self, router: Router, *, effort: str | None = "medium") -> None:
        self.router = router
        self.effort = effort

    def decide(self, game, power: str, store, counterparts: list[str]) -> AgentResult:
        legal = engine.possible_orders(game)
        locations = engine.orderable_locations(game, power)
        legal_here = {loc: legal.get(loc, []) for loc in locations}
        beliefs = {
            other: {
                "trust": round(store.trust(other), 3),
            }
            for other in counterparts if other != power
        }
        body = (
            f"Board:\n{_board_summary(game, power)}\n\n"
            f"Your beliefs about the others:\n{json.dumps(beliefs, sort_keys=True)}\n\n"
            f"Legal orders available to you, by location:\n"
            f"{json.dumps(legal_here, sort_keys=True, indent=1)}\n\n"
            f"Submit one order per location. Choose only from the legal orders above."
        )
        request = LLMRequest(
            role=self.role,
            cacheable_system=DECIDER_PREFIX,
            messages=[{"role": "user", "content": body}],
            tool=ORDERS_TOOL,
            effort=self.effort,
            max_tokens=900,
            mock_hint={
                "legal_orders": legal_here,
                "trust": {k: v["trust"] for k, v in beliefs.items()},
            },
        )
        response = self.router.complete(request)
        if _no_orders(response.data):
            # The model wrote prose instead of calling the tool -- typically
            # "Let me analyze the situation..." until it hit max_tokens. One terse
            # retry, then give up loudly rather than pretending it held.
            retry = LLMRequest(
                role=self.role,
                cacheable_system=DECIDER_PREFIX,
                system="Respond ONLY by calling submit_orders. Do not write any "
                       "analysis, preamble or explanation before the call.",
                messages=request.messages,
                tool=ORDERS_TOOL,
                effort=self.effort,
                max_tokens=request.max_tokens,
                mock_hint=request.mock_hint,
            )
            response = self.router.complete(retry)
            request = retry
        if _no_orders(response.data):
            return AgentResult({"orders": []}, request, response, tool_called=False)
        return AgentResult(response.data, request, response, tool_called=True)
