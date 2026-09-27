"""Wind-farm identity model for v0.1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WindFarm:
    name: str = "wind_farm"
