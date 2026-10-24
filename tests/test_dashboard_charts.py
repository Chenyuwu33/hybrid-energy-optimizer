import pandas as pd

from energy_hub.presentation.charts import (
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


def test_dispatch_and_wind_charts_draw_grid_limit_only_when_set() -> None:
    inputs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-09-01", periods=2, freq="h"),
            "wind_mwh": [30.0, 80.0],
            "price_eur_mwh": [20.0, 100.0],
        }
    )

    assert len(sample_dispatch_figure(_dispatch()).layout.shapes) == 0
    limited = sample_dispatch_figure(_dispatch(), grid_export_limit_mw=55.0)
    assert [shape.y0 for shape in limited.layout.shapes] == [55.0]

    assert len(historical_wind_price_figure(inputs).layout.shapes) == 0
    limited_wind = historical_wind_price_figure(inputs, grid_export_limit_mw=55.0)
    assert [shape.y0 for shape in limited_wind.layout.shapes] == [55.0]


def test_sizing_charts_build_from_sweep_table() -> None:
    from energy_hub.presentation.charts import sizing_npv_heatmap, sizing_value_capex_figure

    table = pd.DataFrame(
        {
            "power_mw": [10.0, 10.0, 25.0, 25.0],
            "duration_h": [1.0, 2.0, 1.0, 2.0],
            "energy_mwh": [10.0, 20.0, 25.0, 50.0],
            "annual_battery_value_eur": [1e5, 2e5, 2e5, 3e5],
            "npv_eur": [-1e6, 5e5, -2e6, 1e6],
        }
    )

    heatmap = sizing_npv_heatmap(table)
    assert heatmap.data[0].z.shape == (2, 2)
    assert list(heatmap.data[0].y) == ["10 MW", "25 MW"]
    assert heatmap.data[0].zmid == 0.0
    assert len(sizing_value_capex_figure(table).data) == 2


def test_dispatch_chart_shows_grid_import_only_when_present() -> None:
    plain = _dispatch()
    names = [trace.name for trace in sample_dispatch_figure(plain).data]
    assert "Grid import" not in names

    with_import = plain.assign(grid_import_mwh=[5.0, 0.0])
    names = [trace.name for trace in sample_dispatch_figure(with_import).data]
    assert "Grid import" in names
