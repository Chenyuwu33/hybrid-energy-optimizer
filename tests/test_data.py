from pathlib import Path

import pandas as pd
import pytest

from energy_hub.data.io import load_hourly_inputs


def _write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "input.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_sample_csv_loads_24_monotonic_hourly_rows() -> None:
    data = load_hourly_inputs("data/sample/sample_24h.csv")
    assert len(data) == 24
    assert pd.api.types.is_datetime64_any_dtype(data["timestamp"])
    assert data["timestamp"].is_monotonic_increasing
    assert (data["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()


@pytest.mark.parametrize("missing", ["wind_mwh", "price_eur_mwh"])
def test_missing_required_column_raises(tmp_path: Path, missing: str) -> None:
    columns = ["timestamp", "wind_mwh", "price_eur_mwh"]
    columns.remove(missing)
    path = _write_csv(tmp_path, ",".join(columns) + "\n2026-01-01T00:00:00,1\n")
    with pytest.raises(ValueError, match=missing):
        load_hourly_inputs(path)


def test_nan_raises(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n2026-01-01T00:00:00,,50\n",
    )
    with pytest.raises(ValueError, match="missing"):
        load_hourly_inputs(path)


def test_duplicate_timestamp_raises(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n"
        "2026-01-01T00:00:00,10,20\n"
        "2026-01-01T00:00:00,12,25\n",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_hourly_inputs(path)


def test_empty_csv_raises(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "timestamp,wind_mwh,price_eur_mwh\n")
    with pytest.raises(ValueError, match="empty"):
        load_hourly_inputs(path)


def test_negative_wind_raises(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n2026-01-01T00:00:00,-1,20\n",
    )
    with pytest.raises(ValueError, match="wind"):
        load_hourly_inputs(path)


def test_negative_price_is_allowed(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n2026-01-01T00:00:00,10,-20\n",
    )
    data = load_hourly_inputs(path)
    assert data.loc[0, "price_eur_mwh"] == pytest.approx(-20.0)


def test_unsorted_timestamps_raise(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n"
        "2026-01-01T01:00:00,10,20\n"
        "2026-01-01T00:00:00,10,20\n",
    )
    with pytest.raises(ValueError, match="increasing"):
        load_hourly_inputs(path)


def test_non_hourly_timestamps_raise(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "timestamp,wind_mwh,price_eur_mwh\n"
        "2026-01-01T00:00:00,10,20\n"
        "2026-01-01T00:30:00,10,20\n",
    )
    with pytest.raises(ValueError, match="hourly"):
        load_hourly_inputs(path)
