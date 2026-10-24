"""Configuration models and YAML loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from energy_hub.economics.investment import InvestmentAssumptions


@dataclass(frozen=True)
class BatteryConfig:
    energy_capacity_mwh: float
    charge_power_mw: float
    discharge_power_mw: float
    charge_efficiency: float
    discharge_efficiency: float
    min_soc_mwh: float
    max_soc_mwh: float
    initial_soc_mwh: float
    terminal_soc_mwh: float | None
    throughput_cost_eur_per_mwh: float

    def __post_init__(self) -> None:
        if self.energy_capacity_mwh <= 0:
            raise ValueError("energy_capacity_mwh must be positive")
        if self.charge_power_mw <= 0:
            raise ValueError("charge_power_mw must be positive")
        if self.discharge_power_mw <= 0:
            raise ValueError("discharge_power_mw must be positive")
        for name, value in (
            ("charge_efficiency", self.charge_efficiency),
            ("discharge_efficiency", self.discharge_efficiency),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.min_soc_mwh < 0:
            raise ValueError("min_soc_mwh must be non-negative")
        if self.max_soc_mwh > self.energy_capacity_mwh:
            raise ValueError("max_soc_mwh cannot exceed energy_capacity_mwh")
        if self.min_soc_mwh > self.max_soc_mwh:
            raise ValueError("min_soc_mwh cannot exceed max_soc_mwh")
        if not self.min_soc_mwh <= self.initial_soc_mwh <= self.max_soc_mwh:
            raise ValueError("initial_soc_mwh must be within SOC bounds")
        if self.terminal_soc_mwh is not None and not (
            self.min_soc_mwh <= self.terminal_soc_mwh <= self.max_soc_mwh
        ):
            raise ValueError("terminal_soc_mwh must be within SOC bounds")
        if self.throughput_cost_eur_per_mwh < 0:
            raise ValueError("throughput_cost_eur_per_mwh must be non-negative")


@dataclass(frozen=True)
class GridChargingConfig:
    """Whether and how the battery may buy electricity from the grid to charge.

    Disabled by default: many wind support schemes forbid co-located storage from importing,
    and import costs (tariffs, levies) erode arbitrage value. ``import_fee_eur_per_mwh`` is
    added to the market price for every MWh imported; ``import_limit_mw`` caps hourly import
    at the connection point (``None`` = unconstrained).
    """

    enabled: bool = False
    import_limit_mw: float | None = None
    import_fee_eur_per_mwh: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("grid_charging.enabled must be true or false")
        if self.import_limit_mw is not None and not self.import_limit_mw > 0:
            raise ValueError("grid_charging.import_limit_mw must be positive or omitted")
        if not self.import_fee_eur_per_mwh >= 0:
            raise ValueError("grid_charging.import_fee_eur_per_mwh must be non-negative")


def soc_percent_bounds(base: BatteryConfig) -> tuple[float, float]:
    """Return the allowed SOC range in percent implied by a battery's SOC bounds."""
    return (
        base.min_soc_mwh / base.energy_capacity_mwh * 100.0,
        base.max_soc_mwh / base.energy_capacity_mwh * 100.0,
    )


def resize_battery_config(
    base: BatteryConfig,
    *,
    energy_capacity_mwh: float,
    charge_power_mw: float,
    discharge_power_mw: float,
    initial_soc_pct: float,
    terminal_soc_pct: float,
) -> BatteryConfig:
    """Resize a battery while preserving the base efficiencies, cost and SOC-bound fractions.

    Initial and terminal SOC are given as percentages of the new energy capacity and must lie
    inside the base battery's operating SOC range, so that resizing never produces an
    infeasible SOC configuration.
    """
    min_pct, max_pct = soc_percent_bounds(base)
    for name, value in (
        ("Initial SOC", initial_soc_pct),
        ("Terminal SOC", terminal_soc_pct),
    ):
        if not min_pct - 1e-9 <= value <= max_pct + 1e-9:
            raise ValueError(
                f"{name} must be between {min_pct:g}% and {max_pct:g}% "
                "(the battery's configured operating SOC range)"
            )

    energy = float(energy_capacity_mwh)
    if energy <= 0:
        raise ValueError("energy_capacity_mwh must be positive")
    min_soc = min_pct / 100.0 * energy
    max_soc = min(max_pct / 100.0 * energy, energy)

    def to_mwh(pct: float) -> float:
        # Clamp away floating-point noise at the boundaries already validated above.
        return min(max(pct / 100.0 * energy, min_soc), max_soc)

    return BatteryConfig(
        energy_capacity_mwh=energy,
        charge_power_mw=float(charge_power_mw),
        discharge_power_mw=float(discharge_power_mw),
        charge_efficiency=base.charge_efficiency,
        discharge_efficiency=base.discharge_efficiency,
        min_soc_mwh=min_soc,
        max_soc_mwh=max_soc,
        initial_soc_mwh=to_mwh(initial_soc_pct),
        terminal_soc_mwh=to_mwh(terminal_soc_pct),
        throughput_cost_eur_per_mwh=base.throughput_cost_eur_per_mwh,
    )


@dataclass(frozen=True)
class ProjectConfig:
    input_csv: Path
    output_dir: Path
    solver: str
    battery: BatteryConfig
    grid_export_limit_mw: float | None = None
    investment: InvestmentAssumptions = InvestmentAssumptions()
    grid_charging: GridChargingConfig = GridChargingConfig()

    def __post_init__(self) -> None:
        if self.grid_export_limit_mw is not None and not self.grid_export_limit_mw > 0:
            raise ValueError("grid_export_limit_mw must be positive or omitted")


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_config(path: str | Path) -> ProjectConfig:
    """Load and validate a project configuration from YAML."""
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in configuration: {config_path}") from exc

    root = _require_mapping(raw, "configuration")
    battery_raw = _require_mapping(root.get("battery"), "battery")

    raw_limit = root.get("grid_export_limit_mw")
    try:
        grid_export_limit_mw = None if raw_limit is None else float(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("grid_export_limit_mw must be a number or null") from exc

    investment_raw = root.get("investment") or {}
    investment_raw = _require_mapping(investment_raw, "investment")
    try:
        investment = InvestmentAssumptions(**investment_raw)
    except TypeError as exc:
        raise ValueError(f"Invalid investment configuration: {exc}") from exc

    grid_charging_raw = _require_mapping(root.get("grid_charging") or {}, "grid_charging")
    try:
        grid_charging = GridChargingConfig(**grid_charging_raw)
    except TypeError as exc:
        raise ValueError(f"Invalid grid_charging configuration: {exc}") from exc

    try:
        battery = BatteryConfig(**battery_raw)
        return ProjectConfig(
            input_csv=Path(root["input_csv"]),
            output_dir=Path(root.get("output_dir", "outputs")),
            solver=str(root.get("solver", "highs")),
            battery=battery,
            grid_export_limit_mw=grid_export_limit_mw,
            investment=investment,
            grid_charging=grid_charging,
        )
    except KeyError as exc:
        raise ValueError(f"Missing configuration key: {exc.args[0]}") from exc
    except TypeError as exc:
        raise ValueError(f"Invalid battery configuration: {exc}") from exc
