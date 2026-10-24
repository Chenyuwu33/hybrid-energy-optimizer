from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_app_loads_sample_and_historical_tabs_without_exception() -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"

    app = AppTest.from_file(app_path, default_timeout=10).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Sample Dispatch",
        "Historical DK1 Backtest",
        "BESS Sizing",
    ]


def test_dashboard_app_runs_from_any_working_directory(tmp_path, monkeypatch) -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(app_path, default_timeout=10).run()

    assert not app.exception
    # Submitting the sample form reads the sample CSV through the repo-relative path.
    app.button[0].click().run()
    assert not app.exception
    assert not app.error


def test_sample_tab_applies_grid_export_limit() -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    app = AppTest.from_file(app_path, default_timeout=20).run()

    grid_inputs = [w for w in app.number_input if w.label == "Grid export limit (MW)"]
    assert len(grid_inputs) == 3  # one per tab
    grid_inputs[0].set_value(50.0)
    app.button[0].click().run()

    assert not app.exception
    assert not app.error
    assert any("Grid export limit 50 MW was binding" in c.value for c in app.caption)


def test_sizing_tab_runs_on_sample_data() -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    app = AppTest.from_file(app_path, default_timeout=60).run()

    app.radio[0].set_value("Synthetic 24-hour sample")
    app.text_input[0].set_value("10, 25")
    app.text_input[1].set_value("1, 2")
    sizing_button = [b for b in app.button if b.label == "Run sizing sweep"][0]
    sizing_button.click().run()

    assert not app.exception
    assert not app.error or "positive NPV" in app.error[0].value
    assert len(app.dataframe) >= 1


def test_sample_tab_grid_charging_toggle_reports_imports() -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    app = AppTest.from_file(app_path, default_timeout=20).run()

    app.checkbox(key="sample_grid_charging").check()
    app.number_input(key="sample_import_fee").set_value(0.0)
    app.button[0].click().run()

    assert not app.exception
    assert not app.error
    assert any("Grid charging:" in c.value for c in app.caption)
