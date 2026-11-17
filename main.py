#!/usr/bin/env python3
"""Forecast GTA VI's launch-day Twitch viewers hour by hour.

Model (learned fresh from the case's own comparables at run time):
  1. Every comparable launch's release day is reduced to a curve of
     log(viewers_h / viewers_1), so launches of different sizes are
     comparable. Only "rolling-midnight" console launches are kept:
     hour 1 already live (h1 >= 10,000), a night dip in hours 2-5, a
     peak at hour 5 or later, peak ratio between 1.2x and 20x, no early
     access and no free-to-play/live-service tier. Single-global-unlock
     launches (hour 1 near zero, then a 100x explosion) and already-at-
     peak launches (simultaneous global unlock, hour 1 is the peak) are
     a different shape and are left out; so is the GTA VI category's
     own pre-release history, which is a premiere, not a launch.
  2. The typical shape is the per-hour median log-ratio across the
     kept launches, normalised so its peak is 1. It dips to ~0.7x in
     hours 3-4 (Europe asleep, US not yet unlocked), jumps at hours
     5-6 (US East midnight) and 9 (US West midnight), and peaks in
     the US evening around hour 20-21.
  3. The scale of the rise depends on how much of the audience was
     already in at hour 1: across the kept launches, the peak
     log-ratio falls almost linearly with log(hour-1 viewers)
     (a small hour 1 means most of the world still has to unlock, so
     the day grows far more). A least-squares fit of peak log-ratio
     on log(hour-1 viewers) gives this case's growth factor G,
     clamped to [0.3, 2.2] so an extrapolated giant launch still
     rises a little and a tiny one does not explode.
  4. The quantile spread is honest: per hour, the standard deviation
     of the kept launches' residuals around (shape * their own G),
     smoothed over neighbouring hours and scaled by 0.85. That value
     sits on a smooth spread curve measured on the practice cases
     (0.80: loss 0.1923, coverage 0.87; 0.85: 0.1928, 0.89; 0.90:
     0.1939, 0.91; 0.95: 0.1952, 0.92): 0.85 is the narrowest factor
     that still keeps 90% coverage essentially on target, while 0.80
     scores a touch lower only by letting coverage slip to 0.87.
     Quantiles are the log-normal quantiles
     p * exp(shape_h * G + z_tau * sd_h).

No wall clock, no randomness, no network: the output is a pure
function of the input case, so two runs are byte-identical.
Python 3.13 standard library only.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]
SPREAD = 0.85
G_FLOOR = 0.3
G_CAP = 2.2
MAX_VIEWERS = 1_000_000_000.0


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def day_curve(comp):
    """Hour -> viewers for the comparable's release day (00:00Z + 24h)."""
    day_start = parse_ts(comp["day_start"])
    out = {}
    for point in comp.get("hourly", []):
        try:
            when = parse_ts(point["from"])
            viewers = point["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None:
            continue
        if day_start <= when < day_start + timedelta(hours=24):
            hour = int((when - day_start).total_seconds() // 3600) + 1
            out[hour] = viewers
    return out


def is_rolling(comp, curve):
    """True when the comparable looks like a rolling-midnight launch."""
    name = (comp.get("name") or "").lower()
    if "grand theft auto vi category" in name:
        return False
    unlock = (comp.get("unlock") or "").lower()
    if "tier: weak" in unlock or "early access" in unlock:
        return False
    first = curve.get(1)
    if not first or first < 10000:
        return False
    present = [h for h in range(1, 25) if curve.get(h)]
    if len(present) < 20:
        return False
    peak_hour = max(curve, key=lambda h: curve[h])
    if peak_hour < 5:
        return False
    early = [curve[h] for h in range(2, 6) if h in curve]
    if not early or min(early) >= first:
        return False
    peak_ratio = curve[peak_hour] / first
    if peak_ratio < 1.2 or peak_ratio > 20:
        return False
    return True


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def fit_growth(rows):
    """Least squares: peak log-ratio = a + b * log(hour-1 viewers)."""
    xs = [math.log(p1) for _, p1, _ in rows]
    ys = [peak for _, _, peak in rows]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 0:
        return mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, ys)) / denom
    return mean_y - slope * mean_x, slope


