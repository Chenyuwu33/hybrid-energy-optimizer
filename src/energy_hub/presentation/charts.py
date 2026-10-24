"""Pure Plotly chart builders shared by interactive front ends."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def sample_input_figure(dispatch: pd.DataFrame) -> go.Figure:
    """Build the v0.1 wind-availability and price chart."""
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["wind_available_mwh"],
            name="Wind available (MWh)",
            yaxis="y1",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["price_eur_mwh"],
            name="Price (EUR/MWh)",
            yaxis="y2",
        )
    )
    figure.update_layout(
        title="Wind availability and electricity price",
        yaxis={"title": "Wind (MWh)"},
        yaxis2={"title": "Price (EUR/MWh)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h"},
    )
    return figure


def _add_grid_limit_line(figure: go.Figure, grid_export_limit_mw: float | None) -> None:
    if grid_export_limit_mw is None:
        return
    figure.add_hline(
        y=float(grid_export_limit_mw),
        line_dash="dash",
        annotation_text=f"Grid export limit {grid_export_limit_mw:g} MW",
        annotation_position="top left",
    )


def sample_dispatch_figure(
    dispatch: pd.DataFrame, grid_export_limit_mw: float | None = None
) -> go.Figure:
    """Build the v0.1 optimized hourly-dispatch chart."""
    figure = go.Figure()
    for column, name in [
        ("wind_to_grid_mwh", "Wind to grid"),
        ("battery_charge_mwh", "Battery charge"),
        ("battery_discharge_mwh", "Battery discharge"),
        ("curtailment_mwh", "Curtailment"),
    ]:
        figure.add_trace(go.Bar(x=dispatch["timestamp"], y=dispatch[column], name=name))
    figure.update_layout(
        barmode="group",
        title="Optimized hourly dispatch",
        yaxis_title="Energy (MWh)",
    )
    _add_grid_limit_line(figure, grid_export_limit_mw)
    return figure


def sample_soc_figure(dispatch: pd.DataFrame) -> go.Figure:
    """Build the v0.1 battery state-of-charge chart."""
    figure = go.Figure(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["soc_mwh"],
            name="Battery SOC",
            mode="lines+markers",
        )
    )
    figure.update_layout(title="Battery state of charge", yaxis_title="SOC (MWh)")
    return figure


def historical_wind_price_figure(
    inputs: pd.DataFrame, grid_export_limit_mw: float | None = None
) -> go.Figure:
    """Plot hypothetical wind-farm production beside historical DK1 prices."""
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=inputs["timestamp"],
            y=inputs["wind_mwh"],
            name="Hypothetical wind (MWh)",
            yaxis="y1",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=inputs["timestamp"],
            y=inputs["price_eur_mwh"],
            name="DK1 price (EUR/MWh)",
            yaxis="y2",
        )
    )
    figure.update_layout(
        title="Historical wind profile and DK1 electricity price",
        yaxis={"title": "Wind energy (MWh/h)"},
        yaxis2={"title": "Price (EUR/MWh)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h"},
    )
    _add_grid_limit_line(figure, grid_export_limit_mw)
    return figure


def daily_battery_value_figure(daily: pd.DataFrame) -> go.Figure:
    """Plot daily incremental battery value versus the curtail-negative baseline."""
    figure = go.Figure(
        go.Bar(
            x=daily["date"],
            y=daily["battery_incremental_vs_curtail_eur"],
            name="Battery incremental value",
        )
    )
    figure.update_layout(
        title="Daily battery incremental value",
        xaxis_title="Date",
        yaxis_title="EUR",
    )
    return figure


def daily_revenue_figure(daily: pd.DataFrame) -> go.Figure:
    """Compare the three daily revenue strategies."""
    figure = go.Figure()
    for column, name in [
        ("baseline_sell_all_revenue_eur", "Sell-all"),
        ("baseline_curtail_negative_revenue_eur", "Curtail negative"),
        ("optimized_revenue_eur", "Optimized"),
    ]:
        figure.add_trace(go.Bar(x=daily["date"], y=daily[column], name=name))
    figure.update_layout(
        barmode="group",
        title="Daily revenue comparison",
        xaxis_title="Date",
        yaxis_title="EUR",
    )
    return figure


def daily_cycles_figure(daily: pd.DataFrame) -> go.Figure:
    """Plot daily equivalent full cycles."""
    figure = go.Figure(
        go.Bar(
            x=daily["date"],
            y=daily["equivalent_full_cycles"],
            name="Equivalent full cycles",
        )
    )
    figure.update_layout(
        title="Daily battery cycling",
        xaxis_title="Date",
        yaxis_title="Equivalent full cycles",
    )
    return figure
