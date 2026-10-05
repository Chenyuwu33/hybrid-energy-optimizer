from datetime import date

import pandas as pd
import pytest

from energy_hub.data.energinet import EnerginetClient, normalize_wind_records


def test_wind_normalization_preserves_total_and_onshore_generation() -> None:
    records = [
        {
            "HourUTC": "2026-09-01T00:00:00",
            "PriceArea": "DK1",
            "OffshoreWindGe100MW_MWh": 100.0,
            "OffshoreWindLt100MW_MWh": 10.0,
            "OnshoreWindGe50kW_MWh": 200.0,
            "OnshoreWindLt50kW_MWh": 20.0,
        }
    ]

    wind = normalize_wind_records(records)

    assert wind.loc[0, "dk1_wind_mwh"] == pytest.approx(330.0)
    assert wind.loc[0, "dk1_onshore_wind_mwh"] == pytest.approx(220.0)


def test_capacity_based_fetch_returns_exact_utc_days_in_optimizer_schema() -> None:
    class StubClient(EnerginetClient):
        def __init__(self) -> None:
            self.price_call = None
            self.wind_call = None
            self.capacity_call = None

        def fetch_hourly_prices(self, start: date, end: date, price_area: str) -> pd.DataFrame:
            self.price_call = (start, end, price_area)
            timestamps = pd.date_range("2026-08-31T23:00:00", periods=26, freq="h")
            return pd.DataFrame(
                {"timestamp": timestamps, "price_eur_mwh": [50.0] * len(timestamps)}
            )

        def fetch_hourly_wind(self, start: date, end: date, price_area: str) -> pd.DataFrame:
            self.wind_call = (start, end, price_area)
            timestamps = pd.date_range("2026-08-31T23:00:00", periods=26, freq="h")
            return pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "dk1_wind_mwh": [1100.0] * len(timestamps),
                    "dk1_onshore_wind_mwh": [500.0] * len(timestamps),
                }
            )

        def fetch_monthly_wind_capacity(self, start: date, end: date) -> pd.DataFrame:
            self.capacity_call = (start, end)
            return pd.DataFrame(
                {
                    "month": pd.to_datetime(["2026-09-01"]),
                    "dk1_onshore_capacity_mw": [2000.0],
                }
            )

    client = StubClient()
    inputs = client.fetch_hourly_inputs_for_capacity(
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        price_area="DK1",
        wind_capacity_mw=100.0,
    )

    assert client.price_call == (date(2026, 8, 31), date(2026, 9, 3), "DK1")
    assert client.wind_call == (date(2026, 8, 31), date(2026, 9, 3), "DK1")
    assert client.capacity_call == (date(2026, 9, 1), date(2026, 10, 1))
    assert inputs.columns.tolist() == ["timestamp", "wind_mwh", "price_eur_mwh"]
    assert len(inputs) == 24
    assert inputs["wind_mwh"].tolist() == pytest.approx([25.0] * 24)
    assert inputs["timestamp"].iloc[0] == pd.Timestamp("2026-09-01T00:00:00")
    assert inputs["timestamp"].iloc[-1] == pd.Timestamp("2026-09-01T23:00:00")
