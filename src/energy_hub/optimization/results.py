"""Typed optimization result containers."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DispatchResult:
    dispatch: pd.DataFrame
    objective_eur: float
    solver_status: str
