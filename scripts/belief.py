"""Power-indexed belief store -- the Theory of Mind core.

One store instance belongs to exactly one observer power. That is the isolation
boundary, and it is enforced by construction: a store physically cannot hold another
power's private channel, because there is no method that would put it there. The
isolation gate (isolation.py) is the second line of defence, checking assembled
prompts rather than trusting this invariant.

Trust is a Beta posterior over promise-keeping rather than a scalar with an ad-hoc
update rule. Conjugate updates are exact and cheap, and confidence falls out of the
distribution instead of being bolted on -- which the calibration metric in Phase 4
needs and a scalar would have forced us to retrofit.

The BeliefStore protocol is the D4 injection seam. Nothing in the negotiation or
decision layer may reference a concrete implementation; the ablation swaps
BayesianBeliefStore for StubBeliefStore and changes nothing else.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "belief.schema.json"

POWERS = (
    "AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY",
)

# A broken promise is stronger evidence than a kept one. Diplomacy trust is
# asymmetric: alliances take many turns to build and one stab to destroy, and a model
# that treats the two symmetrically will lag every betrayal it sees.
DEFAULT_BETRAYAL_WEIGHT = 2.0

# Beta(1,1) -- uniform. Deliberately agnostic: the agent starts with no opinion about
# whether a counterpart is trustworthy, which is the honest prior for turn one.
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0

# Per-phase pull of the posterior back toward the prior, so ancient evidence stops
# dominating a long game. 1.0 disables it.
DEFAULT_DECAY = 0.98


def _schema_validator() -> Draft202012Validator:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return Draft202012Validator(json.load(fh))


def validate_export(data: dict, *, strict: bool = True) -> list[str]:
    """Validate belief-store JSON against the schema.

    This is the entry point for belief state arriving from OUTSIDE the process --
    loaded from disk, or reconstructed from a turn log. A live BayesianBeliefStore
    maintains its own invariants and fails fast on corruption (see
    BetaTrust._check_domain), so the schema is not defending against this module; it
    is defending against untrusted data that claims to be belief state.
    """
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(_schema_validator().iter_errors(data),
                        key=lambda e: list(e.absolute_path))
    ]
    if errors and strict:
        raise ValueError(
            f"belief state failed schema validation ({len(errors)} error(s)):\n  "
            + "\n  ".join(errors)
        )
    return errors


@dataclass
class BetaTrust:
    """Posterior over 'will this power keep its word?'"""

    alpha: float = PRIOR_ALPHA
    beta: float = PRIOR_BETA
    observations: int = 0

    def _check_domain(self) -> None:
        """A Beta is only defined for alpha > 0 and beta > 0.

        Guarded explicitly because the derived statistics otherwise fail with an
        opaque ZeroDivisionError on corrupt state, which points at arithmetic rather
        than at the actual problem.
        """
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError(
                f"Beta parameters must be positive, got alpha={self.alpha}, "
                f"beta={self.beta} -- belief state is corrupt"
            )

    @property
    def mean(self) -> float:
        self._check_domain()
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        self._check_domain()
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def confidence(self) -> float:
        """1 - 2*sd, clamped to [0,1].

        The maximum standard deviation of a Beta is 0.5, so this maps a maximally
        uncertain posterior to 0 and a sharply peaked one toward 1. Derived from the
        distribution rather than an arbitrary observation-count threshold.
        """
        return max(0.0, min(1.0, 1.0 - 2.0 * math.sqrt(self.variance)))

    def update(self, kept: bool, weight: float = 1.0) -> None:
        if weight <= 0:
            raise ValueError("evidence weight must be positive")
        if kept:
            self.alpha += weight
        else:
            self.beta += weight
        self.observations += 1

    def decay(self, factor: float) -> None:
        """Pull toward the prior without discarding accumulated evidence."""
        if not 0 < factor <= 1:
            raise ValueError("decay factor must be in (0, 1]")
        self.alpha = PRIOR_ALPHA + (self.alpha - PRIOR_ALPHA) * factor
        self.beta = PRIOR_BETA + (self.beta - PRIOR_BETA) * factor

    def as_dict(self) -> dict:
        return {
            "alpha": round(self.alpha, 6),
            "beta": round(self.beta, 6),
            "mean": round(self.mean, 6),
            "confidence": round(self.confidence, 6),
            "observations": self.observations,
        }


@dataclass
class Dyad:
    """What one observer believes about one subject."""

    subject: str
    trust: BetaTrust = field(default_factory=BetaTrust)
    episodic: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    estimated_goals: list[str] = field(default_factory=list)
    estimated_alliances: list[dict] = field(default_factory=list)

    def predicted_betrayal(self) -> dict:
        """Probability the subject breaks its next commitment.

        Phase 0 derives this from trust alone. Phase 2 enriches it with board
        position -- a power with a tempting stab available is more dangerous than its
        track record alone suggests. Kept deliberately simple and honest here rather
        than dressed up as more than it is.
        """
        return {"probability": round(1.0 - self.trust.mean, 6), "horizon_phases": 1}


@runtime_checkable
class BeliefStore(Protocol):
    """The D4 injection seam. Two implementations, one interface."""

    observer: str

    def observe_message(self, subject: str, phase: str, message: dict, *, sent: bool = False) -> None: ...
    def observe_public_orders(self, subject: str, phase: str, orders: list[str]) -> None: ...
    def record_outcome(self, subject: str, phase: str, message_id: str, kept: bool,
                       stated: str = "", actual: str = "") -> None: ...
    def trust(self, subject: str) -> float: ...
    def end_phase(self) -> None: ...
    def context_for_prompt(self, subject: str) -> dict: ...
    def snapshot(self) -> list[dict]: ...


class BayesianBeliefStore:
    """The real store. One instance per power -- ARCHITECTURE.md section 4."""

    def __init__(
        self,
        observer: str,
        subjects: Iterable[str] | None = None,
        *,
        betrayal_weight: float = DEFAULT_BETRAYAL_WEIGHT,
        decay: float = DEFAULT_DECAY,
    ) -> None:
        if observer not in POWERS:
            raise ValueError(f"unknown power {observer!r}")
        self.observer = observer
        self.betrayal_weight = betrayal_weight
        self.decay_factor = decay
        subjects = subjects if subjects is not None else POWERS
        # A power modelling itself is a category error, so the key cannot exist.
        self.dyads: dict[str, Dyad] = {
            s: Dyad(subject=s) for s in sorted(subjects) if s != observer
        }
        self.treaties_believed: list[dict] = []

    # -- guards ---------------------------------------------------------

    def _dyad(self, subject: str) -> Dyad:
        if subject == self.observer:
            raise ValueError(
                f"{self.observer} cannot hold beliefs about itself -- "
                "observer and subject must differ"
            )
        if subject not in self.dyads:
            raise ValueError(f"{subject!r} is not a tracked subject for {self.observer}")
        return self.dyads[subject]

    # -- observation ----------------------------------------------------

    def observe_message(self, subject: str, phase: str, message: dict, *, sent: bool = False) -> None:
        """Record a message on this dyad's episodic tier.

        Only messages this observer is a party to may be recorded. A message between
        two other powers has no legitimate path into this store -- attempting it is a
        programming error, not a runtime condition to tolerate.
        """
        sender, recipient = message.get("sender"), message.get("recipient")
        if self.observer not in (sender, recipient):
            raise ValueError(
                f"ISOLATION VIOLATION: {self.observer} cannot observe a message "
                f"between {sender} and {recipient}"
            )
        dyad = self._dyad(subject)
        dyad.episodic.append({
            "phase": phase,
            "kind": "message_sent" if sent else "message_received",
            "message_id": message.get("message_id", ""),
            "body": message.get("body", ""),
            "stated_intent": message.get("stated_intent", []),
        })

    def observe_public_orders(self, subject: str, phase: str, orders: list[str]) -> None:
        """Adjudicated orders are public, so every observer may record them."""
        self._dyad(subject).episodic.append({
            "phase": phase, "kind": "public_orders", "orders": list(orders),
        })

    def record_outcome(
        self, subject: str, phase: str, message_id: str, kept: bool,
        stated: str = "", actual: str = "",
    ) -> None:
        """Post-adjudication trust revision -- pipeline step 8."""
        dyad = self._dyad(subject)
        before = dyad.trust.mean
        weight = 1.0 if kept else self.betrayal_weight
        dyad.trust.update(kept, weight)
        dyad.corrections.append({
            "phase": phase,
            "message_id": message_id,
            "kept": kept,
            "stated": stated,
            "actual": actual,
            "weight": weight,
            "trust_before": round(before, 6),
            "trust_after": round(dyad.trust.mean, 6),
        })

    def end_phase(self) -> None:
        for dyad in self.dyads.values():
            dyad.trust.decay(self.decay_factor)

    # -- reads ----------------------------------------------------------

    def trust(self, subject: str) -> float:
        return self._dyad(subject).trust.mean

    def context_for_prompt(self, subject: str) -> dict:
        """Everything this observer may legitimately bring into a prompt about
        `subject`. The isolation gate scans the assembled result of this."""
        dyad = self._dyad(subject)
        return {
            "observer": self.observer,
            "subject": subject,
            "trust": round(dyad.trust.mean, 4),
            "trust_confidence": round(dyad.trust.confidence, 4),
            "episodic": list(dyad.episodic),
            "corrections": list(dyad.corrections),
            "treaties_believed": [
                t for t in self.treaties_believed if t.get("with_power") == subject
            ],
        }

    def snapshot(self) -> list[dict]:
        """Belief snapshots in turn-log shape (turn_log schema $defs/belief_snapshot)."""
        out = []
        for subject in sorted(self.dyads):
            dyad = self.dyads[subject]
            entry = {
                "observer": self.observer,
                "subject": subject,
                "trust": round(dyad.trust.mean, 6),
                "predicted_betrayal": dyad.predicted_betrayal(),
            }
            if dyad.corrections:
                last = dyad.corrections[-1]
                entry["trust_delta"] = round(
                    last["trust_after"] - last["trust_before"], 6
                )
            if dyad.estimated_goals:
                entry["estimated_goals"] = list(dyad.estimated_goals)
            if dyad.estimated_alliances:
                entry["estimated_alliances"] = list(dyad.estimated_alliances)
            out.append(entry)
        return out

    def export(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "observer": self.observer,
            "semantic": {"treaties_believed": list(self.treaties_believed)},
            "dyads": [
                {
                    "subject": s,
                    "trust": self.dyads[s].trust.as_dict(),
                    "episodic": list(self.dyads[s].episodic),
                    "corrections": list(self.dyads[s].corrections),
                    "estimated_goals": list(self.dyads[s].estimated_goals),
                    "estimated_alliances": list(self.dyads[s].estimated_alliances),
                    "predicted_betrayal": self.dyads[s].predicted_betrayal(),
                }
                for s in sorted(self.dyads)
            ],
        }

    def validate(self, *, strict: bool = True) -> list[str]:
        errors = [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in _schema_validator().iter_errors(self.export())
        ]
        if errors and strict:
            raise ValueError(
                f"belief store failed schema validation ({len(errors)} error(s)):\n  "
                + "\n  ".join(errors)
            )
        return errors


class StubBeliefStore:
    """The belief_off arm of D4.

    Deliberately inert: fixed trust, no evidence accumulation, empty context. It
    satisfies the same protocol so the rest of the system cannot tell the difference
    structurally -- which is exactly what makes the comparison clean. Any measured
    difference between arms is attributable to the belief layer and nothing else.
    """

    def __init__(self, observer: str, subjects: Iterable[str] | None = None,
                 *, fixed_trust: float = 0.5, **_ignored) -> None:
        self.observer = observer
        self.fixed_trust = fixed_trust
        subjects = subjects if subjects is not None else POWERS
        self.subjects = [s for s in sorted(subjects) if s != observer]

    def observe_message(self, subject, phase, message, *, sent=False): return None
    def observe_public_orders(self, subject, phase, orders): return None
    def record_outcome(self, subject, phase, message_id, kept, stated="", actual=""): return None
    def end_phase(self): return None

    def trust(self, subject: str) -> float:
        return self.fixed_trust

    def context_for_prompt(self, subject: str) -> dict:
        return {
            "observer": self.observer, "subject": subject,
            "trust": self.fixed_trust, "trust_confidence": 0.0,
            "episodic": [], "corrections": [], "treaties_believed": [],
        }

    def snapshot(self) -> list[dict]:
        return [
            {
                "observer": self.observer, "subject": s,
                "trust": self.fixed_trust,
                "predicted_betrayal": {
                    "probability": round(1.0 - self.fixed_trust, 6),
                    "horizon_phases": 1,
                },
            }
            for s in self.subjects
        ]


def make_store(arm: str, observer: str, subjects: Iterable[str] | None = None, **kwargs):
    """Factory keyed by ablation arm. The only place either class is named."""
    if arm == "belief_on":
        return BayesianBeliefStore(observer, subjects, **kwargs)
    if arm == "belief_off":
        return StubBeliefStore(observer, subjects, **kwargs)
    raise ValueError(f"unknown arm {arm!r}")
