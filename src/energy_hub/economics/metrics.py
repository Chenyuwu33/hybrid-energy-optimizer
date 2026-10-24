"""Baseline and optimized economic KPI calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from energy_hub.assets.battery import Battery
    from energy_hub.optimization.results import DispatchResult


def _exportable_wind(inputs: pd.DataFrame, grid_export_limit_mw: float | None) -> pd.Series:
    """Wind that a battery-less asset can physically export through its grid connection."""
    if grid_export_limit_mw is None:
        return inputs["wind_mwh"]
    return inputs["wind_mwh"].clip(upper=float(grid_export_limit_mw))


def calculate_baseline_revenue(
    inputs: pd.DataFrame, grid_export_limit_mw: float | None = None
) -> float:
    """Revenue when all available wind is exported directly to the grid.

    With a grid export limit, wind above the limit is curtailed because no battery exists.
    """
    exported = _exportable_wind(inputs, grid_export_limit_mw)
    return float((exported * inputs["price_eur_mwh"]).sum())


def calculate_curtail_negative_revenue(
    inputs: pd.DataFrame, grid_export_limit_mw: float | None = None
) -> float:
    """Revenue for a wind-only asset that curtails whenever the price is negative.

    This baseline needs no battery, so the gap between it and the optimized revenue is the
    value actually created by the battery rather than by simply avoiding negative prices.
    Wind above any grid export limit is curtailed as well.
    """
    exported = _exportable_wind(inputs, grid_export_limit_mw)
    nonnegative_price = inputs["price_eur_mwh"].clip(lower=0.0)
    return float((exported * nonnegative_price).sum())


def calculate_kpis(
    inputs: pd.DataFrame,
    result: DispatchResult,
    battery: Battery,
    grid_export_limit_mw: float | None = None,
    grid_import_fee_eur_per_mwh: float = 0.0,
    cycle_life_full_cycles: float | None = None,
) -> dict[str, float | str]:
    """Calculate operational and economic KPIs for one optimized dispatch.

    Pass the same ``grid_export_limit_mw`` used for optimization so the baselines face the
    same connection constraint and the battery's value is not overstated. When the battery
    charged from the grid, imports are paid at the market price plus
    ``grid_import_fee_eur_per_mwh`` and deducted from the optimized revenue. Battery
    degradation cost (``battery.degradation_cost_eur_per_mwh``) is deducted like the generic
    throughput cost; pass ``cycle_life_full_cycles`` to also report the share of cycle life used.
    """
    dispatch = result.dispatch
    baseline = calculate_baseline_revenue(inputs, grid_export_limit_mw)
    curtail_negative = calculate_curtail_negative_revenue(inputs, grid_export_limit_mw)
    gross_market_revenue = float(
        (dispatch["price_eur_mwh"] * dispatch["grid_export_mwh"]).sum()
    )
    if "grid_import_mwh" in dispatch.columns:
        grid_import = dispatch["grid_import_mwh"]
    else:
        grid_import = pd.Series(0.0, index=dispatch.index)
    import_cost = float(
        ((dispatch["price_eur_mwh"] + float(grid_import_fee_eur_per_mwh)) * grid_import).sum()
    )
    throughput = float(
        dispatch["battery_charge_mwh"].sum() + dispatch["battery_discharge_mwh"].sum()
    )
    degradation_cost = battery.degradation_cost_eur_per_mwh * throughput
    optimized = (
        gross_market_revenue
        - import_cost
        - battery.throughput_cost_eur_per_mwh * throughput
        - degradation_cost
    )
    uplift = optimized - baseline
    uplift_pct = 0.0 if abs(baseline) < 1e-12 else uplift / baseline * 100.0

    total_export = float(dispatch["grid_export_mwh"].sum())
    realized_price = 0.0 if total_export <= 1e-12 else gross_market_revenue / total_export
    cycles = throughput / (2.0 * battery.energy_capacity_mwh)

    kpis: dict[str, float | str] = {
        "baseline_revenue_eur": float(baseline),
        "optimized_revenue_eur": float(optimized),
        "revenue_uplift_eur": float(uplift),
        "revenue_uplift_pct": float(uplift_pct),
        "baseline_curtail_negative_revenue_eur": float(curtail_negative),
        "battery_incremental_value_eur": float(optimized - curtail_negative),
        "total_wind_mwh": float(dispatch["wind_available_mwh"].sum()),
        "total_grid_export_mwh": total_export,
        "total_battery_charge_mwh": float(dispatch["battery_charge_mwh"].sum()),
        "total_battery_discharge_mwh": float(dispatch["battery_discharge_mwh"].sum()),
        "total_curtailment_mwh": float(dispatch["curtailment_mwh"].sum()),
        "total_grid_import_mwh": float(grid_import.sum()),
        "grid_import_cost_eur": import_cost,
        "degradation_cost_eur": float(degradation_cost),
        "average_realized_price_eur_per_mwh": float(realized_price),
        "equivalent_full_cycles": float(cycles),
        "min_soc_mwh": float(dispatch["soc_mwh"].min()),
        "max_soc_mwh": float(dispatch["soc_mwh"].max()),
        "solver_status": result.solver_status,
    }
    if cycle_life_full_cycles is not None:
        kpis["cycle_life_consumed_pct"] = float(cycles / cycle_life_full_cycles * 100.0)
    if grid_export_limit_mw is not None:
        limit = float(grid_export_limit_mw)
        kpis["grid_export_limit_mw"] = limit
        kpis["grid_limit_binding_hours"] = float(
            (dispatch["grid_export_mwh"] >= limit - 1e-6).sum()
        )
        kpis["wind_above_grid_limit_mwh"] = float(
            (dispatch["wind_available_mwh"] - limit).clip(lower=0.0).sum()
        )
    return kpis
