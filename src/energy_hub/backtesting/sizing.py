"""Battery sizing sweep: backtest a grid of power/duration options and appraise each one."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import run_daily_backtest
from energy_hub.config import (
    BatteryConfig,
    DegradationConfig,
    GridChargingConfig,
    resize_battery_config,
    soc_percent_bounds,
)
from energy_hub.economics.investment import InvestmentAssumptions, evaluate_battery_investment

DAYS_PER_YEAR = 365.0
MAX_SWEEP_CASES = 60

SIZING_COLUMNS = [
    "power_mw",
    "duration_h",
    "energy_mwh",
    "period_battery_value_eur",
    "annual_battery_value_eur",
    "annual_equivalent_full_cycles",
    "annual_degradation_cost_eur",
    "cycle_life_years",
    "capex_eur",
    "annual_fixed_om_eur",
    "npv_eur",
    "irr",
    "simple_payback_years",
]


@dataclass(frozen=True)
class SizingResult:
    """One row per candidate size plus the shared context of the sweep."""

    table: pd.DataFrame
    days: int
    annualization_factor: float
    assumptions: InvestmentAssumptions
    grid_export_limit_mw: float | None
    grid_charging_enabled: bool = False
    degradation: DegradationConfig | None = None

    @property
    def best(self) -> pd.Series | None:
        """The size with the highest NPV, or ``None`` if every candidate destroys value."""
        if self.table.empty:
            return None
        row = self.table.loc[self.table["npv_eur"].idxmax()]
        return row if row["npv_eur"] > 0 else None


def parse_number_list(text: str, name: str) -> list[float]:
    """Parse "10, 25,50" into sorted unique positive floats (CLI and dashboard input)."""
    try:
        values = [float(part) for part in text.replace(";", ",").split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated list of numbers") from exc
    return _clean_options(values, name)


def _clean_options(values: Iterable[float], name: str) -> list[float]:
    cleaned = sorted({float(value) for value in values})
    if not cleaned:
        raise ValueError(f"{name} must contain at least one value")
    if cleaned[0] <= 0:
        raise ValueError(f"{name} must contain only positive values")
    return cleaned


def run_sizing_sweep(
    inputs: pd.DataFrame,
    base_battery: BatteryConfig,
    power_mw_options: Sequence[float],
    duration_h_options: Sequence[float],
    assumptions: InvestmentAssumptions | None = None,
    *,
    solver: str = "highs",
    grid_export_limit_mw: float | None = None,
    grid_charging: GridChargingConfig | None = None,
    degradation: DegradationConfig | None = None,
    initial_soc_pct: float | None = None,
    terminal_soc_pct: float | None = None,
    max_cases: int = MAX_SWEEP_CASES,
) -> SizingResult:
    """Backtest every power x duration combination on the same hourly inputs.

    Each candidate keeps the base battery's efficiencies, throughput cost and SOC-bound
    fractions; charge and discharge power are both set to ``power_mw``. The battery's value is
    its incremental revenue over the battery-less curtail-negative baseline (which faces the
    same grid limit), scaled from the backtest period to a year. That first-year value feeds a
    discounted cash-flow appraisal per size.

    With ``degradation`` enabled, each candidate pays the per-MWh cycling cost inside the
    optimizer, so its value is already net of cell wear (a sinking fund for replacement), and
    ``cycle_life_years`` reports how long its cycle life would last at the backtested pace.

    The backtest is a perfect-foresight benchmark, so values are an optimistic upper bound,
    and a short or unrepresentative period scales poorly to a full year.
    """
    assumptions = assumptions or InvestmentAssumptions()
    powers = _clean_options(power_mw_options, "power options")
    durations = _clean_options(duration_h_options, "duration options")
    if len(powers) * len(durations) > max_cases:
        raise ValueError(
            f"sizing sweep is limited to {max_cases} cases; "
            f"got {len(powers)} powers x {len(durations)} durations"
        )

    min_pct, max_pct = soc_percent_bounds(base_battery)

    def base_pct(mwh: float) -> float:
        pct = mwh / base_battery.energy_capacity_mwh * 100.0
        return min(max(pct, min_pct), max_pct)

    # Unspecified SOC targets inherit the base battery's (as % of capacity); explicit values
    # are validated against the operating range by resize_battery_config.
    initial = base_pct(base_battery.initial_soc_mwh) if initial_soc_pct is None else initial_soc_pct
    terminal_mwh = base_battery.terminal_soc_mwh
    if terminal_soc_pct is not None:
        terminal = terminal_soc_pct
    elif terminal_mwh is not None:
        terminal = base_pct(terminal_mwh)
    else:
        terminal = initial

    rows: list[dict[str, float | None]] = []
    days = 0
    for power in powers:
        for duration in durations:
            energy = power * duration
            battery = Battery.from_config(
                resize_battery_config(
                    base_battery,
                    energy_capacity_mwh=energy,
                    charge_power_mw=power,
                    discharge_power_mw=power,
                    initial_soc_pct=initial,
                    terminal_soc_pct=terminal,
                ),
                degradation,
            )
            backtest = run_daily_backtest(
                inputs,
                battery,
                solver=solver,
                grid_export_limit_mw=grid_export_limit_mw,
                grid_charging=grid_charging,
            )
            days = int(backtest.summary["days"])
            factor = DAYS_PER_YEAR / days
            period_value = float(backtest.summary["battery_incremental_vs_curtail_eur"])
            annual_value = period_value * factor
            appraisal = evaluate_battery_investment(energy, power, annual_value, assumptions)
            annual_cycles = float(backtest.summary["equivalent_full_cycles"]) * factor
            degradation_on = degradation is not None and degradation.enabled
            # NaN (not None) keeps the column numeric when no candidate has a cycle life.
            cycle_life_years = (
                degradation.cycle_life_full_cycles / annual_cycles
                if degradation_on and annual_cycles > 1e-9
                else float("nan")
            )
            rows.append(
                {
                    "power_mw": power,
                    "duration_h": duration,
                    "energy_mwh": energy,
                    "period_battery_value_eur": period_value,
                    "annual_battery_value_eur": annual_value,
                    "annual_equivalent_full_cycles": annual_cycles,
                    "annual_degradation_cost_eur": float(
                        backtest.summary["degradation_cost_eur"]
                    )
                    * factor,
                    "cycle_life_years": cycle_life_years,
                    "capex_eur": appraisal.capex_eur,
                    "annual_fixed_om_eur": appraisal.annual_fixed_om_eur,
                    "npv_eur": appraisal.npv_eur,
                    "irr": appraisal.irr,
                    "simple_payback_years": appraisal.simple_payback_years,
                }
            )

    table = pd.DataFrame(rows, columns=SIZING_COLUMNS)
    return SizingResult(
        table=table,
        days=days,
        annualization_factor=DAYS_PER_YEAR / days,
        assumptions=assumptions,
        grid_export_limit_mw=grid_export_limit_mw,
        grid_charging_enabled=bool(grid_charging and grid_charging.enabled),
        degradation=degradation if degradation is not None and degradation.enabled else None,
    )
