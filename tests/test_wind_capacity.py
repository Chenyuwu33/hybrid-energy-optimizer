from __future__ import annotations

import pandas as pd
import pytest

from energy_hub.data.wind_capacity import (
    DK1_MUNICIPALITY_CODES,
    aggregate_dk1_onshore_wind_capacity,
    normalize_capacity_records,
    scale_dk1_onshore_wind_to_farm,
)


def test_normalize_capacity_records_keeps_month_municipality_and_onshore_capacity() -> None:
    records = [
        {
            "Month": "2026-09-01T00:00:00",
            "MunicipalityNo": "561",
            "OnshoreWindCapacity": 120.5,
            "OffshoreWindCapacity": 0.0,
        }
    ]

    normalized = normalize_capacity_records(records)

    assert normalized.columns.tolist() == ["month", "municipality_no", "onshore_wind_capacity_mw"]
    assert normalized.loc[0, "month"] == pd.Timestamp("2026-09-01")
    assert normalized.loc[0, "municipality_no"] == "561"
    assert normalized.loc[0, "onshore_wind_capacity_mw"] == pytest.approx(120.5)


def test_aggregate_dk1_onshore_capacity_excludes_east_denmark_and_special_records() -> None:
    assert "561" in DK1_MUNICIPALITY_CODES
    assert "101" not in DK1_MUNICIPALITY_CODES
    assert "1" not in DK1_MUNICIPALITY_CODES

    capacity = pd.DataFrame(
        {
            "month": pd.to_datetime(["2026-09-01", "2026-09-01", "2026-09-01"]),
            "municipality_no": ["561", "607", "101"],
            "onshore_wind_capacity_mw": [100.0, 25.0, 999.0],
        }
    )

    aggregated = aggregate_dk1_onshore_wind_capacity(capacity)

    assert aggregated.to_dict("records") == [
        {"month": pd.Timestamp("2026-09-01"), "dk1_onshore_capacity_mw": 125.0}
    ]


def test_scale_dk1_onshore_wind_to_farm_uses_monthly_capacity_factor() -> None:
    wind = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-09-01T00:00:00", "2026-09-01T01:00:00"]),
            "dk1_onshore_wind_mwh": [500.0, 1000.0],
        }
    )
    capacity = pd.DataFrame(
        {"month": pd.to_datetime(["2026-09-01"]), "dk1_onshore_capacity_mw": [2000.0]}
    )

    scaled = scale_dk1_onshore_wind_to_farm(wind, capacity, wind_capacity_mw=100.0)

    assert scaled.columns.tolist() == ["timestamp", "wind_mwh"]
    assert scaled["wind_mwh"].tolist() == pytest.approx([25.0, 50.0])


def test_scale_rejects_missing_capacity_month_or_impossible_capacity_factor() -> None:
    wind = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-09-01T00:00:00"]),
            "dk1_onshore_wind_mwh": [2100.0],
        }
    )
    missing_month = pd.DataFrame(
        {"month": pd.to_datetime(["2026-08-01"]), "dk1_onshore_capacity_mw": [2000.0]}
    )
    with pytest.raises(ValueError, match="installed capacity"):
        scale_dk1_onshore_wind_to_farm(wind, missing_month, wind_capacity_mw=100.0)

    september = pd.DataFrame(
        {"month": pd.to_datetime(["2026-09-01"]), "dk1_onshore_capacity_mw": [2000.0]}
    )
    with pytest.raises(ValueError, match="capacity factor"):
        scale_dk1_onshore_wind_to_farm(wind, september, wind_capacity_mw=100.0)


def test_scale_rejects_nonpositive_hypothetical_farm_capacity() -> None:
    wind = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-09-01T00:00:00"]),
            "dk1_onshore_wind_mwh": [500.0],
        }
    )
    capacity = pd.DataFrame(
        {"month": pd.to_datetime(["2026-09-01"]), "dk1_onshore_capacity_mw": [2000.0]}
    )

    with pytest.raises(ValueError, match="wind_capacity_mw"):
        scale_dk1_onshore_wind_to_farm(wind, capacity, wind_capacity_mw=0.0)
