from __future__ import annotations

import numpy as np

def median(x: list[float]) -> float:
    return float(np.median(np.asarray(x, dtype=float))) if x else 0.0

def mad(x: list[float], scale: float = 1.4826) -> float:
    if not x:
        return 0.0
    arr = np.asarray(x, dtype=float)
    med = np.median(arr)
    val = np.median(np.abs(arr - med))
    return float(val * scale)

def robust_z(x: float, med: float, mad_val: float) -> float:
    denom = mad_val if mad_val > 1e-9 else 1.0
    return (x - med) / denom
