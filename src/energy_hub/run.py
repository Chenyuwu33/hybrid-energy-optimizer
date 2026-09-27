"""Application orchestration shared by CLI and dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from energy_hub.assets.battery import Battery
from energy_hub.config import ProjectConfig
from energy_hub.data.io import load_hourly_inputs
from energy_hub.economics.metrics import calculate_kpis
from energy_hub.optimization.dispatch import optimize_dispatch


@dataclass(frozen=True)
class RunResult:
    dispatch: pd.DataFrame
    kpis: dict[str, float | str]


def run_case(config: ProjectConfig, solver_override: str | None = None) -> RunResult:
    """Run one configured decision-support case without writing output files."""
    inputs = load_hourly_inputs(config.input_csv)
    battery = Battery.from_config(config.battery)
    result = optimize_dispatch(inputs, battery, solver=solver_override or config.solver)
    kpis = calculate_kpis(inputs, result, battery)
    return RunResult(dispatch=result.dispatch, kpis=kpis)
