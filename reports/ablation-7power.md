# Ablation report — does the belief layer do anything?

Providers: openrouter. 10 games per arm, matched seeds.

| Metric | belief_on | belief_off | reads |
| --- | --- | --- | --- |
| Games | 10 | 10 | matched seeds |
| Messages resolved (falsifiable) | 667 | 683 | |
| Excluded as unfalsifiable | 926 | 960 | promise the speaker could not have broken |
| Promises broken | 236 | 226 | |
| **Evaluator AUC** | **0.497** | 0.491 | 0.5 = no signal |
| Evaluator Brier | 0.294 | 0.292 | lower better; 0.25 = always 0.5 |
| Trust Brier | 0.247 | — | lower better |
| Betrayals | 236 | 226 | |
| Anticipated (lead > 0) | 54 | 0 | belief moved *before* the stab |
| Mean lead (phases) | 0.75 | 0.00 | 0 = only ever reacts |
| Alliance spans | 26 | 0 | |
| Mean span (phases) | 1.42 | — | |
| Cost / game | $1.4081 | $0.8134 | |
| Cache hit rate | 0.000 | 0.000 | |

## Calibration — belief_on evaluator

| Predicted band | n | mean predicted | actually kept |
| --- | --- | --- | --- |
| 0.0–0.2 | 51 | 0.148 | 0.804 |
| 0.2–0.4 | 146 | 0.295 | 0.610 |
| 0.4–0.6 | 39 | 0.484 | 0.615 |
| 0.6–0.8 | 313 | 0.713 | 0.626 |
| 0.8–1.0 | 118 | 0.872 | 0.686 |
