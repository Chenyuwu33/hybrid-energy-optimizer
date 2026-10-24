"""Deterministic wind-plus-battery dispatch optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from energy_hub.optimization.results import DispatchResult

if TYPE_CHECKING:
    from energy_hub.assets.battery import Battery
    from energy_hub.config import GridChargingConfig

# Tie-breaking cost (EUR/MWh) on battery throughput used only inside the solver. With lossless
# or zero-cost storage, charging and discharging in the same hour can be exactly as profitable
# as not cycling at all, which inflates reported throughput and cycle counts. A penalty this
# small never trades away real revenue; the reported objective is recomputed without it.
_THROUGHPUT_TIE_BREAK_EUR_PER_MWH = 1e-4

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
    "battery_charge_from_wind_mwh",
    "grid_import_mwh",
]


@dataclass(frozen=True)
class _GridImport:
    """Resolved grid-charging settings for one solve (disabled when ``allowed`` is False)."""

    allowed: bool = False
    limit_mw: float | None = None
    fee_eur_per_mwh: float = 0.0


def optimize_dispatch(
    inputs: pd.DataFrame,
    battery: Battery,
    solver: str = "highs",
    grid_export_limit_mw: float | None = None,
    grid_charging: GridChargingConfig | None = None,
) -> DispatchResult:
    """Optimize hourly dispatch using HiGHS by default or optional Gurobi.

    ``grid_export_limit_mw`` caps hourly grid export (wind to grid plus battery discharge) at
    the point of connection. ``None`` means an unconstrained connection. Wind above the limit
    must be stored or curtailed, which is where co-located storage typically earns most.

    ``grid_charging`` (when enabled) lets the battery also charge from the grid, paying the
    hourly market price plus an import fee, subject to an optional import limit. Wind and grid
    charging share the battery's charge power. Without it the battery charges from wind only.

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
    grid_import = _resolve_grid_import(grid_charging)

    if requested == "gurobi":
        try:
            return _solve_with_pyomo(inputs, battery, requested, limit, grid_import)
        except ImportError as exc:
            raise RuntimeError(
                "Requested solver 'gurobi' is unavailable: install Pyomo and gurobipy"
            ) from exc

    try:
        return _solve_with_pyomo(inputs, battery, requested, limit, grid_import)
    except (ImportError, RuntimeError):
        return _solve_with_scipy_highs(inputs, battery, limit, grid_import)


def validate_grid_export_limit(value: float | None) -> float | None:
    """Return a validated grid export limit in MW, or ``None`` for no limit."""
    if value is None:
        return None
    limit = float(value)
    if not np.isfinite(limit) or limit <= 0:
        raise ValueError("grid_export_limit_mw must be a positive number or omitted")
    return limit


def _resolve_grid_import(grid_charging: GridChargingConfig | None) -> _GridImport:
    if grid_charging is None or not grid_charging.enabled:
        return _GridImport()
    return _GridImport(
        allowed=True,
        limit_mw=grid_charging.import_limit_mw,
        fee_eur_per_mwh=float(grid_charging.import_fee_eur_per_mwh),
    )


