from datetime import date

import pandas as pd
import pytest

from energy_hub.data.energinet import (
    DAY_AHEAD_CUTOFF,
    EnerginetClient,
    build_hourly_inputs,
    normalize_price_records,
    normalize_wind_records,
    price_datasets_for_period,
)


def test_new_day_ahead_prices_are_aggregated_from_15_minutes_to_hourly() -> None:
    records = [
        {"TimeUTC": "2026-01-02T00:00:00", "PriceArea": "DK1", "DayAheadPriceEUR": 10.0},
        {"TimeUTC": "2026-01-02T00:15:00", "PriceArea": "DK1", "DayAheadPriceEUR": 20.0},
        {"TimeUTC": "2026-01-02T00:30:00", "PriceArea": "DK1", "DayAheadPriceEUR": 30.0},
        {"TimeUTC": "2026-01-02T00:45:00", "PriceArea": "DK1", "DayAheadPriceEUR": 40.0},
        {"TimeUTC": "2026-01-02T01:00:00", "PriceArea": "DK1", "DayAheadPriceEUR": 50.0},
        {"TimeUTC": "2026-01-02T01:15:00", "PriceArea": "DK1", "DayAheadPriceEUR": 60.0},
        {"TimeUTC": "2026-01-02T01:30:00", "PriceArea": "DK1", "DayAheadPriceEUR": 70.0},
        {"TimeUTC": "2026-01-02T01:45:00", "PriceArea": "DK1", "DayAheadPriceEUR": 80.0},
    ]

    prices = normalize_price_records(records, dataset="DayAheadPrices")

    assert prices["price_eur_mwh"].tolist() == pytest.approx([25.0, 65.0])
    assert prices["timestamp"].tolist() == [
        pd.Timestamp("2026-01-02T00:00:00"),
        pd.Timestamp("2026-01-02T01:00:00"),
    ]


def test_legacy_elspot_prices_remain_hourly() -> None:
    records = [
        {"HourUTC": "2025-09-29T22:00:00", "PriceArea": "DK1", "SpotPriceEUR": 42.5},
        {"HourUTC": "2025-09-29T23:00:00", "PriceArea": "DK1", "SpotPriceEUR": -3.0},
    ]

    prices = normalize_price_records(records, dataset="Elspotprices")

    assert prices["price_eur_mwh"].tolist() == pytest.approx([42.5, -3.0])


def test_price_dataset_selection_switches_at_october_2025() -> None:
    cutoff = DAY_AHEAD_CUTOFF
    assert price_datasets_for_period(date(2025, 9, 1), cutoff) == ["Elspotprices"]
    assert price_datasets_for_period(cutoff, date(2025, 11, 1)) == ["DayAheadPrices"]
    assert price_datasets_for_period(date(2025, 9, 1), date(2025, 11, 1)) == [
        "Elspotprices",
        "DayAheadPrices",
    ]


def test_wind_production_sums_all_onshore_and_offshore_columns() -> None:
    records = [
        {
            "HourUTC": "2026-01-02T00:00:00",
            "PriceArea": "DK1",
            "OffshoreWindGe100MW_MWh": 100.0,
            "OffshoreWindLt100MW_MWh": 10.0,
            "OnshoreWindGe50kW_MWh": 200.0,
            "OnshoreWindLt50kW_MWh": 2.0,
        }
    ]

    wind = normalize_wind_records(records)

    assert wind.loc[0, "dk1_wind_mwh"] == pytest.approx(312.0)


def test_build_hourly_inputs_applies_explicit_wind_portfolio_share() -> None:
    prices = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-02T00:00:00", "2026-01-02T01:00:00"]),
            "price_eur_mwh": [25.0, 65.0],
        }
    )
    wind = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-02T00:00:00", "2026-01-02T01:00:00"]),
            "dk1_wind_mwh": [1000.0, 1200.0],
        }
    )

    inputs = build_hourly_inputs(prices, wind, wind_share=0.05)

    assert inputs.columns.tolist() == ["timestamp", "wind_mwh", "price_eur_mwh"]
    assert inputs["wind_mwh"].tolist() == pytest.approx([50.0, 60.0])


def test_build_hourly_inputs_rejects_invalid_share_or_missing_hours() -> None:
    prices = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-02T00:00:00"]),
            "price_eur_mwh": [25.0],
        }
    )
    wind = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-02T01:00:00"]),
            "dk1_wind_mwh": [1000.0],
        }
    )

    with pytest.raises(ValueError, match="wind_share"):
        build_hourly_inputs(prices, wind, wind_share=0.0)
    with pytest.raises(ValueError, match="overlapping"):
        build_hourly_inputs(prices, wind, wind_share=0.05)


def test_fetch_hourly_inputs_pads_local_api_range_and_trims_to_requested_utc_days() -> None:
    class StubClient(EnerginetClient):
        def __init__(self) -> None:
            self.price_call = None
            self.wind_call = None

        def fetch_hourly_prices(self, start: date, end: date, price_area: str) -> pd.DataFrame:
            self.price_call = (start, end, price_area)
            timestamps = pd.date_range("2025-12-31T23:00:00", periods=26, freq="h")
            return pd.DataFrame(
                {"timestamp": timestamps, "price_eur_mwh": [50.0] * len(timestamps)}
            )

        def fetch_hourly_wind(self, start: date, end: date, price_area: str) -> pd.DataFrame:
            self.wind_call = (start, end, price_area)
            timestamps = pd.date_range("2025-12-31T23:00:00", periods=26, freq="h")
            return pd.DataFrame(
                {"timestamp": timestamps, "dk1_wind_mwh": [1000.0] * len(timestamps)}
            )

    client = StubClient()
    inputs = client.fetch_hourly_inputs(
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        price_area="DK1",
        wind_share=0.05,
    )

    assert client.price_call == (date(2025, 12, 31), date(2026, 1, 3), "DK1")
    assert client.wind_call == (date(2025, 12, 31), date(2026, 1, 3), "DK1")
    assert len(inputs) == 24
    assert inputs["timestamp"].iloc[0] == pd.Timestamp("2026-01-01T00:00:00")
    assert inputs["timestamp"].iloc[-1] == pd.Timestamp("2026-01-01T23:00:00")
