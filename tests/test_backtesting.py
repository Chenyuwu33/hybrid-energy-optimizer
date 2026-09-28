import pandas as pd
import pytest

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import run_daily_backtest


def _two_day_inputs() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=48, freq="h")
    prices = []
    for hour in range(48):
        local_hour = hour % 24
        if 0 <= local_hour < 6:
            prices.append(-10.0 if local_hour < 2 else 10.0)
        elif 17 <= local_hour < 21:
            prices.append(100.0)
        else:
            prices.append(40.0)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "wind_mwh": [50.0] * 48,
            "price_eur_mwh": prices,
        }
    )


def _battery() -> Battery:
    return Battery(
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


def test_daily_backtest_reports_sell_all_curtail_negative_and_optimized_baselines() -> None:
    result = run_daily_backtest(_two_day_inputs(), _battery(), solver="highs")

    assert len(result.daily) == 2
    assert result.summary["days"] == 2
    assert result.summary["hours"] == 48
    assert result.summary["baseline_curtail_negative_revenue_eur"] >= result.summary[
        "baseline_sell_all_revenue_eur"
    ]
    assert result.summary["optimized_revenue_eur"] >= result.summary[
        "baseline_curtail_negative_revenue_eur"
    ]
    assert result.summary["battery_incremental_vs_curtail_eur"] == pytest.approx(
        result.summary["optimized_revenue_eur"]
        - result.summary["baseline_curtail_negative_revenue_eur"]
    )


def test_daily_backtest_requires_complete_hourly_days() -> None:
    incomplete = _two_day_inputs().iloc[:-1].copy()

    with pytest.raises(ValueError, match="24 hourly records"):
        run_daily_backtest(incomplete, _battery(), solver="highs")


def test_daily_backtest_preserves_terminal_soc_each_day() -> None:
    result = run_daily_backtest(_two_day_inputs(), _battery(), solver="highs")

    assert result.daily["ending_soc_mwh"].tolist() == pytest.approx([50.0, 50.0])
