"""Application service for capacity-based historical wind-plus-battery backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import BacktestResult, run_daily_backtest
from energy_hub.config import BatteryConfig
from energy_hub.data.energinet import EnerginetClient


class HistoricalDataClient(Protocol):
    """Minimal data-client interface required by the historical backtest service."""

    def fetch_hourly_inputs_for_capacity(
        self,
        start: date,
        end: date,
        price_area: str,
        wind_capacity_mw: float,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class HistoricalBacktestRequest:
    """User-facing assumptions for one historical DK1 scenario."""

    start: date
    end: date
    area: str
    wind_capacity_mw: float
    battery_energy_mwh: float
    charge_power_mw: float
    discharge_power_mw: float
    initial_soc_pct: float
    terminal_soc_pct: float
    solver: str = "highs"

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        if self.area != "DK1":
            raise ValueError("historical capacity-based backtests currently support DK1 only")
        if self.wind_capacity_mw <= 0:
            raise ValueError("wind_capacity_mw must be positive")
        if self.battery_energy_mwh <= 0:
            raise ValueError("battery_energy_mwh must be positive")
        if self.charge_power_mw <= 0:
            raise ValueError("charge_power_mw must be positive")
        if self.discharge_power_mw <= 0:
            raise ValueError("discharge_power_mw must be positive")
        for name, value in (
            ("initial SOC", self.initial_soc_pct),
            ("terminal SOC", self.terminal_soc_pct),
        ):
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} percentage must be between 0 and 100")
        if self.solver not in {"highs", "gurobi"}:
            raise ValueError("solver must be 'highs' or 'gurobi'")


@dataclass(frozen=True)
class HistoricalBacktestBundle:
    """Normalized hourly inputs plus the shared daily backtest result."""

    inputs: pd.DataFrame
    result: BacktestResult


def build_battery_from_request(
    base: BatteryConfig,
    request: HistoricalBacktestRequest,
) -> Battery:
    """Build a BESS scenario while preserving base efficiency and SOC-bound fractions."""
    min_fraction = base.min_soc_mwh / base.energy_capacity_mwh
    max_fraction = base.max_soc_mwh / base.energy_capacity_mwh
    energy = float(request.battery_energy_mwh)

    return Battery(
        energy_capacity_mwh=energy,
        charge_power_mw=float(request.charge_power_mw),
        discharge_power_mw=float(request.discharge_power_mw),
        charge_efficiency=base.charge_efficiency,
        discharge_efficiency=base.discharge_efficiency,
        min_soc_mwh=min_fraction * energy,
        max_soc_mwh=max_fraction * energy,
        initial_soc_mwh=request.initial_soc_pct / 100.0 * energy,
        terminal_soc_mwh=request.terminal_soc_pct / 100.0 * energy,
        throughput_cost_eur_per_mwh=base.throughput_cost_eur_per_mwh,
    )


def run_historical_backtest(
    request: HistoricalBacktestRequest,
    base_battery: BatteryConfig,
    *,
    client: HistoricalDataClient | None = None,
) -> HistoricalBacktestBundle:
    """Fetch normalized historical inputs and reuse the shared daily backtest runner."""
    data_client = client or EnerginetClient()
    battery = build_battery_from_request(base_battery, request)
    inputs = data_client.fetch_hourly_inputs_for_capacity(
        start=request.start,
        end=request.end,
        price_area=request.area,
        wind_capacity_mw=request.wind_capacity_mw,
    )
    result = run_daily_backtest(inputs, battery, solver=request.solver)
    return HistoricalBacktestBundle(inputs=inputs, result=result)
