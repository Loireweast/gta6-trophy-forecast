"""GTA VI trophy rarity forecast: dilution-aware forecaster.

For every trophy of Grand Theft Auto VI on PlayStation 5, forecast the earn
rate on Exophase at the case's target, as five quantiles (5/25/50/75/95%).

The core idea is that an Exophase earn rate is a ratio, earned / tracked,
and the two sides move at different speeds. The tracked-player count surges
after launch (thousands of new and casual players register), which dilutes
every rate, while the earned count only grows as players actually reach each
trophy. Early, easy trophies accumulate earners almost as fast as the player
base grows, so their rates barely fall; late, hard trophies accumulate almost
no new earners while the denominator multiplies, so their rates collapse
toward the pure-dilution floor. A forecast that ignores this (persistence)
is systematically too high, and one that ignores how uncertain the refresh
is pays for every trophy outside its band.

So the forecaster works in two modes, chosen from the case's history:

* When the history moves (the usual case, and the final's), it fits each
  trophy's logit-rate trend over the recent reads and extrapolates it with
  a damping factor that shrinks the trend as the horizon grows, so a
  4.5-day extrapolation does not run away on a 2-day trend.

* When the history is flat (every read identical: the page has not refreshed
  in hours, as in the practice cases), it uses a refresh prior instead of
  the flat trend. The tracked count is assumed to have been growing since
  the page was set, at a launch-phase rate that decays with time since
  release; each trophy's earned count is assumed to grow at a fraction of
  that rate, the fraction set by how early the trophy sits in the game
  (its description: Chapter 1 and fishing unlock fast, late chapters and
  grinds barely move). The net drift is negative for almost every trophy,
  and the spread is kept wide because the refresh's size is uncertain.

Quantiles are built on the logit scale from the median and a spread that
grows with the horizon, then mapped back to percent and clamped to the
legal 0.01..99.99 range. The 100% trophy stays at 100%: every tracked
player holds it, and a refresh cannot lower it.

Standard library only. Deterministic: no randomness, no wall-clock reads,
no network. Reads $MAKEFUN_INPUT_DIR (else /input) and writes
$MAKEFUN_OUTPUT_DIR (else /output), one <id>.out per <id>.in.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a helper
# module shipped beside this file would import. (This entry ships one file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# --- logit helpers -------------------------------------------------------

def _clamp_pct(x):
    if x < 0.01:
        return 0.01
    if x > 99.99:
        return 99.99
    return x


def _logit(pct):
    p = _clamp_pct(pct)
    return math.log(p / (100.0 - p))


def _inv_logit(lg):
    if lg >= 0:
        return 100.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return 100.0 * e / (1.0 + e)


def _parse_time(text):
    """ISO 8601 timestamp (with Z or offset) -> aware datetime, or None."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_between(a, b):
    if a is None or b is None:
        return 0.0
    return (b - a).total_seconds() / 3600.0


# --- refresh prior (flat history) ---------------------------------------
#
# The tracked-player count of a blockbuster launch grows fast at first and
# then decays. Model its instantaneous log-growth rate (per hour) as
# G0 / (1 + t / TG), with t the hours since release; integrated over an
# interval it gives the log growth of the tracked count. G0 and TG are
# calibrated to the launch-day shape (a ~6x tracked-count jump over the
# first ~5 hours, then a much slower climb), not to any single answer.

G0 = 0.85
TG = 1.5


def _log_tracked_growth(t_start_h, t_end_h):
    """Log growth of the tracked count between two times (hours since release)."""
    if t_end_h <= t_start_h:
        return 0.0
    lo = 1.0 + t_start_h / TG
    hi = 1.0 + t_end_h / TG
    if lo <= 0.0:
        lo = 1e-9
    if hi <= 0.0:
        hi = 1e-9
    return G0 * TG * (math.log(hi) - math.log(lo))


def _early_fraction(description, tier):
    """Fraction of the tracked-count growth that a trophy's earned count
    keeps up with, from how early it sits in the game. Early story beats
    and first-hour activities are reached by almost every new player, so
    their earners grow nearly as fast as the player base; late chapters,
    grinds and the platinum barely move while the denominator multiplies."""
    desc = (description or "").lower()
    if tier == "platinum":
        return 0.05
    if "gone fishing" in desc or "beat cal" in desc or "fishing challenge" in desc:
        return 0.90
    if "chapter 1" in desc:
        return 0.80
    if "arcade" in desc or "breakfast run" in desc or "discover 100" in desc:
        return 0.50
    if "chapter 2" in desc:
        return 0.35
    if "100% completion" in desc or "250 stunts" in desc or "100 locations" in desc:
        return 0.05
    return 0.10


# --- trend fit (moving history) ------------------------------------------

