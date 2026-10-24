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


def test_resize_battery_config_scales_soc_bounds_with_capacity() -> None:
    from energy_hub.config import resize_battery_config, soc_percent_bounds

    base = load_config("configs/base.yaml").battery
    assert soc_percent_bounds(base) == pytest.approx((10.0, 100.0))

    # Smaller than the base minimum SOC in MWh: must stay feasible.
    resized = resize_battery_config(
        base,
        energy_capacity_mwh=8.0,
        charge_power_mw=4.0,
        discharge_power_mw=4.0,
        initial_soc_pct=50.0,
        terminal_soc_pct=10.0,
    )

    assert resized.min_soc_mwh == pytest.approx(0.8)
    assert resized.max_soc_mwh == pytest.approx(8.0)
    assert resized.initial_soc_mwh == pytest.approx(4.0)
    assert resized.terminal_soc_mwh == pytest.approx(0.8)
    assert resized.charge_efficiency == base.charge_efficiency


def test_resize_battery_config_reports_soc_outside_operating_range_in_percent() -> None:
    from energy_hub.config import resize_battery_config

    base = load_config("configs/base.yaml").battery

    with pytest.raises(ValueError, match=r"Initial SOC must be between 10% and 100%"):
        resize_battery_config(
            base,
            energy_capacity_mwh=100.0,
            charge_power_mw=25.0,
            discharge_power_mw=25.0,
            initial_soc_pct=5.0,
            terminal_soc_pct=50.0,
        )


def test_base_config_has_no_grid_export_limit_by_default() -> None:
    assert load_config("configs/base.yaml").grid_export_limit_mw is None


def test_grid_export_limit_is_loaded_and_validated(tmp_path: Path) -> None:
    base_text = Path("configs/base.yaml").read_text(encoding="utf-8")

    valid = tmp_path / "valid.yaml"
    valid.write_text(
        base_text.replace("grid_export_limit_mw: null", "grid_export_limit_mw: 60"),
        encoding="utf-8",
    )
    assert load_config(valid).grid_export_limit_mw == pytest.approx(60.0)

    for bad_value in ("0", "-10", "fast"):
        invalid = tmp_path / f"invalid_{bad_value}.yaml"
        invalid.write_text(
            base_text.replace(
                "grid_export_limit_mw: null", f"grid_export_limit_mw: {bad_value}"
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="grid_export_limit_mw"):
            load_config(invalid)


def test_investment_assumptions_load_from_yaml_with_defaults(tmp_path: Path) -> None:
    from energy_hub.economics.investment import InvestmentAssumptions

    base = load_config("configs/base.yaml")
    assert base.investment.energy_capex_eur_per_mwh == pytest.approx(100_000.0)
    assert base.investment.lifetime_years == 15

    text = Path("configs/base.yaml").read_text(encoding="utf-8")
    no_section = tmp_path / "no_investment.yaml"
    no_section.write_text(text.split("# Investment assumptions")[0], encoding="utf-8")
    assert load_config(no_section).investment == InvestmentAssumptions()

    bad = tmp_path / "bad_investment.yaml"
    bad.write_text(text.replace("discount_rate: 0.08", "discount_rate: 3"), encoding="utf-8")
    with pytest.raises(ValueError, match="discount_rate"):
        load_config(bad)

    unknown = tmp_path / "unknown_investment.yaml"
    unknown.write_text(text + "  capex_typo: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid investment configuration"):
        load_config(unknown)


def test_grid_charging_section_loads_and_validates(tmp_path: Path) -> None:
    from energy_hub.config import GridChargingConfig

    base = load_config("configs/base.yaml")
    assert base.grid_charging == GridChargingConfig(
        enabled=False, import_limit_mw=None, import_fee_eur_per_mwh=10.0
    )

    text = Path("configs/base.yaml").read_text(encoding="utf-8")
    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        text.replace("  enabled: false", "  enabled: true").replace(
            "  import_limit_mw: null", "  import_limit_mw: 40"
        ),
        encoding="utf-8",
    )
    loaded = load_config(enabled).grid_charging
    assert loaded.enabled is True
    assert loaded.import_limit_mw == pytest.approx(40.0)

    for old, new, match in [
        ("  enabled: false", "  enabled: maybe", "enabled"),
        ("import_fee_eur_per_mwh: 10.0", "import_fee_eur_per_mwh: -1", "import_fee"),
        ("  import_limit_mw: null", "  import_limit_mw: 0", "import_limit"),
        ("  enabled: false", "  enabled: false\n  typo: 1", "Invalid grid_charging"),
    ]:
        bad = tmp_path / "bad.yaml"
        bad.write_text(text.replace(old, new), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            load_config(bad)
