"""CSV loading for hourly wind and market inputs."""

from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

from energy_hub.data.market import validate_price_series
from energy_hub.data.wind import validate_wind_series

_REQUIRED_COLUMNS = ("timestamp", "wind_mwh", "price_eur_mwh")


def load_hourly_inputs(path: str | Path) -> pd.DataFrame:
    """Load and validate an hourly input CSV without modifying the source file."""
    input_path = Path(path)
    try:
        data = pd.read_csv(input_path)
    except EmptyDataError as exc:
        raise ValueError("input dataset is empty") from exc
    except FileNotFoundError as exc:
        raise ValueError(f"input CSV not found: {input_path}") from exc

    if data.empty:
        raise ValueError("input dataset is empty")

    missing = [column for column in _REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"missing required column(s): {', '.join(missing)}")

    data = data.loc[:, list(_REQUIRED_COLUMNS)].copy()
    if data.isna().any().any():
        raise ValueError("input dataset contains missing values")

    timestamps = pd.to_datetime(data["timestamp"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("timestamp contains invalid or missing values")
    data["timestamp"] = timestamps

    if data["timestamp"].duplicated().any():
        raise ValueError("duplicate timestamps are not allowed")
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be strictly increasing")

    diffs = data["timestamp"].diff().dropna()
    if not diffs.empty and not (diffs == pd.Timedelta(hours=1)).all():
        raise ValueError("timestamps must use an hourly interval")

    validate_wind_series(data["wind_mwh"])
    validate_price_series(data["price_eur_mwh"])
    data["wind_mwh"] = pd.to_numeric(data["wind_mwh"], errors="raise").astype(float)
    data["price_eur_mwh"] = pd.to_numeric(data["price_eur_mwh"], errors="raise").astype(float)
    return data.reset_index(drop=True)
