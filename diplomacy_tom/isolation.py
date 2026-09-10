"""Context-assembly gate -- pipeline step 1.

The belief store already makes leaks structurally hard: a store belongs to one power
and has no method that would admit another power's private channel. This is the
second line of defence, and it exists because the first one depends on every future
caller staying disciplined.

The gate works on the assembled prompt, immediately before it is sent. It knows which
private content belongs to whom, and hard-fails if anything reaches a power that was
not party to it.

A leak here does not merely look bad. Every belief metric downstream assumes agents
reason from what they legitimately observed, so a leak silently invalidates the whole
experiment while still producing plausible-looking numbers. That is why this fails
closed and why the deliberate-leak fixture is a required test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class IsolationViolation(Exception):
    """Raised when private content reaches a power that was not party to it."""


@dataclass
class PrivateItem:
    """One piece of private content and the powers entitled to see it."""

    item_id: str
    text: str
    entitled: frozenset[str]
    kind: str = "message"


@dataclass
class IsolationRegistry:
    """Every private item in the game, with its entitlement set.

    Registered centrally by the game runner as messages are created, so the gate has
    a complete picture rather than relying on each call site to declare what it is
    passing.
    """

    items: dict[str, PrivateItem] = field(default_factory=dict)

    def register_message(self, message: dict) -> PrivateItem:
        sender, recipient = message.get("sender"), message.get("recipient")
        if not sender or not recipient:
            raise ValueError("message must carry sender and recipient to be registered")
        item = PrivateItem(
            item_id=message.get("message_id", ""),
            text=message.get("body", ""),
            entitled=frozenset({sender, recipient}),
            kind="message",
        )
        self.items[item.item_id] = item
        return item

    def register(self, item_id: str, text: str, entitled: set[str], kind: str = "note") -> PrivateItem:
        item = PrivateItem(item_id, text, frozenset(entitled), kind)
        self.items[item_id] = item
        return item


def _normalize(text: str) -> str:
    """Collapse whitespace and case so trivial reformatting cannot evade the scan."""
    return re.sub(r"\s+", " ", text).strip().lower()


# Substrings shorter than this are ignored: common phrases would otherwise produce
# constant false positives and train the team to disable the gate, which is worse
# than the leaks it prevents.
MIN_MATCH_LENGTH = 24


def scan(context: object, viewer: str, registry: IsolationRegistry) -> list[str]:
    """Return a violation string for every private item leaking into `context`.

    `context` is anything JSON-serializable -- a prompt string, a context dict, a
    message list. It is flattened to text before scanning, so a leak buried in a
    nested structure is caught as readily as one in a top-level string.
    """
    if isinstance(context, str):
        blob = _normalize(context)
    else:
        blob = _normalize(json.dumps(context, default=str))

    # Text the viewer IS entitled to. Two powers can independently send byte-identical
    # messages -- "Agreed.", "I will hold in Munich." -- and a pure substring scan
    # cannot tell whose copy it found. Without this, the viewer's own legitimate
    # message gets reported as someone else's leak (finding F7). A gate that cries
    # wolf gets switched off, which is worse than the leaks it prevents.
    entitled_text = {
        _normalize(item.text)
        for item in registry.items.values()
        if viewer in item.entitled
    }

    violations: list[str] = []
    for item in registry.items.values():
        if viewer in item.entitled:
            continue
        needle = _normalize(item.text)
        if len(needle) < MIN_MATCH_LENGTH:
            continue
        if needle in entitled_text:
            # Presence is fully explained by content the viewer may legitimately
            # hold. This is a real blind spot, not a clean pass: an actual leak of
            # text that happens to duplicate an entitled message is invisible here.
            # Accepted deliberately -- the alternative is constant false alarms.
            continue
        if needle in blob:
            violations.append(
                f"{item.kind} {item.item_id!r} (entitled: "
                f"{', '.join(sorted(item.entitled))}) is visible to {viewer}"
            )
    return sorted(violations)


def enforce(context: object, viewer: str, registry: IsolationRegistry) -> object:
    """Scan and fail closed. Returns the context unchanged when clean.

    Call this on every prompt before it is sent. It returns the context so it can wrap
    the assembly expression directly, making it awkward to bypass by accident.
    """
    violations = scan(context, viewer, registry)
    if violations:
        raise IsolationViolation(
            f"context assembled for {viewer} contains {len(violations)} "
            f"private item(s) it is not entitled to:\n  " + "\n  ".join(violations)
        )
    return context


def audit_store(store, registry: IsolationRegistry) -> list[str]:
    """Check a belief store's whole contents, not just one assembled prompt.

    Catches a leak that was written into memory during an earlier phase and would
    otherwise surface only when some later prompt happens to include it.
    """
    export = store.export() if hasattr(store, "export") else {"dyads": []}
    return scan(export, store.observer, registry)
