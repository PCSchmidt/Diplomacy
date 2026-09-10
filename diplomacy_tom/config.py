"""Credential loading.

A `.env` file at the repo root is read on import, so `ANTHROPIC_API_KEY` and
`OPENROUTER_API_KEY` reach the providers without exporting anything by hand.

Deliberately stdlib-only: this is fifteen lines, and it keeps the install line to
`pip install diplomacy jsonschema anthropic` rather than growing a dependency whose
entire job is parsing `KEY=value`.

Two rules that matter:

* **The real environment always wins.** A value already in `os.environ` is never
  overwritten by the file. A stale `.env` silently shadowing an exported key is a
  genuinely horrible afternoon, and CI must never pick up a developer's file.
* **The file is never logged, echoed, or committed.** `.gitignore` covers `.env*`,
  and `redacted()` exists so diagnostics can say whether a key is present without
  putting it on screen.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

KEYS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")


def load_env(path: Path | str = ENV_PATH, *, override: bool = False) -> list[str]:
    """Load KEY=value lines into os.environ. Returns the names that were set.

    Missing file is not an error — exported variables are an equally valid setup,
    and the CI path has no file at all.
    """
    path = Path(path)
    if not path.exists():
        return []

    loaded = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key in os.environ and not override:
            continue          # the real environment wins
        os.environ[key] = value
        loaded.append(key)
    return loaded


def redacted(key: str) -> str:
    """Describe a credential without disclosing it."""
    val = os.environ.get(key)
    if not val:
        return f"{key}: unset"
    return f"{key}: set ({len(val)} chars, ...{val[-4:]})"


def status() -> str:
    lines = [f"env file: {ENV_PATH} ({'found' if ENV_PATH.exists() else 'not present'})"]
    lines += [f"  {redacted(k)}" for k in KEYS]
    return "\n".join(lines)


# Load on import so `from diplomacy_tom.llm import AnthropicProvider` just works.
load_env()


if __name__ == "__main__":
    print(status())
