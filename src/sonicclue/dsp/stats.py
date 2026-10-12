"""Statistics for comparisons and uncertainty.

Measurement uncertainty and diagnostic evidence strength are separate.
Everything here describes measurement uncertainty only.

* Welch estimate spread: a band integrating B effectively independent bins
  from n_eff independent averages has relative standard deviation about
  1/sqrt(n_eff*B), so the level standard deviation in dB is about
  4.343/sqrt(n_eff*B). This is the "estimated" repeatability, used when only
  one capture per condition exists. It ignores real-world variability
  (source changes, positioning), so the comparison is labelled "estimated"
  and DIAG rules treat it as weaker than measured repeatability.
* Measured repeatability: with repeats in both conditions, use the
  Welch-Satterthwaite t-interval on the per-capture dB levels (95%).
* An effect counts as significant only when |delta| exceeds both the 95%
  interval and a minimum practical effect (MIN_EFFECT_DB). This stops tiny
  but statistically resolvable differences from being called improvements.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

MIN_EFFECT_DB = 1.0
ESTIMATED_FLOOR_DB = 0.5  # never claim better than +/-0.5 dB from a single capture


def welch_level_sd_db(n_eff: int, bins: float) -> float:
    n = max(1.0, float(n_eff) * max(1.0, bins))
    return 4.343 / math.sqrt(n)


def compare_levels(a_db: list[float], b_db: list[float], sd_est_a: float, sd_est_b: float):
    """Return (delta_db, u95_db, significant, kind), with delta = mean(B) - mean(A)."""
    a = np.asarray(a_db, float)
    b = np.asarray(b_db, float)
    delta = float(b.mean() - a.mean())
    if len(a) >= 2 and len(b) >= 2:
        va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
        se = math.sqrt(va + vb)
        if se > 0:
            dof = (va + vb) ** 2 / ((va**2) / (len(a) - 1) + (vb**2) / (len(b) - 1)) if (va + vb) > 0 else 1.0
            t = float(stats.t.ppf(0.975, max(1.0, dof)))
        else:
            t = 2.0
        u = max(t * se, ESTIMATED_FLOOR_DB / 2)
        kind = "measured"
    else:
        u = max(2.0 * math.sqrt(sd_est_a**2 + sd_est_b**2), ESTIMATED_FLOOR_DB)
        kind = "estimated"
    sig = abs(delta) > max(u, MIN_EFFECT_DB)
    return delta, float(u), bool(sig), kind


def power_mean_db(levels_db: list[float]) -> float:
    """Energy-average of dB levels (used when pooling repeats into one figure)."""
    if not levels_db:
        return float("nan")
    return 10 * math.log10(float(np.mean(10 ** (np.asarray(levels_db) / 10))))
