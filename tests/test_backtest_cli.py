from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import energy_hub.cli as cli


def _historical_inputs() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=48, freq="h")
    prices = [
        -10.0 if (hour % 24) < 2 else 100.0 if 17 <= (hour % 24) < 21 else 40.0
        for hour in range(48)
    ]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "wind_mwh": [50.0] * 48,
            "price_eur_mwh": prices,
        }
    )


class FakeEnerginetClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float]] = []

    def fetch_hourly_inputs(self, start, end, price_area: str, wind_share: float) -> pd.DataFrame:
        self.calls.append((start.isoformat(), end.isoformat(), price_area, wind_share))
        return _historical_inputs()


def test_backtest_command_fetches_real_data_shape_and_writes_outputs(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    fake = FakeEnerginetClient()
    monkeypatch.setattr(cli, "EnerginetClient", lambda: fake, raising=False)

    exit_code = cli.main(
        [
            "backtest",
            "--config",
            "configs/base.yaml",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
            "--area",
            "DK1",
            "--wind-share",
            "0.05",
            "--solver",
            "highs",
            "--output-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake.calls == [("2026-01-01", "2026-01-03", "DK1", 0.05)]
    assert "Historical backtest" in captured.out
    assert "Battery incremental value" in captured.out

    inputs_path = tmp_path / "backtest_inputs.csv"
    daily_path = tmp_path / "backtest_daily.csv"
    summary_path = tmp_path / "backtest_summary.json"
    assert inputs_path.exists()
    assert daily_path.exists()
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["days"] == 2
    assert summary["hours"] == 48
    assert summary["optimized_revenue_eur"] >= summary[
        "baseline_curtail_negative_revenue_eur"
    ]


def test_backtest_command_rejects_nonpositive_wind_share(tmp_path: Path, capsys) -> None:
    exit_code = cli.main(
        [
            "backtest",
            "--config",
            "configs/base.yaml",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
            "--area",
            "DK1",
            "--wind-share",
            "0",
            "--output-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "wind-share" in captured.err.lower()