def _least_squares_slope(xs, ys):
    """Slope of the least-squares line through (xs, ys); 0.0 if degenerate."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = 0.0
    sxy = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        sxx += dx * dx
        sxy += dx * (y - my)
    if sxx <= 0.0:
        return 0.0
    return sxy / sxx


# --- per-case forecast -----------------------------------------------------

def _forecast_case(case):
    if case.get("levels") != LEVELS:
        raise ValueError("levels are not the scored levels")
    trophies = case["trophies"]
    history = case["history"]
    if not history:
        raise ValueError("no history")
    horizon_h = case["horizon_minutes"] / 60.0
    target = _parse_time(case.get("target"))
    checkpoint = _parse_time(case.get("at"))

    # Release instant, from the game's release date (midnight UTC that day).
    release = None
    game = case.get("game") or {}
    rd = game.get("release_date")
    if rd:
        try:
            release = datetime.fromisoformat(rd + "T00:00:00+00:00")
        except ValueError:
            release = None
    if release is None:
        release = _parse_time(history[0].get("at"))

    # Read times (hours since release) and the series of tracked counts.
    times_h = []
    tracked = []
    for read in history:
        t = _parse_time(read.get("at"))
        if t is None or release is None:
            times_h.append(0.0)
        else:
            times_h.append(_hours_between(release, t))
        tracked.append(read.get("players_tracked") or 0)

    last = history[-1]
    last_rates = last["rates"]
    last_tracked = last.get("players_tracked") or 0

    # Is the page stale? Every read identical (same tracked count and the
    # same rates) means Exophase has not refreshed in the whole window.
    flat = True
    for read in history:
        if (read.get("players_tracked") or 0) != last_tracked:
            flat = False
            break
        if read["rates"] != last_rates:
            flat = False
            break

    rows = []
    if flat:
        # --- refresh prior ----------------------------------------------
        # The page was set around the first read and will refresh by the
        # target; the tracked count has been growing since then.
        first_t = _parse_time(history[0].get("at"))
        t_first = _hours_between(release, first_t) if first_t is not None else 0.0
        t_target = _hours_between(release, target) if target is not None else t_first + horizon_h
        # Full accumulated growth since the page was set: a page that has
        # sat unchanged for hours is due a refresh, and the competition's
        # practice cases straddle one, so the forecast takes the whole
        # jump rather than hedging it away. The spread below carries the
        # uncertainty about the refresh's exact size and timing.
        log_growth = _log_tracked_growth(t_first, t_target)
        spread = 0.5 * math.sqrt(1.0 + horizon_h / 24.0)
        for i, trophy in enumerate(trophies):
            rate = last_rates[i]
            if rate is None:
                rate = 0.0
            if rate >= 99.99:
                rows.append({"id": trophy["id"], "q": [99.99, 99.99, 99.99, 99.99, 99.99]})
                continue
            frac = _early_fraction(trophy.get("description"), trophy.get("tier"))
            drift = (frac - 1.0) * log_growth
            centre = _logit(rate) + drift
            qs = []
            for z in Z:
                qs.append(round(_clamp_pct(_inv_logit(centre + z * spread)), 4))
            # Keep the row non-decreasing after rounding.
            for k in range(1, 5):
                if qs[k] < qs[k - 1]:
                    qs[k] = qs[k - 1]
            rows.append({"id": trophy["id"], "q": qs})
    else:
        # --- trend extrapolation ----------------------------------------
        # Fit each trophy's logit-rate trend over the recent reads (the
        # last 24 hours of history, or all of it when shorter), then
        # extrapolate with a damping factor that shrinks the trend as the
        # horizon grows, so a long forecast reverts toward persistence.
        damp = 1.0 / (1.0 + horizon_h / 36.0)
        spread = 0.5 * math.sqrt(1.0 + horizon_h / 24.0)
        # Recent window: reads within the last 24 h of the checkpoint.
        if checkpoint is not None and release is not None:
            t_check = _hours_between(release, checkpoint)
        else:
            t_check = times_h[-1] if times_h else 0.0
        recent_idx = [j for j, th in enumerate(times_h) if th >= t_check - 24.0]
        if len(recent_idx) < 3:
            recent_idx = list(range(len(times_h)))
        xs = [times_h[j] for j in recent_idx]
        for i, trophy in enumerate(trophies):
            ys = []
            ok = True
            for j in recent_idx:
                r = history[j]["rates"][i]
                if r is None:
                    ok = False
                    break
                ys.append(_logit(r))
            if not ok or len(ys) < 2:
                slope = 0.0
            else:
                slope = _least_squares_slope(xs, ys)
            # Clamp wild slopes: no trophy's logit rate moves that fast.
            if slope > 0.10:
                slope = 0.10
            elif slope < -0.10:
                slope = -0.10
            rate = last_rates[i]
            if rate is None:
                rate = 0.0
            if rate >= 99.99:
                rows.append({"id": trophy["id"], "q": [99.99, 99.99, 99.99, 99.99, 99.99]})
                continue
            centre = _logit(rate) + slope * horizon_h * damp
            qs = []
            for z in Z:
                qs.append(round(_clamp_pct(_inv_logit(centre + z * spread)), 4))
            for k in range(1, 5):
                if qs[k] < qs[k - 1]:
                    qs[k] = qs[k - 1]
            rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = _forecast_case(case)
        out = OUTPUT_DIR / (path.stem + ".out")
        out.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
