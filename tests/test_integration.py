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
