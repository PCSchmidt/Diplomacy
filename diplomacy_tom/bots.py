"""Scripted policies -- the Phase 1 stand-ins for LLM powers.

These exist so the whole pipeline (game loop, belief updates, isolation gate, turn
log) can be exercised end to end with no API calls, no cost and no latency. Phase 2
swaps LLM negotiators in behind the same interface.

They also stay in the finished system: D2 fixes three of the seven powers as scripted
bots to bound token cost and pairwise message blowup.

Every policy takes an explicit `rng` rather than using module-level randomness, so a
run is reproducible from its seed alone.
"""

from __future__ import annotations

import random
from typing import Protocol

from . import engine


class Policy(Protocol):
    name: str

    def orders(self, game, power: str, rng: random.Random) -> list[str]: ...


class RandomPolicy:
    """Uniformly random legal orders. The floor: any policy worth having beats it."""

    name = "random"

    def orders(self, game, power: str, rng: random.Random) -> list[str]:
        possible = engine.possible_orders(game)
        return [
            rng.choice(possible[loc])
            for loc in engine.orderable_locations(game, power)
            if possible.get(loc)
        ]


class HoldPolicy:
    """Holds everything it can. Useful as a control: a power that never moves gives
    the belief layer a stable backdrop to measure other powers against."""

    name = "hold"

    def orders(self, game, power: str, rng: random.Random) -> list[str]:
        possible = engine.possible_orders(game)
        chosen = []
        for loc in engine.orderable_locations(game, power):
            options = possible.get(loc) or []
            holds = [o for o in options if o.endswith(" H")]
            if holds:
                chosen.append(holds[0])
            elif options:
                chosen.append(rng.choice(options))
        return chosen


class GreedyExpansionPolicy:
    """Prefers moves into unowned supply centres, then any move, then hold.

    Deliberately simple. It is not trying to play well -- it is trying to produce
    games with enough territorial churn that trust dynamics have something to bite
    on, which uniformly random play does not reliably give.
    """

    name = "greedy_expansion"

    def orders(self, game, power: str, rng: random.Random) -> list[str]:
        possible = engine.possible_orders(game)
        owned = set(game.get_centers(power))
        all_centers = set(game.map.scs)
        targets = all_centers - owned

        chosen = []
        for loc in engine.orderable_locations(game, power):
            options = possible.get(loc) or []
            if not options:
                continue
            moves = [o for o in options if " - " in o]
            to_center = [
                o for o in options
                if " - " in o and o.rsplit(" - ", 1)[-1].split("/")[0] in targets
            ]
            if to_center:
                chosen.append(rng.choice(sorted(to_center)))
            elif moves:
                chosen.append(rng.choice(sorted(moves)))
            else:
                chosen.append(rng.choice(options))
        return chosen


POLICIES: dict[str, Policy] = {
    p.name: p() for p in (RandomPolicy, HoldPolicy, GreedyExpansionPolicy)
}


def get_policy(name: str) -> Policy:
    if name not in POLICIES:
        raise ValueError(f"unknown policy {name!r}; have {sorted(POLICIES)}")
    return POLICIES[name]
