from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from subsentry.core.stats import median, mad

CANDIDATE_PERIODS = [7, 14, 28, 30, 31, 365]

@dataclass
class SeriesResult:
    period_days: int
    amount_median: float
    amount_mad: float
    gap_median: float
    gap_mad: float
    confidence: float
    next_expected_at: datetime

def _nearest_period(days: float) -> int:
    return min(CANDIDATE_PERIODS, key=lambda p: abs(p - days))

def detect_recurring(dates: Sequence[datetime], amounts: Sequence[float], min_points: int = 3) -> SeriesResult | None:
    if len(dates) < min_points:
        return None
    pairs = sorted(zip(dates, amounts), key=lambda x: x[0])
    ds = [p[0] for p in pairs]
    am = [float(p[1]) for p in pairs]
    gaps = [(ds[i] - ds[i-1]).days for i in range(1, len(ds))]
    if not gaps:
        return None

    gap_med = median(gaps)
    gap_mad = mad(gaps)
    period = _nearest_period(gap_med)

    tol = 3 if period in (7, 14, 28, 30, 31) else 10
    inliers = [g for g in gaps if abs(g - period) <= tol]
    gap_consistency = len(inliers) / max(1, len(gaps))

    a_med = median(am)
    a_mad = mad(am)
    amt_stability = 1.0 / (1.0 + (a_mad / max(1e-6, abs(a_med) + 1e-6)))

    confidence = float(max(0.0, min(1.0, 0.55 * gap_consistency + 0.45 * amt_stability)))
    next_expected = ds[-1] + timedelta(days=int(period))

    return SeriesResult(
        period_days=int(period),
        amount_median=a_med,
        amount_mad=a_mad,
        gap_median=gap_med,
        gap_mad=gap_mad,
        confidence=confidence,
        next_expected_at=next_expected,
    )
