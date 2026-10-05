import pandas as pd
from dashboard.components.charts import (
    daily_battery_value_figure,
    daily_cycles_figure,
    daily_revenue_figure,
    historical_wind_price_figure,
    sample_dispatch_figure,
    sample_input_figure,
    sample_soc_figure,
)


def _dispatch() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
            "wind_available_mwh": [50.0, 60.0],
            "price_eur_mwh": [20.0, 100.0],
            "wind_to_grid_mwh": [25.0, 60.0],
            "battery_charge_mwh": [25.0, 0.0],
            "battery_discharge_mwh": [0.0, 20.0],
            "curtailment_mwh": [0.0, 0.0],
            "soc_mwh": [73.75, 52.7],
        }
    )


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-09-01", "2026-09-02"],
            "baseline_sell_all_revenue_eur": [1000.0, 1100.0],
            "baseline_curtail_negative_revenue_eur": [1010.0, 1100.0],
            "optimized_revenue_eur": [1200.0, 1300.0],
            "battery_incremental_vs_curtail_eur": [190.0, 200.0],
            "equivalent_full_cycles": [1.2, 1.5],
        }
    )


def test_sample_chart_helpers_preserve_existing_trace_content() -> None:
    dispatch = _dispatch()

    assert [trace.name for trace in sample_input_figure(dispatch).data] == [
        "Wind available (MWh)",
        "Price (EUR/MWh)",
    ]
    assert [trace.name for trace in sample_dispatch_figure(dispatch).data] == [
        "Wind to grid",
        "Battery charge",
        "Battery discharge",
        "Curtailment",
    ]
    assert [trace.name for trace in sample_soc_figure(dispatch).data] == ["Battery SOC"]


def test_historical_chart_helpers_expose_wind_price_value_revenue_and_cycles() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-09-01", periods=2, freq="h"),
            "wind_mwh": [25.0, 50.0],
            "price_eur_mwh": [20.0, 100.0],
        }
    )
    daily = _daily()

    assert len(historical_wind_price_figure(inputs).data) == 2
    assert [trace.name for trace in daily_battery_value_figure(daily).data] == [
        "Battery incremental value"
    ]
    assert [trace.name for trace in daily_revenue_figure(daily).data] == [
        "Sell-all",
        "Curtail negative",
        "Optimized",
    ]
    assert [trace.name for trace in daily_cycles_figure(daily).data] == [
        "Equivalent full cycles"
    ]
