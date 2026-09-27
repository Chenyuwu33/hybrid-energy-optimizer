"""Wind input validation."""

import pandas as pd


def validate_wind_series(series: pd.Series) -> None:
    """Validate non-negative wind energy availability."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        raise ValueError("wind_mwh contains missing or non-numeric values")
    if (numeric < 0).any():
        raise ValueError("wind_mwh must be non-negative")
