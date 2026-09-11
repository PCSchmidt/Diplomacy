"""Turn-log construction, validation and normalization.

The turn log is the project's single product artifact: the eval harness, the static
replay viewer, and both D4 ablation arms all read it. See ARCHITECTURE.md section 3.

Design: the `diplomacy` saved-game format is embedded verbatim under `game` rather
than translated into a format of our own. Adjudication data stays canonical,
`from_saved_game_format()` keeps working on that subtree, and our layers version
independently of the library's.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "1.3.0"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "turn_log.schema.json"

# Fields stamped at serialization time rather than being game data (finding F1).
# Two logs of the same game differ on these while being identical in substance, so
# every comparison and replay check normalizes them away first.
VOLATILE_STATE_KEYS = ("timestamp",)
VOLATILE_MESSAGE_KEYS = ("time_sent",)

# Identity assigned per Game() instance. Two runs of the same seed get different
# ids, so ablation-arm comparison must ignore them.
IDENTITY_KEYS = ("id", "game_id")


def _validator() -> Draft202012Validator:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return Draft202012Validator(json.load(fh))


def validate(log: dict, *, strict: bool = True) -> list[str]:
    """Validate a turn log. Returns error strings; raises on error when strict.

    Strict is the default deliberately: a schema break should stop the run, not
    produce a log that fails silently three phases later.
    """
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(_validator().iter_errors(log), key=lambda e: list(e.absolute_path))
    ]
    if errors and strict:
        raise ValueError(
            f"turn log failed schema validation ({len(errors)} error(s)):\n  "
            + "\n  ".join(errors)
        )
    return errors


def normalize_volatile(log: dict, *, drop_identity: bool = False) -> dict:
    """Strip serialization-time noise so two logs can be compared meaningfully.

    Set drop_identity to compare across runs (e.g. the two D4 arms), which get
    different game ids by construction.
    """
    out = json.loads(json.dumps(log))  # deep copy; logs are plain JSON by definition
    game = out.get("game", {})

    if drop_identity:
        for key in IDENTITY_KEYS:
            game.pop(key, None)

    for phase in game.get("phases", []):
        state = phase.get("state")
        if isinstance(state, dict):
            for key in VOLATILE_STATE_KEYS:
                state.pop(key, None)
            if drop_identity:
                for key in IDENTITY_KEYS:
                    state.pop(key, None)
        for message in phase.get("messages", []) or []:
            if isinstance(message, dict):
                for key in VOLATILE_MESSAGE_KEYS:
                    message.pop(key, None)

    return out


def replay_fingerprint(log: dict) -> str:
    """Stable identity for a played game.

    Built from the per-phase zobrist hashes, which are canonical board-position
    identities stable across processes (unlike an ad-hoc hash of our own). This is
    the primitive that proves two ablation arms played the same game.
    """
    positions = [
        f"{phase.get('name')}:{phase.get('state', {}).get('zobrist_hash')}"
        for phase in log.get("game", {}).get("phases", [])
    ]
    return hashlib.sha256("|".join(positions).encode()).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _diplomacy_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("diplomacy")
    except PackageNotFoundError:
        return "unknown"


def build_log(
    saved_game: dict,
    *,
    seed: int,
    arm: str,
    llm_powers: Iterable[str],
    scripted_powers: Iterable[str],
    models: dict[str, str],
    provider: str = "none",
    turns: list[dict] | None = None,
    llm_calls: list[dict] | None = None,
    max_phases: int | None = None,
    run_id: str | None = None,
) -> dict:
    """Assemble a turn log around a `diplomacy` saved game.

    `saved_game` is embedded verbatim apart from one correction: NO_PRESS is dropped
    from rules. It is in the library's defaults, but a negotiation game must not
    record itself as no-press -- the schema rejects it.
    """
    game = json.loads(json.dumps(saved_game))
    game["rules"] = [r for r in game.get("rules", []) if r != "NO_PRESS"]

    config: dict[str, Any] = {
        "llm_powers": sorted(llm_powers),
        "scripted_powers": sorted(scripted_powers),
        "models": models,
        "provider": provider,
    }
    if max_phases is not None:
        config["max_phases"] = max_phases

    log = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_id or uuid.uuid4().hex,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "arm": arm,
            "config": config,
            "code_version": {
                "git_sha": _git_sha(),
                "diplomacy_version": _diplomacy_version(),
                "python_version": sys.version.split()[0],
            },
        },
        "game": game,
        "turns": turns if turns is not None else [],
    }
    if llm_calls is not None:
        log["llm_calls"] = llm_calls
    return log


def empty_turn(phase: str, board_hash: str) -> dict:
    """A schema-valid turn with no agent activity yet.

    Phase 1 runs scripted bots with no LLM, so it emits these; Phase 2 fills them in.
    Keeping the shape identical from the start means the viewer and eval harness bind
    to their final contract immediately.
    """
    return {
        "phase": phase,
        "board_hash": board_hash,
        "messages": [],
        "beliefs": [],
        "decisions": [],
        "corrections": [],
    }


def turns_from_saved_game(saved_game: dict) -> list[dict]:
    """Seed one empty turn per phase, aligned to game.phases[].name."""
    return [
        empty_turn(phase["name"], phase.get("state", {}).get("zobrist_hash", ""))
        for phase in saved_game.get("phases", [])
        if phase.get("name") != "COMPLETED"
    ]


def check_alignment(log: dict) -> list[str]:
    """Structural invariants the JSON Schema cannot express.

    Schema validation proves each piece is well-formed; these prove the pieces refer
    to each other consistently. Both must pass for a log to be trustworthy.
    """
    problems: list[str] = []
    phases = log.get("game", {}).get("phases", [])
    by_name = {p.get("name"): p for p in phases}

    hashes = {}
    for phase in phases:
        state = phase.get("state", {})
        hashes[phase.get("name")] = state.get("zobrist_hash")

    seen: set[str] = set()
    for turn in log.get("turns", []):
        name = turn.get("phase")
        if name in seen:
            problems.append(f"turn {name!r} appears more than once")
        seen.add(name)

        if name not in by_name:
            problems.append(f"turn {name!r} has no matching phase in game.phases")
            continue
        if turn.get("board_hash") != hashes.get(name):
            problems.append(
                f"turn {name!r} board_hash does not match that phase's zobrist_hash"
            )

    # Every correction must point at a message that exists somewhere in the log.
    message_ids = {
        m.get("message_id")
        for turn in log.get("turns", [])
        for m in turn.get("messages", [])
    }
    for turn in log.get("turns", []):
        for correction in turn.get("corrections", []):
            if correction.get("message_id") not in message_ids:
                problems.append(
                    f"turn {turn.get('phase')!r}: correction references unknown "
                    f"message_id {correction.get('message_id')!r}"
                )

    # An observer holding beliefs about itself is a modelling error, and a message
    # to oneself means the negotiation loop is miswired.
    for turn in log.get("turns", []):
        for belief in turn.get("beliefs", []):
            if belief.get("observer") == belief.get("subject"):
                problems.append(
                    f"turn {turn.get('phase')!r}: belief with observer == subject "
                    f"({belief.get('observer')})"
                )
        for message in turn.get("messages", []):
            if message.get("sender") == message.get("recipient"):
                problems.append(
                    f"turn {turn.get('phase')!r}: message {message.get('message_id')!r} "
                    f"sent to self"
                )

    return problems


def load(path: str | Path, *, strict: bool = True) -> dict:
    with open(path, encoding="utf-8") as fh:
        log = json.load(fh)
    validate(log, strict=strict)
    return log


def save(log: dict, path: str | Path, *, strict: bool = True) -> Path:
    """Validate then write. Validation happens first so an invalid log never lands."""
    validate(log, strict=strict)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2, sort_keys=True)
    return path


# Providers whose output is synthetic. A run served by one of these is not evidence
# about model behaviour, and eval refuses to report it as such.
SYNTHETIC_PROVIDERS = {"mock", "none", "capture"}


def is_synthetic(log: dict) -> bool:
    """True when this run's responses did not come from a real model.

    `replay` is not synthetic: it reproduces whatever provider was recorded, so the
    recorded log's own provider is what counts. A replay of a mock run is still mock,
    because the recording carries that provider forward.
    """
    provider = (log.get("run", {}).get("config", {}) or {}).get("provider", "none")
    base = provider.split(":")[-1]
    return base in SYNTHETIC_PROVIDERS
