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


def test_kpis_separate_battery_value_from_negative_price_curtailment() -> None:
    from energy_hub.economics.metrics import calculate_curtail_negative_revenue

    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_mwh": [10.0, 10.0],
            "price_eur_mwh": [-20.0, 50.0],
        }
    )
    # No battery activity: optimal play is to curtail the negative-price hour.
    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"],
            "wind_available_mwh": [10.0, 10.0],
            "price_eur_mwh": [-20.0, 50.0],
            "wind_to_grid_mwh": [0.0, 10.0],
            "battery_charge_mwh": [0.0, 0.0],
            "battery_discharge_mwh": [0.0, 0.0],
            "grid_export_mwh": [0.0, 10.0],
            "curtailment_mwh": [10.0, 0.0],
            "soc_mwh": [0.0, 0.0],
        }
    )
    result = DispatchResult(dispatch=dispatch, objective_eur=500.0, solver_status="optimal")

    kpis = calculate_kpis(inputs, result, _battery())

    assert calculate_curtail_negative_revenue(inputs) == pytest.approx(500.0)
    assert kpis["revenue_uplift_eur"] == pytest.approx(200.0)
    assert kpis["baseline_curtail_negative_revenue_eur"] == pytest.approx(500.0)
    assert kpis["battery_incremental_value_eur"] == pytest.approx(0.0)


def test_baselines_and_kpis_respect_grid_export_limit() -> None:
    from energy_hub.economics.metrics import calculate_curtail_negative_revenue

    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_mwh": [30.0, 10.0],
            "price_eur_mwh": [-10.0, 50.0],
        }
    )

    assert calculate_baseline_revenue(inputs, grid_export_limit_mw=20.0) == pytest.approx(
        20.0 * -10.0 + 10.0 * 50.0
    )
    assert calculate_curtail_negative_revenue(
        inputs, grid_export_limit_mw=20.0
    ) == pytest.approx(500.0)

    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"],
            "wind_available_mwh": [30.0, 10.0],
            "price_eur_mwh": [-10.0, 50.0],
            "wind_to_grid_mwh": [0.0, 10.0],
            "battery_charge_mwh": [10.0, 0.0],
            "battery_discharge_mwh": [0.0, 10.0],
            "grid_export_mwh": [0.0, 20.0],
            "curtailment_mwh": [20.0, 0.0],
            "soc_mwh": [10.0, 0.0],
        }
    )
    result = DispatchResult(dispatch=dispatch, objective_eur=1000.0, solver_status="optimal")

    kpis = calculate_kpis(inputs, result, _battery(), grid_export_limit_mw=20.0)

    assert kpis["grid_export_limit_mw"] == pytest.approx(20.0)
    assert kpis["grid_limit_binding_hours"] == pytest.approx(1.0)
    assert kpis["wind_above_grid_limit_mwh"] == pytest.approx(10.0)
    assert kpis["battery_incremental_value_eur"] == pytest.approx(1000.0 - 500.0)


def test_kpis_omit_grid_limit_keys_without_a_limit() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=1, freq="h"),
            "wind_mwh": [10.0],
            "price_eur_mwh": [50.0],
        }
    )
    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"],
            "wind_available_mwh": [10.0],
            "price_eur_mwh": [50.0],
            "wind_to_grid_mwh": [10.0],
            "battery_charge_mwh": [0.0],
            "battery_discharge_mwh": [0.0],
            "grid_export_mwh": [10.0],
            "curtailment_mwh": [0.0],
            "soc_mwh": [0.0],
        }
    )
    result = DispatchResult(dispatch=dispatch, objective_eur=500.0, solver_status="optimal")

    kpis = calculate_kpis(inputs, result, _battery())

    assert "grid_export_limit_mw" not in kpis
