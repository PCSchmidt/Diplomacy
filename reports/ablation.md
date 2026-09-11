# Ablation report — does the belief layer do anything?

Providers: openrouter. 6 games per arm, matched seeds.

| Metric | belief_on | belief_off | reads |
| --- | --- | --- | --- |
| Games | 6 | 6 | matched seeds |
| Messages resolved | 89 | 28 | |
| Promises broken | 16 | 6 | |
| **Evaluator AUC** | **0.470** | 0.428 | 0.5 = no signal |
| Evaluator Brier | 0.228 | 0.276 | lower better; 0.25 = always 0.5 |
| Trust Brier | 0.244 | — | lower better |
| Betrayals | 16 | 6 | |
| Anticipated (lead > 0) | 1 | 0 | belief moved *before* the stab |
| Mean lead (phases) | 0.19 | 0.00 | 0 = only ever reacts |
| Alliance spans | 1 | 0 | |
| Mean span (phases) | 1.00 | — | |
| Cost / game | $0.0733 | $0.0506 | |
| Cache hit rate | 0.000 | 0.000 | |

## Calibration — belief_on evaluator

| Predicted band | n | mean predicted | actually kept |
| --- | --- | --- | --- |
| 0.0–0.2 | 0 | — | — |
| 0.2–0.4 | 8 | 0.319 | 1.000 |
| 0.4–0.6 | 40 | 0.504 | 0.775 |
| 0.6–0.8 | 31 | 0.692 | 0.871 |
| 0.8–1.0 | 10 | 0.820 | 0.700 |
