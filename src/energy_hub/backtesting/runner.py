"""Day-by-day historical replay for wind-plus-battery scenarios."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from energy_hub.assets.battery import Battery
from energy_hub.optimization.dispatch import optimize_dispatch


@dataclass(frozen=True)
class BacktestResult:
    """Daily results and aggregate summary for a historical replay."""

    daily: pd.DataFrame
    summary: dict[str, float | int]


def _validate_hourly_days(inputs: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "wind_mwh", "price_eur_mwh"}
    missing = required - set(inputs.columns)
    if missing:
        raise ValueError(f"backtest inputs missing required columns: {sorted(missing)}")
    if inputs.empty:
        raise ValueError("backtest inputs cannot be empty")

    clean = inputs[list(required)].copy()
    clean["timestamp"] = pd.to_datetime(clean["timestamp"], errors="raise")
    clean = clean.sort_values("timestamp").reset_index(drop=True)
    if clean["timestamp"].duplicated().any():
        raise ValueError("backtest inputs contain duplicate timestamps")

    clean["date"] = clean["timestamp"].dt.date
    counts = clean.groupby("date", sort=True).size()
    if (counts != 24).any():
        bad = ", ".join(str(day) for day in counts[counts != 24].index)
        raise ValueError(f"each backtest day must contain exactly 24 hourly records; check {bad}")
    return clean


def run_daily_backtest(
    inputs: pd.DataFrame,
    battery: Battery,
    solver: str = "highs",
) -> BacktestResult:
    """Replay complete UTC days using perfect-information day-ahead optimization.

    Every day starts from the configured initial SOC and, when a terminal SOC is configured,
    ends at that same configured target. This keeps daily comparisons independent and avoids
    giving one day free energy from the previous day.
    """
    clean = _validate_hourly_days(inputs)
    daily_rows: list[dict[str, float | str]] = []

    for day, group in clean.groupby("date", sort=True):
        hourly = group[["timestamp", "wind_mwh", "price_eur_mwh"]].reset_index(drop=True)
        dispatch_result = optimize_dispatch(hourly, battery, solver=solver)
        dispatch = dispatch_result.dispatch

        sell_all = float((hourly["wind_mwh"] * hourly["price_eur_mwh"]).sum())
        nonnegative_price = hourly["price_eur_mwh"].clip(lower=0.0)
        curtail_negative = float((hourly["wind_mwh"] * nonnegative_price).sum())
        throughput = float(
            dispatch["battery_charge_mwh"].sum() + dispatch["battery_discharge_mwh"].sum()
        )
        optimized = float(dispatch_result.objective_eur)
        daily_rows.append(
            {
                "date": str(day),
                "hours": 24,
                "wind_mwh": float(hourly["wind_mwh"].sum()),
                "baseline_sell_all_revenue_eur": sell_all,
                "baseline_curtail_negative_revenue_eur": curtail_negative,
                "optimized_revenue_eur": optimized,
                "battery_incremental_vs_curtail_eur": optimized - curtail_negative,
                "total_uplift_vs_sell_all_eur": optimized - sell_all,
                "equivalent_full_cycles": throughput / (2.0 * battery.energy_capacity_mwh),
                "ending_soc_mwh": float(dispatch["soc_mwh"].iloc[-1]),
            }
        )

    daily = pd.DataFrame(daily_rows)
    summary: dict[str, float | int] = {
        "days": int(len(daily)),
        "hours": int(daily["hours"].sum()),
        "wind_mwh": float(daily["wind_mwh"].sum()),
        "baseline_sell_all_revenue_eur": float(
            daily["baseline_sell_all_revenue_eur"].sum()
        ),
        "baseline_curtail_negative_revenue_eur": float(
            daily["baseline_curtail_negative_revenue_eur"].sum()
        ),
        "optimized_revenue_eur": float(daily["optimized_revenue_eur"].sum()),
        "battery_incremental_vs_curtail_eur": float(
            daily["battery_incremental_vs_curtail_eur"].sum()
        ),
        "total_uplift_vs_sell_all_eur": float(daily["total_uplift_vs_sell_all_eur"].sum()),
        "equivalent_full_cycles": float(daily["equivalent_full_cycles"].sum()),
    }
    return BacktestResult(daily=daily, summary=summary)