def learn(case):
    """Learn (shape, growth, spread) from the case's comparables.

    Returns (shape, growth, spread) where shape maps hour -> the
    median log-ratio normalised so its peak is 1, growth is this
    case's predicted peak log-ratio, and spread maps hour -> the
    log-space standard deviation of the forecast.
    """
    rows = []
    for comp in case.get("comparables", []):
        curve = day_curve(comp)
        if not is_rolling(comp, curve):
            continue
        first = curve[1]
        log_ratio = {}
        for hour in range(1, 25):
            value = curve.get(hour)
            if value and value > 0:
                log_ratio[hour] = math.log(value / first)
        if len(log_ratio) < 20:
            continue
        rows.append((comp.get("name", ""), first,
                     max(log_ratio.values()), log_ratio))
    if len(rows) < 3:
        # Too few rolling launches: fall back to every usable curve.
        rows = []
        for comp in case.get("comparables", []):
            curve = day_curve(comp)
            first = curve.get(1)
            if not first or first <= 0:
                continue
            if len([h for h in range(1, 25) if curve.get(h)]) < 20:
                continue
            log_ratio = {}
            for hour in range(1, 25):
                value = curve.get(hour)
                if value and value > 0:
                    log_ratio[hour] = math.log(value / first)
            if len(log_ratio) >= 20:
                rows.append((comp.get("name", ""), first,
                             max(log_ratio.values()), log_ratio))
    if not rows:
        return None
    shape = {}
    for hour in range(1, 25):
        values = [lr[hour] for _, _, _, lr in rows if hour in lr]
        if values:
            shape[hour] = median(values)
    peak_shape = max(shape.values())
    if peak_shape <= 0:
        return None
    shape = {hour: value / peak_shape for hour, value in shape.items()}
    intercept, slope = fit_growth(
        [(name, first, peak) for name, first, peak, _ in rows])
    anchor = hour_one_viewers(case)
    growth = intercept + slope * math.log(max(anchor, 1))
    growth = max(G_FLOOR, min(G_CAP, growth))
    residuals = {hour: [] for hour in range(2, 25)}
    for _, first, _, log_ratio in rows:
        own_growth = intercept + slope * math.log(max(first, 1))
        own_growth = max(G_FLOOR, min(G_CAP, own_growth))
        for hour in range(2, 25):
            if hour in log_ratio:
                residuals[hour].append(log_ratio[hour] - shape[hour] * own_growth)
    spread = {}
    for hour in range(2, 25):
        values = residuals[hour]
        if not values:
            spread[hour] = 0.5
            continue
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
        spread[hour] = math.sqrt(var)
    smoothed = {}
    for hour in range(2, 25):
        near = [spread[h] for h in (hour - 1, hour, hour + 1)
                if h in spread]
        smoothed[hour] = sum(near) / len(near) if near else 0.5
    return shape, growth, smoothed


def hour_one_viewers(case):
    """Hour 1's print, with fallbacks if it is missing."""
    known = case.get("known") or []
    if known:
        viewers = known[0].get("viewers")
        if viewers:
            return viewers
    history = case.get("history") or []
    if history:
        viewers = history[-1].get("viewers")
        if viewers:
            return viewers
    return 1


def baseline_forecast(anchor):
    """House-baseline shape, used only when no comparable can be read."""
    rows = []
    for hour in range(2, 25):
        width = 0.15 * math.sqrt(hour - 1)
        quantiles = [anchor * math.exp(z * width) for z in Z]
        rows.append({"hour": hour, "q": quantiles})
    return rows


def forecast(case):
    anchor = max(hour_one_viewers(case), 1)
    learned = learn(case)
    if learned is None:
        return baseline_forecast(anchor)
    shape, growth, spread = learned
    rows = []
    for hour in range(2, 25):
        centre = shape.get(hour, shape.get(24, 0.0)) * growth
        sd = spread.get(hour, 0.5) * SPREAD
        quantiles = []
        for z in Z:
            value = anchor * math.exp(centre + z * sd)
            value = max(1.0, min(MAX_VIEWERS, value))
            quantiles.append(round(value, 2))
        for i in range(1, len(quantiles)):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append({"hour": hour, "q": quantiles})
    return rows


def run(input_dir, output_dir):
    names = sorted(name for name in os.listdir(input_dir)
                   if name.endswith(".in"))
    for name in names:
        case_id = name[:-3]
        with open(os.path.join(input_dir, name), "r",
                  encoding="utf-8") as handle:
            case = json.load(handle)
        result = {"hours": forecast(case)}
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, case_id + ".out")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, separators=(",", ":"))
            handle.write("\n")


def main(argv):
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input/"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output/"
    run(input_dir, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
