"""Battery energy-storage parameters."""

from __future__ import annotations

from dataclasses import dataclass, replace

from energy_hub.config import BatteryConfig, DegradationConfig


@dataclass(frozen=True)
class Battery:
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
    degradation_cost_eur_per_mwh: float = 0.0

    def __post_init__(self) -> None:
        if self.energy_capacity_mwh <= 0:
            raise ValueError("energy_capacity_mwh must be positive")
        if self.charge_power_mw <= 0:
            raise ValueError("charge_power_mw must be positive")
        if self.discharge_power_mw <= 0:
            raise ValueError("discharge_power_mw must be positive")
        if not 0 < self.charge_efficiency <= 1:
            raise ValueError("charge_efficiency must be in (0, 1]")
        if not 0 < self.discharge_efficiency <= 1:
            raise ValueError("discharge_efficiency must be in (0, 1]")
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
        if self.degradation_cost_eur_per_mwh < 0:
            raise ValueError("degradation_cost_eur_per_mwh must be non-negative")

    @property
    def cycling_cost_eur_per_mwh(self) -> float:
        """Total cost per MWh charged or discharged: generic throughput plus degradation."""
        return self.throughput_cost_eur_per_mwh + self.degradation_cost_eur_per_mwh

    def with_degradation(self, degradation: DegradationConfig | None) -> Battery:
        """Return a copy priced with ``degradation`` (no degradation cost if None/disabled)."""
        cost = 0.0 if degradation is None else degradation.cost_eur_per_mwh_throughput
        return replace(self, degradation_cost_eur_per_mwh=cost)

    @classmethod
    def from_config(
        cls, config: BatteryConfig, degradation: DegradationConfig | None = None
    ) -> Battery:
        """Create an immutable asset model from validated project configuration."""
        cost = 0.0 if degradation is None else degradation.cost_eur_per_mwh_throughput
        return cls(
            energy_capacity_mwh=config.energy_capacity_mwh,
            charge_power_mw=config.charge_power_mw,
            discharge_power_mw=config.discharge_power_mw,
            charge_efficiency=config.charge_efficiency,
            discharge_efficiency=config.discharge_efficiency,
            min_soc_mwh=config.min_soc_mwh,
            max_soc_mwh=config.max_soc_mwh,
            initial_soc_mwh=config.initial_soc_mwh,
            terminal_soc_mwh=config.terminal_soc_mwh,
            throughput_cost_eur_per_mwh=config.throughput_cost_eur_per_mwh,
            degradation_cost_eur_per_mwh=cost,
        )
