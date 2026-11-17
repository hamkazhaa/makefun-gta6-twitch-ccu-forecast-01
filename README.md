# GTA VI launch-day Twitch forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hamkazhaa/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hamkazhaa/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for the [gta6-twitch-ccu-forecast-01 bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast GTA VI's launch-day Twitch concurrent viewers hour by hour
(hours 2–24, five quantiles each), from the hour-1 print and the
comparable launches in the case file.

## Model

All work happens in log space, and everything is learned fresh from the
case's own comparables at run time — there are no hard-coded curves.

1. **Comparable curves.** Each comparable's release day is reduced to
   log(viewers_h / viewers_1), so launches of different sizes are
   comparable. Only *rolling-midnight* console launches are kept:
   hour 1 already live (h1 >= 10,000), a night dip in hours 2–5, a
   peak at hour 5 or later, peak ratio between 1.2x and 20x, no early
   access, no free-to-play/live-service tier. Single-global-unlock
   launches (hour 1 near zero, then a 100x explosion) and
   already-at-peak launches (simultaneous global unlock, hour 1 is
   the peak) are a different shape and are left out; so is the GTA VI
   category's own pre-release history, which is a premiere, not a
   launch.
2. **Typical shape.** The per-hour median log-ratio across the kept
   launches, normalised so its peak is 1, WEIGHTED by similarity to
   this case: a comparable counts exp(−|log h1_i − log h1_case|), so
   the shape is set mostly by launches of a similar size to this one
   (for GTA VI's scale, the biggest launches — effective sample about
   5 of 11). The day's curve is NOT flat: it dips to ~0.7x in hours
   3–4 (Europe asleep, US not yet unlocked), jumps at hours 5–6 (US
   East midnight) and 9 (US West midnight), and peaks in the US
   evening around hour 20–21.
3. **Growth depends on hour 1.** Across the kept launches, the peak
   log-ratio falls almost linearly with log(hour-1 viewers): a small
   hour 1 means most of the world still has to unlock, so the day
   grows far more. A least-squares fit of peak log-ratio on
   log(hour-1 viewers) gives this case's growth factor G, clamped to
   [0.3, 2.2] so an extrapolated giant launch still rises a little
   and a tiny one does not explode.
4. **Honest spread.** Per hour, the standard deviation of the kept
   launches' residuals around (shape x their own G), smoothed over
   neighbouring hours and scaled by 0.85 (chosen on the practice
   spread curve: 0.85 keeps 90% coverage at 0.89 while scoring
   better than 0.90; 0.80 scores a touch lower but lets coverage
   slip to 0.87). Quantiles are the log-normal
   quantiles p * exp(shape_h * G + z_tau * sd_h).
5. **Small per-hour centre correction.** The comparable median
   systematically over-predicts midday (hours 11–15) and
   under-predicts the morning rise (hours 5–8) and the evening
   (hours 18–22) on every practice launch, so the average of those
   errors, measured once on the four practice launches
   (BIAS_DELTA in main.py), is added back at a quarter strength.
   The pattern is stable: every leave-one-case-out subset shows the
   same signs, so it is a systematic shape error, not one launch's
   noise. It is a fixed table fitted offline on public historical
   data, like SPREAD — nothing is fitted to the case being forecast
   beyond its own comparables.

Deterministic: no wall clock, no randomness, no network — the output
is a pure function of the input case. Python 3.13 standard library
only, ~0.2 s per case.

## Practice results (mean pinball loss on the log scale)

Scored locally against the real hourly SullyGnome averages for the
four practice launches (the kit's scorer runs on the server; the
answers were fetched from SullyGnome's public API and verified —
hour-1 values match the case files exactly).

| case | game | loss | house baseline | 90% coverage |
|------|------|------|---------------|--------------|
| p00 | Wolverine | **0.2054** | 0.7436 | 0.87 |
| p01 | Red Dead Redemption 2 | **0.1118** | 0.2868 | 1.00 |
| p02 | God of War Ragnarok | **0.1333** | 0.2146 | 1.00 |
| p03 | Spider-Man 2 | **0.2348** | 0.3033 | 0.83 |
| **mean** | | **0.1713** | **0.3871** | **0.92** |

The model beats the house baseline (~0.387) on every practice case —
about **2.3x better overall** — while keeping 90% coverage at 0.92,
essentially on target, so the bands are honest, not degenerate. The two executions of each
practice case are byte-identical.

**Honest out-of-sample check (leave-one-case-out).** The table above
is in-sample for the bias-correction table, so the decision to adopt
the change was made on leave-one-case-out validation instead: tune on
3 practice cases, test on the held-out 4th, rotate. The unweighted
model tuned the same way scores a LOO mean of 0.1932; the weighted
shape plus the bias correction scores **0.1863** (0.1801 with the
knobs fixed at their modal values λ=0.25, s=1.0), improving on all
four held-out cases with 90% coverage at 0.88–0.92. The in-sample
0.1713 above is therefore optimistic; 0.1863 is the honest estimate
of the improvement (about −3.6% vs the unweighted model).

## What did not work (checked and dropped)

- **Normalised-shape median** (median of each launch's shape divided
  by its own peak): essentially the same shape as the chosen model, no
  gain; one implementation of it also had a variable-shadowing bug
  that scaled forecasts by the last comparable's hour-1 print — the
  final program uses distinct variable names throughout.
- **Empirical per-hour quantiles** instead of a log-normal spread:
  worse (0.2112) — 11 comparables make the tails too noisy.
- **Extra predictors** (channels per viewer, pre-launch baseline):
  no signal in the residuals (correlations +0.06 / −0.21 / −0.05),
  so they were not added.
- **Median peak growth, ignoring hour 1**: 0.2637 — adapting the
  growth to hour-1 size is the single biggest win.
- **Second predictor in the G regression** (pre-launch baseline, as
  log(baseline) or log(baseline/h1)): worse in-sample, 0.1982 vs
  0.1928 — dropped. (The two forms are the same fit: the ratio form
  is the baseline form minus log h1, which is already a predictor.)
- **Per-hour spread ramp** (spread multiplier rising or falling with
  the hour): LOO mean 0.1922 vs 0.1932 baseline — a negligible gain
  that picked edge values and let coverage slip to 0.70 on one
  held-out case; dropped.
- **Ensemble with the direct median-ratio forecast**: LOO tuning
  picks weight 1.0 (the current model) on every fold — no gain;
  dropped.

## Run

```sh
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=/output python3 main.py
```

Reads every `*.in` file in the input directory and writes the
matching `*.out` file (23 rows, hours 2–24, five quantiles each).
