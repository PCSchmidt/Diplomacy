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