def _solve_with_scipy_highs(
    inputs: pd.DataFrame,
    battery: Battery,
    grid_export_limit_mw: float | None = None,
    grid_import: _GridImport | None = None,
) -> DispatchResult:
    try:
        from scipy.optimize import linprog
    except ImportError as exc:
        raise RuntimeError(
            "Requested solver 'highs' is unavailable: install Pyomo/highspy or SciPy"
        ) from exc

    grid_import = grid_import or _GridImport()
    n = len(inputs)
    wind = inputs["wind_mwh"].to_numpy(dtype=float)
    price = inputs["price_eur_mwh"].to_numpy(dtype=float)

    # Variable blocks, each of length n.
    wg, cw, dis, cur, soc, gi = (slice(k * n, (k + 1) * n) for k in range(6))
    size = 6 * n

    cycling_cost = battery.cycling_cost_eur_per_mwh + _THROUGHPUT_TIE_BREAK_EUR_PER_MWH
    objective = np.zeros(size, dtype=float)  # linprog minimizes, so revenues are negative
    objective[wg] = -price
    objective[cw] = cycling_cost
    objective[dis] = -price + cycling_cost
    objective[gi] = price + grid_import.fee_eur_per_mwh + cycling_cost

    a_eq: list[np.ndarray] = []
    b_eq: list[float] = []
    for t in range(n):
        balance = np.zeros(size, dtype=float)
        balance[wg.start + t] = 1.0
        balance[cw.start + t] = 1.0
        balance[cur.start + t] = 1.0
        a_eq.append(balance)
        b_eq.append(float(wind[t]))

        transition = np.zeros(size, dtype=float)
        transition[soc.start + t] = 1.0
        transition[cw.start + t] = -battery.charge_efficiency
        transition[gi.start + t] = -battery.charge_efficiency
        transition[dis.start + t] = 1.0 / battery.discharge_efficiency
        if t == 0:
            b = battery.initial_soc_mwh
        else:
            transition[soc.start + t - 1] = -1.0
            b = 0.0
        a_eq.append(transition)
        b_eq.append(float(b))

    a_ub_rows: list[np.ndarray] = []
    b_ub: list[float] = []
    for t in range(n):
        # Hourly steps: MW limits equal the MWh allowed per step.
        if grid_import.allowed:
            charge_power = np.zeros(size, dtype=float)
            charge_power[cw.start + t] = 1.0
            charge_power[gi.start + t] = 1.0
            a_ub_rows.append(charge_power)
            b_ub.append(battery.charge_power_mw)
        if grid_export_limit_mw is not None:
            export = np.zeros(size, dtype=float)
            export[wg.start + t] = 1.0
            export[dis.start + t] = 1.0
            a_ub_rows.append(export)
            b_ub.append(grid_export_limit_mw)

    import_upper = (grid_import.limit_mw if grid_import.allowed else 0.0)
    bounds: list[tuple[float | None, float | None]] = []
    bounds.extend([(0.0, None)] * n)
    bounds.extend([(0.0, battery.charge_power_mw)] * n)
    bounds.extend([(0.0, battery.discharge_power_mw)] * n)
    bounds.extend([(0.0, None)] * n)
    bounds.extend([(battery.min_soc_mwh, battery.max_soc_mwh)] * n)
    bounds.extend([(0.0, import_upper)] * n)
    if battery.terminal_soc_mwh is not None:
        bounds[soc.start + n - 1] = (battery.terminal_soc_mwh, battery.terminal_soc_mwh)

    solved = linprog(
        objective,
        A_ub=np.vstack(a_ub_rows) if a_ub_rows else None,
        b_ub=np.asarray(b_ub) if b_ub else None,
        A_eq=np.vstack(a_eq),
        b_eq=np.asarray(b_eq),
        bounds=bounds,
        method="highs",
    )
    if not solved.success or solved.x is None:
        raise RuntimeError(f"Requested solver 'highs' failed: {solved.message}")

    x = solved.x
    return _build_result(
        inputs,
        battery,
        grid_import,
        wind_to_grid=x[wg],
        charge_from_wind=x[cw],
        discharge=x[dis],
        curtailment=x[cur],
        soc=x[soc],
        grid_charge=x[gi],
        solver_status="optimal",
    )


