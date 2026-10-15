"""Curva patrón de peatones por estación × día de la semana × hora."""
from __future__ import annotations

import pandas as pd


def quarter_key(ts: pd.Timestamp) -> tuple[int, int]:
    return ts.year, (ts.month - 1) // 3 + 1


def last_quarters(counts: pd.DataFrame, n: int = 2) -> list[tuple[int, int]]:
    """Los `n` últimos trimestres CON DATOS (no los del calendario)."""
    q = counts["ts"].dt.year * 10 + (counts["ts"].dt.month - 1) // 3 + 1
    keys = sorted(q.unique())[-n:]
    return [(int(k) // 10, int(k) % 10) for k in keys]


def filter_quarters(counts: pd.DataFrame, quarters: list[tuple[int, int]]) -> pd.DataFrame:
    q = list(zip(counts["ts"].dt.year, (counts["ts"].dt.month - 1) // 3 + 1))
    mask = pd.Series([k in set(quarters) for k in q], index=counts.index)
    return counts[mask]


def build_patterns(counts: pd.DataFrame) -> pd.DataFrame:
    """counts: columnas station_id, ts (datetime), pedestrians.

    Devuelve station_id, dow (0=lunes), hour, mean, p30, p70, n_obs.
    """
    df = counts.copy()
    df["dow"] = df["ts"].dt.dayofweek
    df["hour"] = df["ts"].dt.hour
    g = df.groupby(["station_id", "dow", "hour"])["pedestrians"]
    out = pd.DataFrame(
        {
            "mean": g.mean(),
            "p30": g.quantile(0.30),
            "p70": g.quantile(0.70),
            "n_obs": g.size(),
        }
    ).reset_index()
    return out
