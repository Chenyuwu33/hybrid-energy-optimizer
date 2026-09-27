"""Baseline and optimized economic KPI calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from energy_hub.assets.battery import Battery
    from energy_hub.optimization.results import DispatchResult


def calculate_baseline_revenue(inputs: pd.DataFrame) -> float:
    """Revenue when all available wind is exported directly to the grid."""
    return float((inputs["wind_mwh"] * inputs["price_eur_mwh"]).sum())


def calculate_kpis(
    inputs: pd.DataFrame,
    result: DispatchResult,
    battery: Battery,
) -> dict[str, float | str]:
    """Calculate operational and economic KPIs for one optimized dispatch."""
    dispatch = result.dispatch
    baseline = calculate_baseline_revenue(inputs)
    gross_market_revenue = float(
        (dispatch["price_eur_mwh"] * dispatch["grid_export_mwh"]).sum()
    )
    throughput = float(
        dispatch["battery_charge_mwh"].sum() + dispatch["battery_discharge_mwh"].sum()
    )
    optimized = gross_market_revenue - battery.throughput_cost_eur_per_mwh * throughput
    uplift = optimized - baseline
    uplift_pct = 0.0 if abs(baseline) < 1e-12 else uplift / baseline * 100.0

    total_export = float(dispatch["grid_export_mwh"].sum())
    realized_price = 0.0 if total_export <= 1e-12 else gross_market_revenue / total_export
    cycles = throughput / (2.0 * battery.energy_capacity_mwh)

    return {
        "baseline_revenue_eur": float(baseline),
        "optimized_revenue_eur": float(optimized),
        "revenue_uplift_eur": float(uplift),
        "revenue_uplift_pct": float(uplift_pct),
        "total_wind_mwh": float(dispatch["wind_available_mwh"].sum()),
        "total_grid_export_mwh": total_export,
        "total_battery_charge_mwh": float(dispatch["battery_charge_mwh"].sum()),
        "total_battery_discharge_mwh": float(dispatch["battery_discharge_mwh"].sum()),
        "total_curtailment_mwh": float(dispatch["curtailment_mwh"].sum()),
        "average_realized_price_eur_per_mwh": float(realized_price),
        "equivalent_full_cycles": float(cycles),
        "min_soc_mwh": float(dispatch["soc_mwh"].min()),
        "max_soc_mwh": float(dispatch["soc_mwh"].max()),
        "solver_status": result.solver_status,
    }
