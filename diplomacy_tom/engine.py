"""Deterministic boundary around the `diplomacy` library.

Every interaction with the adjudicator goes through here. The library is sound (its
adjudication is deterministic given identical orders), but two of its APIs return
set-derived collections whose iteration order varies with PYTHONHASHSEED across
processes. See finding F3 in ARCHITECTURE.md.

That matters more than it sounds. The D4 ablation arms run as separate processes, so
unsorted enumeration means "belief layer on" and "belief layer off" are not playing
the same game -- and the naive determinism check passes, because two runs inside one
process agree. It also churns the stable prompt prefix that caching depends on.

**Never call game.get_all_possible_orders() or game.get_orderable_locations()
directly.** Use the helpers here.
"""

from __future__ import annotations

from typing import Iterable

from diplomacy import Game
from diplomacy.utils.export import to_saved_game_format

POWERS = (
    "AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY",
)

# The library's default rules include NO_PRESS. This is a negotiation game, so it is
# dropped -- and the turn-log schema rejects a log that still carries it.
DEFAULT_RULES = ("POWER_CHOICE",)


def new_game(rules: Iterable[str] = DEFAULT_RULES) -> Game:
    """A game with press enabled."""
    game = Game()
    game.rules = [r for r in game.rules if r != "NO_PRESS"]
    for rule in rules:
        if rule not in game.rules:
            game.add_rule(rule)
    return game


def possible_orders(game: Game) -> dict[str, list[str]]:
    """Legal orders per location, sorted. The F3 choke-point."""
    return {
        loc: sorted(orders)
        for loc, orders in sorted(game.get_all_possible_orders().items())
    }


def orderable_locations(game: Game, power: str) -> list[str]:
    """Locations `power` may order this phase, sorted."""
    return sorted(game.get_orderable_locations(power))


def powers_in_order(game: Game) -> list[str]:
    """Powers in a stable order. Dict order is insertion-stable, but relying on that
    silently couples us to library internals."""
    return sorted(game.powers)


def board_hash(game: Game) -> str:
    """Canonical position identity (zobrist), stable across processes."""
    return str(game.get_state().get("zobrist_hash", ""))


def public_orders(game: Game, phase_name: str) -> dict[str, list[str]]:
    """Adjudicated orders for a completed phase, from the game's own history.

    Public information: every power may observe these, which is what makes them the
    ground truth against which stated intent is checked.
    """
    for phase in game.get_phase_history():
        if phase.name == phase_name:
            return {p: sorted(o) for p, o in sorted((phase.orders or {}).items())}
    return {}


def export_game(game: Game) -> dict:
    """Saved-game format, with NO_PRESS stripped so the turn-log schema accepts it."""
    saved = to_saved_game_format(game)
    saved["rules"] = [r for r in saved.get("rules", []) if r != "NO_PRESS"]
    return saved


def can_reach(game, power: str, province: str) -> bool:
    """Could `power` move a unit into `province` this phase?

    This is what makes a commitment falsifiable. A pledge not to enter a province
    the speaker cannot reach is kept by default and carries no information -- 82% of
    commitments in the first live batch were of exactly that kind (ARCHITECTURE.md
    section 15), which is why the eval measured noise.

    Deliberately checks the legal-order list rather than raw adjacency: a fleet
    beside an inland province is adjacent but cannot enter it, and counting that as
    a real opportunity would reintroduce the same false positives in a subtler form.
    """
    target = province.split("/")[0].upper()
    for loc in orderable_locations(game, power):
        for order in possible_orders(game).get(loc, []):
            if " - " not in order:
                continue
            dest = order.rsplit(" - ", 1)[-1].split(" VIA")[0].split("/")[0].strip()
            if dest.upper() == target:
                return True
    return False


def occupies(game, power: str, province: str) -> bool:
    """Does `power` already hold a unit in `province`?"""
    target = province.split("/")[0].upper()
    return any(u.split()[-1].split("/")[0].upper() == target
               for u in game.get_units(power))


def commitment_pressure(game, subject: str, province: str) -> dict:
    """What a human Diplomacy player would actually use to judge this promise.

    The evaluator previously saw raw units/centers but nothing computed about
    OPPORTUNITY: is breaking this specific pledge currently tempting? A promise not
    to enter a contested, valuable, reachable province is a real test of character;
    the same promise about a province nobody wants is not. Missing this distinction
    is one of the two architectural gaps identified after the AUC-0.4993 result
    (ARCHITECTURE.md section 19) -- the other, game length, is not a per-call fix.

    Kept deliberately legible rather than a full 2-ply lookahead: whether OTHER
    powers could also move there this turn is a real but crude proxy for contest,
    not a support-resolved prediction of who would actually win it.
    """
    target = province.split("/")[0].upper()
    scs = {s.upper() for s in game.map.scs}
    is_sc = target in scs

    owner = None
    for power in powers_in_order(game):
        if target in {c.split("/")[0].upper() for c in game.get_centers(power)}:
            owner = power
            break

    reachable = can_reach(game, subject, target)

    rival_can_also_reach = any(
        can_reach(game, other, target)
        for other in powers_in_order(game) if other != subject
    )

    return {
        "province": target,
        "is_supply_center": is_sc,
        "current_owner": owner,
        "subject_could_take_it_now": reachable,
        "another_power_could_also_move_there": rival_can_also_reach,
        "would_be_a_free_gain": (
            is_sc and owner != subject and reachable and not rival_can_also_reach
        ),
    }
