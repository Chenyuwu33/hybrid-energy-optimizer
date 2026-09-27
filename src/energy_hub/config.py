"""Configuration models and YAML loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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
class ProjectConfig:
    input_csv: Path
    output_dir: Path
    solver: str
    battery: BatteryConfig


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

    try:
        battery = BatteryConfig(**battery_raw)
        return ProjectConfig(
            input_csv=Path(root["input_csv"]),
            output_dir=Path(root.get("output_dir", "outputs")),
            solver=str(root.get("solver", "highs")),
            battery=battery,
        )
    except KeyError as exc:
        raise ValueError(f"Missing configuration key: {exc.args[0]}") from exc
    except TypeError as exc:
        raise ValueError(f"Invalid battery configuration: {exc}") from exc
