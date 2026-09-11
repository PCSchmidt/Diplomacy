"""Batch runner for the D4 ablation.

Runs N games per arm on **matched seeds** — that pairing is the whole design. Game
outcomes vary enormously between seeds, so comparing unpaired runs would drown the
belief layer's effect in seed noise long before N got large enough to matter.

Usage:
    python -m diplomacy_tom.batch --games 20 --out runs/
    python -m diplomacy_tom.batch --games 20 --provider anthropic --routing cheap
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import evaluation as ev
from . import turn_log as tl
from .llm import PRESETS
from .runner import GameConfig, GameRunner


def _make_provider(name: str, routing: str):
    """Constructed inside the worker: SDK clients are not always picklable, and a
    live provider must not be shared across processes."""
    if name == "mock":
        from .llm import MockProvider
        return MockProvider()
    if name == "anthropic":
        from .llm import AnthropicProvider
        return AnthropicProvider()
    if name == "openrouter":
        from .llm import OpenRouterProvider
        return OpenRouterProvider()
    raise ValueError(f"unknown provider {name!r}")


def run_one(args: tuple) -> dict:
    """Run one game and persist it immediately.

    The log is written inside the worker rather than by the parent at the end. A
    batch is hours of paid API calls, and losing all of it to one transient failure
    in the final game is not an acceptable failure mode -- which is exactly what
    happened before this changed.
    """
    seed, arm, max_phases, use_llm, provider_name, routing, out_dir = args
    provider = _make_provider(provider_name, routing) if use_llm else None
    cfg = GameConfig(
        seed=seed, arm=arm, max_phases=max_phases,
        use_llm=use_llm, routing=routing, provider=provider,
    )
    log = GameRunner(cfg).run()
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        tl.save(log, out / f"{arm}-{seed}.json")
    return log


def run_batch(
    games: int = 10,
    *,
    max_phases: int = 20,
    use_llm: bool = True,
    provider: str = "mock",
    routing: str = "quality",
    seed0: int = 1901,
    workers: int = 1,
    out_dir: str | Path | None = None,
    progress=print,
) -> ev.Report:
    """Run both arms across `games` matched seeds and return the comparison."""
    seeds = [seed0 + i for i in range(games)]
    jobs = [
        (s, arm, max_phases, use_llm, provider, routing, str(out_dir) if out_dir else None)
        for s in seeds for arm in ("belief_on", "belief_off")
    ]

    results: list[dict] = []
    failures: list[str] = []

    if workers > 1:
        # as_completed, not map: map raises on the first failed future and discards
        # everything. One timeout must not destroy a batch.
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, j): j for j in jobs}
            for i, fut in enumerate(as_completed(futures), 1):
                seed, arm = futures[fut][0], futures[fut][1]
                try:
                    results.append(fut.result())
                    progress(f"  {i}/{len(jobs)}  ok   seed={seed} {arm}")
                except Exception as exc:
                    failures.append(f"seed={seed} {arm}: {type(exc).__name__}: {exc}")
                    progress(f"  {i}/{len(jobs)}  FAIL seed={seed} {arm}: "
                             f"{type(exc).__name__}")
    else:
        for i, job in enumerate(jobs, 1):
            try:
                results.append(run_one(job))
                progress(f"  {i}/{len(jobs)}  ok   seed={job[0]} {job[1]}")
            except Exception as exc:
                failures.append(f"seed={job[0]} {job[1]}: {type(exc).__name__}: {exc}")
                progress(f"  {i}/{len(jobs)}  FAIL seed={job[0]} {job[1]}")

    on = [g for g in results if g["run"]["arm"] == "belief_on"]
    off = [g for g in results if g["run"]["arm"] == "belief_off"]

    # Unpaired seeds break the matched-seed design, so drop any seed missing an arm
    # rather than silently comparing different games.
    paired = {g["run"]["seed"] for g in on} & {g["run"]["seed"] for g in off}
    dropped = (len(on) + len(off)) - 2 * len(paired)
    if dropped:
        progress(f"  dropping {dropped} unpaired game(s) - matched seeds only")
    on = [g for g in on if g["run"]["seed"] in paired]
    off = [g for g in off if g["run"]["seed"] in paired]

    if failures:
        progress(f"  {len(failures)} game(s) failed:")
        for f in failures[:5]:
            progress(f"    {f}")

    return ev.compare(on, off)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the D4 ablation batch.")
    ap.add_argument("--games", type=int, default=5, help="games per arm")
    ap.add_argument("--max-phases", type=int, default=20)
    ap.add_argument("--provider", default="mock",
                    choices=["mock", "anthropic", "openrouter"])
    ap.add_argument("--routing", default="quality", choices=sorted(PRESETS),
                    help="routing preset (derived from llm.PRESETS)")
    ap.add_argument("--seed0", type=int, default=1901)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default=None, help="directory for per-game logs")
    ap.add_argument("--report", default=None, help="write markdown report here")
    ap.add_argument("--no-llm", action="store_true", help="scripted policies only")
    args = ap.parse_args(argv)

    if args.provider != "mock":
        # Spending real money should be a deliberate act, not a default.
        est = args.games * 2
        print(f"About to run {est} games against '{args.provider}' "
              f"(routing={args.routing}). This costs real money.", file=sys.stderr)

    print(f"Running {args.games} games x 2 arms...")
    report = run_batch(
        games=args.games, max_phases=args.max_phases,
        use_llm=not args.no_llm, provider=args.provider, routing=args.routing,
        seed0=args.seed0, workers=args.workers, out_dir=args.out,
    )

    md = report.to_markdown()
    print("\n" + md)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(md, encoding="utf-8")
        Path(args.report).with_suffix(".json").write_text(
            json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        print(f"wrote {args.report}")

    if not report.is_evidence:
        print("\nNOTE: synthetic provider — these numbers are not evidence.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
