import json
import math
from pathlib import Path

import yaml

from energy_hub.cli import main
from energy_hub.config import load_config
from energy_hub.run import run_case

REQUIRED_DISPATCH_COLUMNS = {
    "timestamp",
    "wind_available_mwh",
    "price_eur_mwh",
    "wind_to_grid_mwh",
    "battery_charge_mwh",
    "battery_discharge_mwh",
    "grid_export_mwh",
    "curtailment_mwh",
    "soc_mwh",
}


def test_run_case_solves_sample_without_modifying_inputs() -> None:
    sample = Path("data/sample/sample_24h.csv")
    config_file = Path("configs/base.yaml")
    sample_before = sample.read_bytes()
    config_before = config_file.read_bytes()

    result = run_case(load_config(config_file))

    assert len(result.dispatch) == 24
    assert REQUIRED_DISPATCH_COLUMNS.issubset(result.dispatch.columns)
    for value in result.kpis.values():
        if isinstance(value, float):
            assert math.isfinite(value)
    assert result.kpis["optimized_revenue_eur"] >= result.kpis["baseline_revenue_eur"]
    assert sample.read_bytes() == sample_before
    assert config_file.read_bytes() == config_before


def test_cli_writes_dispatch_and_kpis(tmp_path: Path, capsys) -> None:
    config_raw = yaml.safe_load(Path("configs/base.yaml").read_text(encoding="utf-8"))
    config_raw["input_csv"] = str(Path("data/sample/sample_24h.csv").resolve())
    config_raw["output_dir"] = str(tmp_path / "outputs")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_raw), encoding="utf-8")

    exit_code = main(["run", "--config", str(config_path), "--solver", "highs"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Baseline revenue" in captured.out
    assert "Optimized revenue" in captured.out
    assert (tmp_path / "outputs" / "dispatch.csv").exists()
    kpi_path = tmp_path / "outputs" / "kpis.json"
    assert kpi_path.exists()
    payload = json.loads(kpi_path.read_text(encoding="utf-8"))
    assert payload["solver_status"] == "optimal"


def test_core_imports_do_not_load_streamlit() -> None:
    import importlib
    import sys

    sys.modules.pop("streamlit", None)
    importlib.import_module("energy_hub.run")
    importlib.import_module("energy_hub.optimization.dispatch")
    importlib.import_module("energy_hub.economics.metrics")
    assert "streamlit" not in sys.modules


def test_cli_grid_limit_override_constrains_export_and_reports_limit(
    tmp_path: Path, capsys
) -> None:
    config_raw = yaml.safe_load(Path("configs/base.yaml").read_text(encoding="utf-8"))
    config_raw["input_csv"] = str(Path("data/sample/sample_24h.csv").resolve())
    config_raw["output_dir"] = str(tmp_path / "outputs")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_raw), encoding="utf-8")

    exit_code = main(
        ["run", "--config", str(config_path), "--solver", "highs", "--grid-limit-mw", "50"]
    )

    assert exit_code == 0
    assert "Grid export limit:  50 MW" in capsys.readouterr().out
    payload = json.loads((tmp_path / "outputs" / "kpis.json").read_text(encoding="utf-8"))
    assert payload["grid_export_limit_mw"] == 50.0
    assert payload["optimized_revenue_eur"] >= payload["baseline_curtail_negative_revenue_eur"]
    dispatch = (tmp_path / "outputs" / "dispatch.csv").read_text(encoding="utf-8")
    from io import StringIO

    import pandas as pd

    assert pd.read_csv(StringIO(dispatch))["grid_export_mwh"].max() <= 50.0 + 1e-6


def test_cli_rejects_nonpositive_grid_limit(tmp_path: Path, capsys) -> None:
    exit_code = main(["run", "--config", "configs/base.yaml", "--grid-limit-mw", "0"])

    assert exit_code == 1
    assert "--grid-limit-mw must be positive" in capsys.readouterr().err


