import pytest

from energy_hub.assets.battery import Battery
from energy_hub.config import BatteryConfig, load_config


def test_battery_from_config_exposes_parameters() -> None:
    config = load_config("configs/base.yaml")
    battery = Battery.from_config(config.battery)
    assert battery.energy_capacity_mwh == pytest.approx(100.0)
    assert battery.charge_power_mw == pytest.approx(25.0)
    assert battery.discharge_power_mw == pytest.approx(25.0)
    assert battery.charge_efficiency == pytest.approx(0.95)
    assert battery.discharge_efficiency == pytest.approx(0.95)
    assert battery.min_soc_mwh == pytest.approx(10.0)
    assert battery.max_soc_mwh == pytest.approx(100.0)
    assert battery.initial_soc_mwh == pytest.approx(50.0)
    assert battery.terminal_soc_mwh == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("energy_capacity_mwh", 0.0),
        ("charge_power_mw", -1.0),
        ("discharge_power_mw", 0.0),
        ("charge_efficiency", 0.0),
        ("discharge_efficiency", 1.2),
        ("min_soc_mwh", 110.0),
        ("max_soc_mwh", 120.0),
        ("initial_soc_mwh", 105.0),
        ("terminal_soc_mwh", 105.0),
    ],
)
def test_invalid_battery_parameters_raise(field: str, value: float) -> None:
    values = dict(
        energy_capacity_mwh=100.0,
        charge_power_mw=25.0,
        discharge_power_mw=25.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_mwh=10.0,
        max_soc_mwh=100.0,
        initial_soc_mwh=50.0,
        terminal_soc_mwh=50.0,
        throughput_cost_eur_per_mwh=0.0,
    )
    values[field] = value
    with pytest.raises(ValueError):
        Battery(**values)


def test_battery_config_is_supported_by_from_config() -> None:
    config = BatteryConfig(
        energy_capacity_mwh=40.0,
        charge_power_mw=10.0,
        discharge_power_mw=10.0,
        charge_efficiency=0.9,
        discharge_efficiency=0.9,
        min_soc_mwh=0.0,
        max_soc_mwh=40.0,
        initial_soc_mwh=10.0,
        terminal_soc_mwh=None,
        throughput_cost_eur_per_mwh=1.0,
    )
    assert Battery.from_config(config).terminal_soc_mwh is None


def test_battery_carries_degradation_cost_separately_from_throughput_cost() -> None:
    from energy_hub.config import DegradationConfig, load_config

    base = load_config("configs/base.yaml")
    degradation = DegradationConfig(enabled=True)

    battery = Battery.from_config(base.battery, degradation)

    assert battery.degradation_cost_eur_per_mwh == pytest.approx(5.0)
    assert battery.cycling_cost_eur_per_mwh == pytest.approx(
        base.battery.throughput_cost_eur_per_mwh + 5.0
    )
    assert Battery.from_config(base.battery).degradation_cost_eur_per_mwh == 0.0
    assert battery.with_degradation(None).degradation_cost_eur_per_mwh == 0.0
    assert battery.with_degradation(DegradationConfig(enabled=False)).cycling_cost_eur_per_mwh == (
        pytest.approx(base.battery.throughput_cost_eur_per_mwh)
    )
