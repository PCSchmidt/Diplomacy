"""Phase 4: metrics over turn logs.

This is the module that turns a demo into evidence. Everything here is a pure
function of logged data — no game is replayed, no model is called — which is why the
turn log had to be a complete artifact (ARCHITECTURE.md §3).

Three questions, in order of how much they matter:

1. **Does the evaluator discriminate?** Given a message and its later outcome, is a
   higher predicted_truthfulness actually more likely to be kept? AUC of 0.5 means
   no signal at all, and no amount of pretty visualisation rescues that.
2. **Is trust calibrated?** When a power's trust in another says 0.7, do 70% of that
   counterpart's subsequent promises hold? Measured by Brier score.
3. **Does belief anticipate betrayal, or only record it?** The interesting claim is
   lead time: belief shifting *before* the stab, not after.

A standing rule enforced in code: results derived from a synthetic provider are
labelled as such and never reported as evidence. See `Report.is_evidence`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable

from . import turn_log as tl


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def auc(scores_labels: list[tuple[float, bool]]) -> float | None:
    """Area under the ROC curve, via the Mann-Whitney U identity.

    Reported rather than plain accuracy because accuracy depends on where you put the
    threshold, and on class balance. AUC asks the question we actually care about:
    ranked by predicted truthfulness, do kept promises sort above broken ones?

    0.5 is chance. Below 0.5 means the signal is inverted, which is information.
    Returns None when one class is absent — undefined, not zero.
    """
    pos = [s for s, y in scores_labels if y]
    neg = [s for s, y in scores_labels if not y]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(pos) * len(neg))


def brier(pairs: list[tuple[float, bool]]) -> float | None:
    """Mean squared error of a probabilistic forecast. Lower is better; 0.25 is the
    score of always saying 0.5."""
    if not pairs:
        return None
    return statistics.fmean((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs)


def calibration_bins(pairs: list[tuple[float, bool]], bins: int = 5) -> list[dict]:
    """Reliability table: within each predicted-probability band, what actually
    happened. This is what exposes a model that says 0.7 to everything."""
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, y) for p, y in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        if not sel:
            out.append({"lo": lo, "hi": hi, "n": 0, "predicted": None, "actual": None})
            continue
        out.append({
            "lo": round(lo, 2), "hi": round(hi, 2), "n": len(sel),
            "predicted": round(statistics.fmean(p for p, _ in sel), 4),
            "actual": round(statistics.fmean(1.0 if y else 0.0 for _, y in sel), 4),
        })
    return out


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def _phase_order(log: dict) -> dict[str, int]:
    return {t["phase"]: i for i, t in enumerate(log.get("turns", []))}


def message_outcomes(log: dict) -> list[dict]:
    """Every message that was both scored and later resolved.

    The join is what makes the eval possible: prediction at phase P, ground truth
    from adjudication at phase P or later.
    """
    outcomes = {}
    for turn in log.get("turns", []):
        for c in turn.get("corrections", []):
            outcomes.setdefault(c["message_id"], {**c, "resolved_phase": turn["phase"]})

    rows = []
    for turn in log.get("turns", []):
        for m in turn.get("messages", []):
            oc = outcomes.get(m.get("message_id"))
            if not oc:
                continue
            rows.append({
                "message_id": m["message_id"],
                "phase": turn["phase"],
                "sender": m["sender"],
                "recipient": m["recipient"],
                "kept": bool(oc["kept"]),
                "predicted_truthfulness":
                    (m.get("evaluation") or {}).get("predicted_truthfulness"),
                "confidence": (m.get("evaluation") or {}).get("confidence"),
                "trust_before": oc.get("trust_before"),
            })
    return rows


def betrayal_events(log: dict) -> list[dict]:
    """Broken promises, with the belief trajectory that preceded them.

    `lead` is the headline: how many phases before the betrayal did this dyad's
    predicted_betrayal first exceed its own baseline? A system that only updates
    after the stab scores 0 here, and that is exactly the failure worth detecting.
    """
    order = _phase_order(log)
    # predicted_betrayal per dyad per phase
    traj: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for turn in log.get("turns", []):
        i = order.get(turn["phase"], 0)
        for b in turn.get("beliefs", []):
            key = (b["observer"], b["subject"])
            pb = (b.get("predicted_betrayal") or {}).get(
                "probability", 1.0 - (b.get("trust") or 0.5))
            traj.setdefault(key, []).append((i, float(pb)))

    events = []
    for turn in log.get("turns", []):
        idx = order.get(turn["phase"], 0)
        for c in turn.get("corrections", []):
            if c.get("kept", True):
                continue
            key = (c["observer"], c["subject"])
            series = sorted(traj.get(key, []))
            before = [(i, v) for i, v in series if i < idx]
            if not before:
                events.append({"phase": turn["phase"], "observer": c["observer"],
                               "subject": c["subject"], "lead": 0, "rise": None})
                continue
            baseline = before[0][1]
            # First phase where the estimate rose meaningfully above its own start.
            lead = 0
            for i, v in before:
                if v > baseline + 0.05:
                    lead = idx - i
                    break
            events.append({
                "phase": turn["phase"], "observer": c["observer"],
                "subject": c["subject"], "lead": lead,
                "rise": round(before[-1][1] - baseline, 4),
            })
    return events


def alliance_spans(log: dict, high: float = 0.65, low: float = 0.4) -> list[int]:
    """Durations, in phases, of dyads holding above `high` before falling below `low`.

    Hysteresis rather than a single threshold, so ordinary jitter around one number
    does not read as an alliance collapsing and reforming every phase.
    """
    order = _phase_order(log)
    series: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for turn in log.get("turns", []):
        i = order.get(turn["phase"], 0)
        for b in turn.get("beliefs", []):
            series.setdefault((b["observer"], b["subject"]), []).append(
                (i, float(b.get("trust") or 0.5)))

    spans = []
    for points in series.values():
        start = None
        for i, v in sorted(points):
            if start is None and v >= high:
                start = i
            elif start is not None and v < low:
                spans.append(i - start)
                start = None
    return spans


def cost_summary(log: dict) -> dict:
    calls = log.get("llm_calls", []) or []
    usd = sum((c.get("usage") or {}).get("cost_usd", 0.0) for c in calls)
    inp = sum((c.get("usage") or {}).get("input_tokens", 0) for c in calls)
    out = sum((c.get("usage") or {}).get("output_tokens", 0) for c in calls)
    cached = sum(c.get("cache_read_tokens", 0) for c in calls)
    return {
        "calls": len(calls), "input_tokens": inp, "output_tokens": out,
        "cache_read_tokens": cached,
        "cache_hit_rate": round(cached / (cached + inp), 4) if (cached + inp) else 0.0,
        "cost_usd": round(usd, 6),
    }


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


@dataclass
class ArmReport:
    arm: str
    games: int = 0
    synthetic: bool = True
    providers: set[str] = field(default_factory=set)

    messages: int = 0
    resolved: int = 0
    broken: int = 0

    evaluator_auc: float | None = None
    evaluator_brier: float | None = None
    calibration: list[dict] = field(default_factory=list)

    trust_brier: float | None = None
    betrayals: int = 0
    mean_lead: float | None = None
    anticipated: int = 0          # betrayals with lead > 0

    alliance_spans: int = 0
    mean_alliance_span: float | None = None

    cost: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["providers"] = sorted(self.providers)
        return d


def evaluate_arm(logs: Iterable[dict], arm: str) -> ArmReport:
    rep = ArmReport(arm=arm)
    ev_pairs: list[tuple[float, bool]] = []
    trust_pairs: list[tuple[float, bool]] = []
    leads: list[int] = []
    spans: list[int] = []
    cost = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cost_usd": 0.0}

    for log in logs:
        rep.games += 1
        rep.providers.add((log.get("run", {}).get("config", {}) or {}).get("provider", "?"))
        if not tl.is_synthetic(log):
            rep.synthetic = False

        rows = message_outcomes(log)
        rep.messages += sum(len(t.get("messages", [])) for t in log.get("turns", []))
        rep.resolved += len(rows)
        rep.broken += sum(1 for r in rows if not r["kept"])

        for r in rows:
            if r["predicted_truthfulness"] is not None:
                ev_pairs.append((float(r["predicted_truthfulness"]), r["kept"]))
            if r["trust_before"] is not None:
                trust_pairs.append((float(r["trust_before"]), r["kept"]))

        events = betrayal_events(log)
        rep.betrayals += len(events)
        for e in events:
            leads.append(e["lead"])
        spans += alliance_spans(log)

        c = cost_summary(log)
        for k in ("calls", "input_tokens", "output_tokens", "cache_read_tokens"):
            cost[k] += c[k]
        cost["cost_usd"] += c["cost_usd"]

    rep.evaluator_auc = auc(ev_pairs)
    rep.evaluator_brier = brier(ev_pairs)
    rep.calibration = calibration_bins(ev_pairs)
    rep.trust_brier = brier(trust_pairs)
    rep.anticipated = sum(1 for l in leads if l > 0)
    rep.mean_lead = round(statistics.fmean(leads), 3) if leads else None
    rep.alliance_spans = len(spans)
    rep.mean_alliance_span = round(statistics.fmean(spans), 2) if spans else None
    cost["cost_usd"] = round(cost["cost_usd"], 6)
    cost["cache_hit_rate"] = (
        round(cost["cache_read_tokens"] / (cost["cache_read_tokens"] + cost["input_tokens"]), 4)
        if (cost["cache_read_tokens"] + cost["input_tokens"]) else 0.0
    )
    cost["cost_per_game"] = round(cost["cost_usd"] / rep.games, 6) if rep.games else None
    rep.cost = cost
    return rep


@dataclass
class Report:
    """The D4 result: two arms, same seeds, compared."""

    on: ArmReport
    off: ArmReport

    @property
    def is_evidence(self) -> bool:
        """False when either arm came from a synthetic provider.

        The harness runs fine on mock data — that is how it is tested — but mock
        output is uncorrelated with the outcomes it is scored against, so every
        metric below is noise. Publishing those numbers as findings would be
        fabricating evidence, so the report says so instead.
        """
        return not (self.on.synthetic or self.off.synthetic)

    def as_dict(self) -> dict:
        return {
            "is_evidence": self.is_evidence,
            "belief_on": self.on.as_dict(),
            "belief_off": self.off.as_dict(),
        }

    def to_markdown(self) -> str:
        on, off = self.on, self.off
        f = lambda v, n=3: "—" if v is None else f"{v:.{n}f}"

        head = "# Ablation report — does the belief layer do anything?\n\n"
        if not self.is_evidence:
            head += (
                "> **These numbers are not evidence.** At least one arm was produced by a\n"
                "> synthetic provider "
                f"({', '.join(sorted(on.providers | off.providers))}), whose responses are\n"
                "> uncorrelated with the outcomes they are scored against. The harness is\n"
                "> exercised; the findings are noise. Re-run against a real model.\n\n"
            )
        else:
            head += (
                f"Providers: {', '.join(sorted(on.providers | off.providers))}. "
                f"{on.games} games per arm, matched seeds.\n\n"
            )

        return head + f"""| Metric | belief_on | belief_off | reads |
