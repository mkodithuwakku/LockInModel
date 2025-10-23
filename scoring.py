import pandas as pd
from logger import get_logger
log = get_logger(__name__)

"""Fantasy scoring helpers.

This module provides utilities to compute fantasy points for player game rows
and to apply that calculation across a DataFrame.

Doclinks / cross-references:
- :class:`pandas.Series` and :class:`pandas.DataFrame`
- :func:`fantasy_points` and :func:`add_fantasy_points`
"""

def fantasy_points(row: pd.Series, weights: dict) -> float:
    """Compute fantasy points for a single game row.

    The calculation multiplies each stat value found in `row` by the corresponding
    weight in `weights` and returns the summed total.

    Parameters
    ----------
    row : :class:`pandas.Series`
        A single player's game row. Missing stats should be treated as zero.
    weights : dict
        Mapping of stat name (str) to weight (numeric). Keys are matched against
        the row's index/columns.

    Returns
    -------
    float
        Total fantasy points for the row.

    See Also
    --------
    :func:`add_fantasy_points`
        Apply this function across a :class:`pandas.DataFrame`.
    """
    total = 0.0
    for stat, w in weights.items():
        total += float(row.get(stat, 0) or 0) * float(w)
    return float(total)

def add_fantasy_points(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Return a copy of `df` with a fantasy points column ("FP") added.

    This applies :func:`fantasy_points` to each row of `df` and stores the result
    in a new column named "FP".

    Parameters
    ----------
    df : :class:`pandas.DataFrame`
        DataFrame of player game logs where each row represents a game and columns
        correspond to stat names used as keys in `weights`.
    weights : dict
        Mapping of stat name (str) to weight (numeric) used by :func:`fantasy_points`.

    Returns
    -------
    :class:`pandas.DataFrame`
        A copy of the input DataFrame with an additional "FP" column.

    Notes
    -----
    The input DataFrame is copied before modification to avoid side effects.
    """

    out = df.copy()
    # ensure any weighted column exists
    for k in weights.keys():
        if k not in out.columns:
            out[k] = 0

    # compute FP
    out["FP"] = 0.0
    for k, w in weights.items():
        out["FP"] += out[k].astype(float) * float(w or 0.0)
    return out
