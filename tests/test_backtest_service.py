from datetime import date

import pandas as pd
import pytest

from energy_hub.backtesting.service import (
    HistoricalBacktestRequest,
    build_battery_from_request,
    run_historical_backtest,
)
from energy_hub.config import load_config


def _request(**overrides) -> HistoricalBacktestRequest:
    values = {
        "start": date(2026, 9, 1),
        "end": date(2026, 9, 3),
        "area": "DK1",
        "wind_capacity_mw": 100.0,
        "battery_energy_mwh": 100.0,
        "charge_power_mw": 25.0,
        "discharge_power_mw": 25.0,
        "initial_soc_pct": 50.0,
        "terminal_soc_pct": 50.0,
        "solver": "highs",
    }
    values.update(overrides)
    return HistoricalBacktestRequest(**values)


def test_request_converts_soc_percentages_to_battery_mwh() -> None:
    base = load_config("configs/base.yaml")

    battery = build_battery_from_request(base.battery, _request())

    assert battery.energy_capacity_mwh == pytest.approx(100.0)
    assert battery.charge_power_mw == pytest.approx(25.0)
    assert battery.discharge_power_mw == pytest.approx(25.0)
    assert battery.initial_soc_mwh == pytest.approx(50.0)
    assert battery.terminal_soc_mwh == pytest.approx(50.0)
    assert battery.charge_efficiency == pytest.approx(base.battery.charge_efficiency)


def test_request_rejects_invalid_dates_soc_and_area() -> None:
    with pytest.raises(ValueError, match="start"):
        _request(end=date(2026, 9, 1))
    with pytest.raises(ValueError, match="SOC"):
        _request(initial_soc_pct=101.0)
    with pytest.raises(ValueError, match="DK1"):
        _request(area="DK2")


def test_service_reuses_capacity_data_path_and_daily_backtest() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def fetch_hourly_inputs_for_capacity(
            self, start, end, price_area: str, wind_capacity_mw: float
        ) -> pd.DataFrame:
            self.calls.append((start, end, price_area, wind_capacity_mw))
            timestamps = pd.date_range("2026-09-01", periods=48, freq="h")
            prices = [20.0 if hour % 24 < 12 else 100.0 for hour in range(48)]
            return pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "wind_mwh": [30.0] * 48,
                    "price_eur_mwh": prices,
                }
            )

    client = FakeClient()
    base = load_config("configs/base.yaml")

    bundle = run_historical_backtest(_request(), base.battery, client=client)

    assert client.calls == [(date(2026, 9, 1), date(2026, 9, 3), "DK1", 100.0)]
    assert len(bundle.inputs) == 48
    assert bundle.result.summary["days"] == 2
    assert bundle.result.summary["optimized_revenue_eur"] >= bundle.result.summary[
        "baseline_curtail_negative_revenue_eur"
    ]