def _solve_with_pyomo(
    inputs: pd.DataFrame,
    battery: Battery,
    solver: str,
    grid_export_limit_mw: float | None = None,
    grid_import: _GridImport | None = None,
) -> DispatchResult:
    try:
        import pyomo.environ as pyo
        from pyomo.opt import SolverStatus, TerminationCondition
    except ImportError as exc:
        raise ImportError("Pyomo is not installed") from exc

    solver_factory = pyo.SolverFactory(solver)
    if solver_factory is None or not solver_factory.available(exception_flag=False):
        raise RuntimeError(f"Requested solver '{solver}' is unavailable")

    grid_import = grid_import or _GridImport()
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
    import_upper = grid_import.limit_mw if grid_import.allowed else 0.0
    model.grid_charge = pyo.Var(model.T, domain=pyo.NonNegativeReals, bounds=(0.0, import_upper))

    def wind_balance(m: object, t: int) -> object:
        return m.wind_to_grid[t] + m.charge[t] + m.curtailment[t] == wind[t]

    model.wind_balance = pyo.Constraint(model.T, rule=wind_balance)

    def soc_transition(m: object, t: int) -> object:
        previous = battery.initial_soc_mwh if t == 0 else m.soc[t - 1]
        return m.soc[t] == (
            previous
            + battery.charge_efficiency * (m.charge[t] + m.grid_charge[t])
            - m.discharge[t] / battery.discharge_efficiency
        )

    model.soc_transition = pyo.Constraint(model.T, rule=soc_transition)

    if grid_import.allowed:

        def charge_power(m: object, t: int) -> object:
            return m.charge[t] + m.grid_charge[t] <= battery.charge_power_mw

        model.charge_power = pyo.Constraint(model.T, rule=charge_power)

    if grid_export_limit_mw is not None:

        def grid_export_limit(m: object, t: int) -> object:
            return m.wind_to_grid[t] + m.discharge[t] <= grid_export_limit_mw

        model.grid_export_limit = pyo.Constraint(model.T, rule=grid_export_limit)
    if battery.terminal_soc_mwh is not None:
        model.terminal_soc = pyo.Constraint(
            expr=model.soc[n - 1] == battery.terminal_soc_mwh
        )

    cycling_cost = battery.cycling_cost_eur_per_mwh + _THROUGHPUT_TIE_BREAK_EUR_PER_MWH
    model.objective = pyo.Objective(
        expr=sum(
            price[t] * (model.wind_to_grid[t] + model.discharge[t])
            - (price[t] + grid_import.fee_eur_per_mwh) * model.grid_charge[t]
            - cycling_cost * (model.charge[t] + model.grid_charge[t] + model.discharge[t])
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

    def values(var: object) -> list[float]:
        return [pyo.value(var[t]) for t in range(n)]

    return _build_result(
        inputs,
        battery,
        grid_import,
        wind_to_grid=values(model.wind_to_grid),
        charge_from_wind=values(model.charge),
        discharge=values(model.discharge),
        curtailment=values(model.curtailment),
        soc=values(model.soc),
        grid_charge=values(model.grid_charge),
        solver_status=("optimal" if termination == TerminationCondition.optimal else "feasible"),
    )


def _build_result(
    inputs: pd.DataFrame,
    battery: Battery,
    grid_import: _GridImport,
    *,
    wind_to_grid: object,
    charge_from_wind: object,
    discharge: object,
    curtailment: object,
    soc: object,
    grid_charge: object,
    solver_status: str,
) -> DispatchResult:
    wind = inputs["wind_mwh"].to_numpy(dtype=float)
    price = inputs["price_eur_mwh"].to_numpy(dtype=float)
    to_grid = _clean(wind_to_grid)
    from_wind = _clean(charge_from_wind)
    discharging = _clean(discharge)
    imported = _clean(grid_charge)
    export = to_grid + discharging
    charging = from_wind + imported

    dispatch = pd.DataFrame(
        {
            "timestamp": inputs["timestamp"].to_numpy(),
            "wind_available_mwh": wind,
            "price_eur_mwh": price,
            "wind_to_grid_mwh": to_grid,
            "battery_charge_mwh": charging,
            "battery_discharge_mwh": discharging,
            "grid_export_mwh": export,
            "curtailment_mwh": _clean(curtailment),
            "soc_mwh": _clean(soc),
            "battery_charge_from_wind_mwh": from_wind,
            "grid_import_mwh": imported,
        },
        columns=_COLUMNS,
    )
    throughput = float(charging.sum() + discharging.sum())
    # Market revenue net of import, throughput and degradation cost; the solver tie-break
    # is excluded.
    objective = float(
        np.dot(price, export)
        - np.dot(price + grid_import.fee_eur_per_mwh, imported)
        - battery.cycling_cost_eur_per_mwh * throughput
    )
    return DispatchResult(dispatch=dispatch, objective_eur=objective, solver_status=solver_status)


def _clean(values: object) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    array[np.abs(array) < 1e-9] = 0.0
    return array