| --- | --- | --- | --- |
| Games | {on.games} | {off.games} | matched seeds |
| Messages resolved | {on.resolved} | {off.resolved} | |
| Promises broken | {on.broken} | {off.broken} | |
| **Evaluator AUC** | **{f(on.evaluator_auc)}** | {f(off.evaluator_auc)} | 0.5 = no signal |
| Evaluator Brier | {f(on.evaluator_brier)} | {f(off.evaluator_brier)} | lower better; 0.25 = always 0.5 |
| Trust Brier | {f(on.trust_brier)} | {f(off.trust_brier)} | lower better |
| Betrayals | {on.betrayals} | {off.betrayals} | |
| Anticipated (lead > 0) | {on.anticipated} | {off.anticipated} | belief moved *before* the stab |
| Mean lead (phases) | {f(on.mean_lead, 2)} | {f(off.mean_lead, 2)} | 0 = only ever reacts |
| Alliance spans | {on.alliance_spans} | {off.alliance_spans} | |
| Mean span (phases) | {f(on.mean_alliance_span, 2)} | {f(off.mean_alliance_span, 2)} | |
| Cost / game | ${f(on.cost.get('cost_per_game'), 4)} | ${f(off.cost.get('cost_per_game'), 4)} | |
| Cache hit rate | {f(on.cost.get('cache_hit_rate'), 3)} | {f(off.cost.get('cache_hit_rate'), 3)} | |

## Calibration — belief_on evaluator

| Predicted band | n | mean predicted | actually kept |
| --- | --- | --- | --- |
""" + "\n".join(_calibration_row(b) for b in on.calibration) + "\n"


def _calibration_row(b: dict) -> str:
    pred = "—" if b["predicted"] is None else f"{b['predicted']:.3f}"
    act = "—" if b["actual"] is None else f"{b['actual']:.3f}"
    return f"| {b['lo']:.1f}–{b['hi']:.1f} | {b['n']} | {pred} | {act} |"


def compare(on_logs: list[dict], off_logs: list[dict]) -> Report:
    return Report(on=evaluate_arm(on_logs, "belief_on"),
                  off=evaluate_arm(off_logs, "belief_off"))
