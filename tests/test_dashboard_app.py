from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_app_loads_sample_and_historical_tabs_without_exception() -> None:
    app_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"

    app = AppTest.from_file(app_path, default_timeout=10).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Sample Dispatch",
        "Historical DK1 Backtest",
    ]