def test_cli_size_sweeps_sample_and_writes_ranked_outputs(tmp_path: Path, capsys) -> None:
    import pandas as pd

    exit_code = main(
        [
            "size",
            "--config",
            "configs/base.yaml",
            "--powers",
            "10,25",
            "--durations",
            "1,2",
            "--grid-limit-mw",
            "50",
            "--output-dir",
            str(tmp_path),
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Battery sizing sweep" in out
    assert "fewer than 28 days" in out
    table = pd.read_csv(tmp_path / "sizing.csv")
    assert len(table) == 4
    summary = json.loads((tmp_path / "sizing_summary.json").read_text(encoding="utf-8"))
    assert summary["days"] == 1
    assert summary["grid_export_limit_mw"] == 50.0
    assert summary["assumptions"]["lifetime_years"] == 15


def test_cli_size_requires_complete_historical_arguments(capsys) -> None:
    exit_code = main(
        [
            "size",
            "--config",
            "configs/base.yaml",
            "--powers",
            "10",
            "--durations",
            "1",
            "--start",
            "2026-01-01",
        ]
    )

    assert exit_code == 1
    assert "--start, --end and --wind-share together" in capsys.readouterr().err


def test_cli_grid_charging_flags_override_config(tmp_path: Path, capsys) -> None:
    config_raw = yaml.safe_load(Path("configs/base.yaml").read_text(encoding="utf-8"))
    config_raw["input_csv"] = str(Path("data/sample/sample_24h.csv").resolve())
    config_raw["grid_charging"]["enabled"] = True
    config_path = tmp_path / "config.yaml"

    def run(*extra: str) -> dict:
        config_raw["output_dir"] = str(tmp_path / "out")
        config_path.write_text(yaml.safe_dump(config_raw), encoding="utf-8")
        assert main(["run", "--config", str(config_path), *extra]) == 0
        return json.loads((tmp_path / "out" / "kpis.json").read_text(encoding="utf-8"))

    on = run("--import-fee", "0")
    assert "Grid charging:      on (import fee €0/MWh, limit unlimited)" in capsys.readouterr().out
    assert on["total_grid_import_mwh"] > 0

    off = run("--no-grid-charging")
    assert "Grid charging" not in capsys.readouterr().out
    assert off["total_grid_import_mwh"] == 0.0
    assert on["optimized_revenue_eur"] >= off["optimized_revenue_eur"]

    limited = run("--import-fee", "0", "--import-limit-mw", "2")
    capsys.readouterr()
    assert 0 < limited["total_grid_import_mwh"] <= 2.0 * 24 + 1e-6


def test_cli_grid_charging_and_no_grid_charging_are_mutually_exclusive(capsys) -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["run", "--config", "configs/base.yaml", "--grid-charging", "--no-grid-charging"])
    assert "not allowed with argument" in capsys.readouterr().err


def test_cli_size_records_grid_charging_in_summary(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "size",
            "--config",
            "configs/base.yaml",
            "--powers",
            "10",
            "--durations",
            "2",
            "--grid-charging",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert "Grid charging:" in capsys.readouterr().out
    summary = json.loads((tmp_path / "sizing_summary.json").read_text(encoding="utf-8"))
    assert summary["grid_charging_enabled"] is True


def test_cli_degradation_flags(tmp_path: Path, capsys) -> None:
    config_raw = yaml.safe_load(Path("configs/base.yaml").read_text(encoding="utf-8"))
    config_raw["input_csv"] = str(Path("data/sample/sample_24h.csv").resolve())
    config_raw["output_dir"] = str(tmp_path / "out")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_raw), encoding="utf-8")
    kpi_path = tmp_path / "out" / "kpis.json"

    assert main(["run", "--config", str(config_path)]) == 0
    out = capsys.readouterr().out
    assert "Degradation:        on (€5.00/MWh throughput, cycle life 7,500)" in out
    worn = json.loads(kpi_path.read_text(encoding="utf-8"))

    assert main(["run", "--config", str(config_path), "--no-degradation"]) == 0
    assert "Degradation" not in capsys.readouterr().out
    fresh = json.loads(kpi_path.read_text(encoding="utf-8"))

    assert worn["degradation_cost_eur"] > 0
    assert fresh["degradation_cost_eur"] == 0.0
    assert worn["battery_incremental_value_eur"] < fresh["battery_incremental_value_eur"]

    assert main(["run", "--config", str(config_path), "--cycle-life", "3750"]) == 0
    assert "€10.00/MWh throughput" in capsys.readouterr().out


def test_cli_size_shows_cycle_life_years(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "size",
                "--config",
                "configs/base.yaml",
                "--powers",
                "10",
                "--durations",
                "2",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "Life (yr)" in capsys.readouterr().out
    summary = json.loads((tmp_path / "sizing_summary.json").read_text(encoding="utf-8"))
    assert summary["degradation"]["cycle_life_full_cycles"] == 7500.0
