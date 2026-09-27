"""Electricity-market input validation."""

import pandas as pd


def validate_price_series(series: pd.Series) -> None:
    """Validate electricity prices; negative prices are intentionally allowed."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        raise ValueError("price_eur_mwh contains missing or non-numeric values")
