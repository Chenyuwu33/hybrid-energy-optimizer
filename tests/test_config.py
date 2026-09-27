from pathlib import Path

import pytest

from energy_hub.config import BatteryConfig, load_config


def test_load_base_config() -> None:
    config = load_config("configs/base.yaml")

    assert config.solver == "highs"
    assert config.input_csv == Path("data/sample/sample_24h.csv")
    assert config.output_dir == Path("outputs")
    assert config.battery.energy_capacity_mwh == pytest.approx(100.0)
    assert config.battery.charge_power_mw == pytest.approx(25.0)
    assert config.battery.discharge_power_mw == pytest.approx(25.0)
    assert config.battery.charge_efficiency == pytest.approx(0.95)
    assert config.battery.discharge_efficiency == pytest.approx(0.95)
    assert config.battery.initial_soc_mwh == pytest.approx(50.0)
    assert config.battery.terminal_soc_mwh == pytest.approx(50.0)
    assert config.battery.throughput_cost_eur_per_mwh == pytest.approx(0.0)


def test_invalid_efficiency_raises_value_error() -> None:
    with pytest.raises(ValueError, match="charge_efficiency"):
        BatteryConfig(
            energy_capacity_mwh=100.0,
            charge_power_mw=25.0,
            discharge_power_mw=25.0,
            charge_efficiency=1.2,
            discharge_efficiency=0.95,
            min_soc_mwh=10.0,
            max_soc_mwh=100.0,
            initial_soc_mwh=50.0,
            terminal_soc_mwh=50.0,
            throughput_cost_eur_per_mwh=0.0,
        )
