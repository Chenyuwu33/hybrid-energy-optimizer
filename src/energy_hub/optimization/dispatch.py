"""Deterministic wind-plus-battery dispatch optimization."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from energy_hub.optimization.results import DispatchResult

if TYPE_CHECKING:
    from energy_hub.assets.battery import Battery

_COLUMNS = [
    "timestamp",
    "wind_available_mwh",
    "price_eur_mwh",
    "wind_to_grid_mwh",
    "battery_charge_mwh",
    "battery_discharge_mwh",
    "grid_export_mwh",
    "curtailment_mwh",
    "soc_mwh",
]


def optimize_dispatch(
    inputs: pd.DataFrame,
    battery: Battery,
    solver: str = "highs",
    grid_export_limit_mw: float | None = None,
) -> DispatchResult:
    """Optimize hourly dispatch using HiGHS by default or optional Gurobi.

    ``grid_export_limit_mw`` caps hourly grid export (wind to grid plus battery discharge) at
    the point of connection. ``None`` means an unconstrained connection. Wind above the limit
    must be stored or curtailed, which is where co-located storage typically earns most.

    When Pyomo is installed, the requested solver is used through Pyomo. For the
    open-source ``highs`` option, a SciPy/HiGHS compatibility backend is used when
    Pyomo/highspy is unavailable. This keeps the core model verifiable in minimal
    Python environments while preserving the public Pyomo solver path.
    """
    requested = solver.strip().lower()
    if requested not in {"highs", "gurobi"}:
        raise RuntimeError(f"Requested solver '{solver}' is not supported or unavailable")
    if inputs.empty:
        raise ValueError("cannot optimize an empty input horizon")
    limit = validate_grid_export_limit(grid_export_limit_mw)

    if requested == "gurobi":
        try:
            return _solve_with_pyomo(inputs, battery, requested, limit)
        except ImportError as exc:
            raise RuntimeError(
                "Requested solver 'gurobi' is unavailable: install Pyomo and gurobipy"
            ) from exc

    try:
        return _solve_with_pyomo(inputs, battery, requested, limit)
    except (ImportError, RuntimeError):
        return _solve_with_scipy_highs(inputs, battery, limit)


def validate_grid_export_limit(value: float | None) -> float | None:
    """Return a validated grid export limit in MW, or ``None`` for no limit."""
    if value is None:
        return None
    limit = float(value)
    if not np.isfinite(limit) or limit <= 0:
        raise ValueError("grid_export_limit_mw must be a positive number or omitted")
    return limit


def _solve_with_scipy_highs(
    inputs: pd.DataFrame, battery: Battery, grid_export_limit_mw: float | None = None
) -> DispatchResult:
    try:
        from scipy.optimize import linprog
    except ImportError as exc:
        raise RuntimeError(
            "Requested solver 'highs' is unavailable: install Pyomo/highspy or SciPy"
        ) from exc

    n = len(inputs)
    wind = inputs["wind_mwh"].to_numpy(dtype=float)
    price = inputs["price_eur_mwh"].to_numpy(dtype=float)

    wg = slice(0, n)
    charge = slice(n, 2 * n)
    discharge = slice(2 * n, 3 * n)
    curtail = slice(3 * n, 4 * n)
    soc = slice(4 * n, 5 * n)
    size = 5 * n

    objective = np.zeros(size, dtype=float)
    objective[wg] = -price
    objective[charge] = battery.throughput_cost_eur_per_mwh
    objective[discharge] = -price + battery.throughput_cost_eur_per_mwh

    a_eq: list[np.ndarray] = []
    b_eq: list[float] = []

    for t in range(n):
        balance = np.zeros(size, dtype=float)
        balance[t] = 1.0
        balance[n + t] = 1.0
        balance[3 * n + t] = 1.0
        a_eq.append(balance)
        b_eq.append(float(wind[t]))

        transition = np.zeros(size, dtype=float)
        transition[4 * n + t] = 1.0
        transition[n + t] = -battery.charge_efficiency
        transition[2 * n + t] = 1.0 / battery.discharge_efficiency
        if t == 0:
            b = battery.initial_soc_mwh
        else:
            transition[4 * n + t - 1] = -1.0
            b = 0.0
        a_eq.append(transition)
        b_eq.append(float(b))

    a_ub: np.ndarray | None = None
    b_ub: np.ndarray | None = None
    if grid_export_limit_mw is not None:
        # Hourly steps: MW limit equals the MWh that may be exported per step.
        a_ub = np.zeros((n, size), dtype=float)
        for t in range(n):
            a_ub[t, t] = 1.0
            a_ub[t, 2 * n + t] = 1.0
        b_ub = np.full(n, grid_export_limit_mw, dtype=float)

    bounds: list[tuple[float | None, float | None]] = []
    bounds.extend([(0.0, None)] * n)
    bounds.extend([(0.0, battery.charge_power_mw)] * n)
    bounds.extend([(0.0, battery.discharge_power_mw)] * n)
    bounds.extend([(0.0, None)] * n)
    bounds.extend([(battery.min_soc_mwh, battery.max_soc_mwh)] * n)
    if battery.terminal_soc_mwh is not None:
        bounds[4 * n + n - 1] = (battery.terminal_soc_mwh, battery.terminal_soc_mwh)

    solved = linprog(
        objective,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=np.vstack(a_eq),
        b_eq=np.asarray(b_eq),
        bounds=bounds,
        method="highs",
    )
    if not solved.success or solved.x is None:
        raise RuntimeError(f"Requested solver 'highs' failed: {solved.message}")

    x = solved.x
    wind_to_grid = _clean(x[wg])
    charging = _clean(x[charge])
    discharging = _clean(x[discharge])
    curtailment = _clean(x[curtail])
    soc_values = _clean(x[soc])
    grid_export = wind_to_grid + discharging

    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"].to_numpy(),
            "wind_available_mwh": wind,
            "price_eur_mwh": price,
            "wind_to_grid_mwh": wind_to_grid,
            "battery_charge_mwh": charging,
            "battery_discharge_mwh": discharging,
            "grid_export_mwh": grid_export,
            "curtailment_mwh": curtailment,
            "soc_mwh": soc_values,
        },
        columns=_COLUMNS,
    )
    return DispatchResult(
        dispatch=dispatch,
        objective_eur=float(-solved.fun),
        solver_status="optimal",
    )


def _solve_with_pyomo(
    inputs: pd.DataFrame,
    battery: Battery,
    solver: str,
    grid_export_limit_mw: float | None = None,
) -> DispatchResult:
    try:
        import pyomo.environ as pyo
        from pyomo.opt import SolverStatus, TerminationCondition
    except ImportError as exc:
        raise ImportError("Pyomo is not installed") from exc

    solver_factory = pyo.SolverFactory(solver)
    if solver_factory is None or not solver_factory.available(exception_flag=False):
        raise RuntimeError(f"Requested solver '{solver}' is unavailable")

    n = len(inputs)
    wind = inputs["wind_mwh"].to_numpy(dtype=float)
    price = inputs["price_eur_mwh"].to_numpy(dtype=float)

    model = pyo.ConcreteModel()
    model.T = pyo.RangeSet(0, n - 1)
    model.wind_to_grid = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.charge = pyo.Var(
        model.T, domain=pyo.NonNegativeReals, bounds=(0.0, battery.charge_power_mw)
    )
    model.discharge = pyo.Var(
        model.T, domain=pyo.NonNegativeReals, bounds=(0.0, battery.discharge_power_mw)
    )
    model.curtailment = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.soc = pyo.Var(
        model.T,
        domain=pyo.NonNegativeReals,
        bounds=(battery.min_soc_mwh, battery.max_soc_mwh),
    )

    def wind_balance(m: object, t: int) -> object:
        return m.wind_to_grid[t] + m.charge[t] + m.curtailment[t] == wind[t]

    model.wind_balance = pyo.Constraint(model.T, rule=wind_balance)

    def soc_transition(m: object, t: int) -> object:
        previous = battery.initial_soc_mwh if t == 0 else m.soc[t - 1]
        return m.soc[t] == (
            previous
            + battery.charge_efficiency * m.charge[t]
            - m.discharge[t] / battery.discharge_efficiency
        )

    model.soc_transition = pyo.Constraint(model.T, rule=soc_transition)

    if grid_export_limit_mw is not None:

        def grid_export_limit(m: object, t: int) -> object:
            return m.wind_to_grid[t] + m.discharge[t] <= grid_export_limit_mw

        model.grid_export_limit = pyo.Constraint(model.T, rule=grid_export_limit)
    if battery.terminal_soc_mwh is not None:
        model.terminal_soc = pyo.Constraint(
            expr=model.soc[n - 1] == battery.terminal_soc_mwh
        )

    model.objective = pyo.Objective(
        expr=sum(
            price[t] * (model.wind_to_grid[t] + model.discharge[t])
            - battery.throughput_cost_eur_per_mwh
            * (model.charge[t] + model.discharge[t])
            for t in range(n)
        ),
        sense=pyo.maximize,
    )

    solved = solver_factory.solve(model, tee=False)
    termination = solved.solver.termination_condition
    if solved.solver.status not in {SolverStatus.ok, SolverStatus.warning} or termination not in {
        TerminationCondition.optimal,
        TerminationCondition.feasible,
    }:
        raise RuntimeError(
            f"Requested solver '{solver}' failed with termination condition {termination}"
        )

    wind_to_grid = _clean([pyo.value(model.wind_to_grid[t]) for t in range(n)])
    charging = _clean([pyo.value(model.charge[t]) for t in range(n)])
    discharging = _clean([pyo.value(model.discharge[t]) for t in range(n)])
    curtailment = _clean([pyo.value(model.curtailment[t]) for t in range(n)])
    soc_values = _clean([pyo.value(model.soc[t]) for t in range(n)])
    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"].to_numpy(),
            "wind_available_mwh": wind,
            "price_eur_mwh": price,
            "wind_to_grid_mwh": wind_to_grid,
            "battery_charge_mwh": charging,
            "battery_discharge_mwh": discharging,
            "grid_export_mwh": wind_to_grid + discharging,
            "curtailment_mwh": curtailment,
            "soc_mwh": soc_values,
        },
        columns=_COLUMNS,
    )
    return DispatchResult(
        dispatch=dispatch,
        objective_eur=float(pyo.value(model.objective)),
        solver_status=("optimal" if termination == TerminationCondition.optimal else "feasible"),
    )


def _clean(values: object) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    array[np.abs(array) < 1e-9] = 0.0
    return array
