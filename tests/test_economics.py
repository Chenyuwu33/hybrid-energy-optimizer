import math

import pandas as pd
import pytest

from energy_hub.assets.battery import Battery
from energy_hub.economics.metrics import calculate_baseline_revenue, calculate_kpis
from energy_hub.optimization.results import DispatchResult


def _battery(cost: float = 0.0) -> Battery:
    return Battery(
        energy_capacity_mwh=20.0,
        charge_power_mw=10.0,
        discharge_power_mw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_mwh=0.0,
        max_soc_mwh=20.0,
        initial_soc_mwh=0.0,
        terminal_soc_mwh=0.0,
        throughput_cost_eur_per_mwh=cost,
    )


def test_baseline_revenue_is_hand_calculable() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_mwh": [10.0, 20.0],
            "price_eur_mwh": [30.0, 50.0],
        }
    )
    assert calculate_baseline_revenue(inputs) == pytest.approx(1300.0)


def test_kpis_include_revenue_uplift_flows_cycles_and_soc() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_mwh": [10.0, 10.0],
            "price_eur_mwh": [10.0, 100.0],
        }
    )
    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"],
            "wind_available_mwh": [10.0, 10.0],
            "price_eur_mwh": [10.0, 100.0],
            "wind_to_grid_mwh": [0.0, 10.0],
            "battery_charge_mwh": [10.0, 0.0],
            "battery_discharge_mwh": [0.0, 10.0],
            "grid_export_mwh": [0.0, 20.0],
            "curtailment_mwh": [0.0, 0.0],
            "soc_mwh": [10.0, 0.0],
        }
    )
    result = DispatchResult(dispatch=dispatch, objective_eur=1990.0, solver_status="optimal")
    kpis = calculate_kpis(inputs, result, _battery(cost=0.5))

    assert kpis["baseline_revenue_eur"] == pytest.approx(1100.0)
    assert kpis["optimized_revenue_eur"] == pytest.approx(1990.0)
    assert kpis["revenue_uplift_eur"] == pytest.approx(890.0)
    assert kpis["revenue_uplift_pct"] == pytest.approx(890.0 / 1100.0 * 100.0)
    assert kpis["total_wind_mwh"] == pytest.approx(20.0)
    assert kpis["total_grid_export_mwh"] == pytest.approx(20.0)
    assert kpis["total_battery_charge_mwh"] == pytest.approx(10.0)
    assert kpis["total_battery_discharge_mwh"] == pytest.approx(10.0)
    assert kpis["total_curtailment_mwh"] == pytest.approx(0.0)
    assert kpis["average_realized_price_eur_per_mwh"] == pytest.approx(100.0)
    assert kpis["equivalent_full_cycles"] == pytest.approx(0.5)
    assert kpis["min_soc_mwh"] == pytest.approx(0.0)
    assert kpis["max_soc_mwh"] == pytest.approx(10.0)
    assert kpis["solver_status"] == "optimal"


def test_zero_wind_kpis_are_finite_and_defined() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_mwh": [0.0, 0.0],
            "price_eur_mwh": [20.0, 30.0],
        }
    )
    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"],
            "wind_available_mwh": [0.0, 0.0],
            "price_eur_mwh": [20.0, 30.0],
            "wind_to_grid_mwh": [0.0, 0.0],
            "battery_charge_mwh": [0.0, 0.0],
            "battery_discharge_mwh": [0.0, 0.0],
            "grid_export_mwh": [0.0, 0.0],
            "curtailment_mwh": [0.0, 0.0],
            "soc_mwh": [0.0, 0.0],
        }
    )
    kpis = calculate_kpis(
        inputs,
        DispatchResult(dispatch=dispatch, objective_eur=0.0, solver_status="optimal"),
        _battery(),
    )
    assert kpis["baseline_revenue_eur"] == 0.0
    assert kpis["optimized_revenue_eur"] == 0.0
    assert kpis["revenue_uplift_eur"] == 0.0
    assert kpis["revenue_uplift_pct"] == 0.0
    assert kpis["equivalent_full_cycles"] == 0.0
    assert kpis["average_realized_price_eur_per_mwh"] == 0.0
    assert all(math.isfinite(value) for value in kpis.values() if isinstance(value, float))
