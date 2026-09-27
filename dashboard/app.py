"""Streamlit dashboard for the Hybrid Energy Optimizer v0.1 sample case."""

from dataclasses import replace

import plotly.graph_objects as go
import streamlit as st

from energy_hub.config import load_config
from energy_hub.run import run_case


st.set_page_config(page_title="Hybrid Energy Optimizer", layout="wide")
st.title("Hybrid Energy Optimizer")
st.caption("Wind + battery decision-support prototype")
st.markdown(
    """
This prototype answers a practical operating question: given hourly wind generation
and electricity prices, when should a wind asset sell power, charge a battery, or
discharge stored energy? The sample is synthetic and is not operational advice for
any specific asset.
"""
)

base = load_config("configs/base.yaml")
with st.sidebar:
    st.header("Battery assumptions")
    energy_capacity = st.number_input(
        "Energy capacity (MWh)", min_value=1.0, value=base.battery.energy_capacity_mwh
    )
    charge_power = st.number_input(
        "Charge power (MW)", min_value=0.1, value=base.battery.charge_power_mw
    )
    discharge_power = st.number_input(
        "Discharge power (MW)", min_value=0.1, value=base.battery.discharge_power_mw
    )
    initial_soc = st.number_input(
        "Initial SOC (MWh)", min_value=0.0, value=base.battery.initial_soc_mwh
    )
    terminal_soc = st.number_input(
        "Terminal SOC (MWh)", min_value=0.0, value=float(base.battery.terminal_soc_mwh or 0.0)
    )
    solver = st.selectbox("Solver", ["highs", "gurobi"], index=0)

if st.button("Run optimization", type="primary"):
    try:
        battery = replace(
            base.battery,
            energy_capacity_mwh=float(energy_capacity),
            max_soc_mwh=float(energy_capacity),
            charge_power_mw=float(charge_power),
            discharge_power_mw=float(discharge_power),
            initial_soc_mwh=float(initial_soc),
            terminal_soc_mwh=float(terminal_soc),
        )
        config = replace(base, battery=battery)
        result = run_case(config, solver_override=solver)
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
        st.stop()

    k = result.kpis
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baseline revenue", f"€{k['baseline_revenue_eur']:,.0f}")
    c2.metric("Optimized revenue", f"€{k['optimized_revenue_eur']:,.0f}")
    c3.metric(
        "Revenue uplift",
        f"€{k['revenue_uplift_eur']:,.0f}",
        f"{k['revenue_uplift_pct']:.1f}%",
    )
    c4.metric("Equivalent cycles", f"{k['equivalent_full_cycles']:.2f}")

    dispatch = result.dispatch

    input_fig = go.Figure()
    input_fig.add_trace(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["wind_available_mwh"],
            name="Wind available (MWh)",
            yaxis="y1",
        )
    )
    input_fig.add_trace(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["price_eur_mwh"],
            name="Price (EUR/MWh)",
            yaxis="y2",
        )
    )
    input_fig.update_layout(
        title="Wind availability and electricity price",
        yaxis={"title": "Wind (MWh)"},
        yaxis2={"title": "Price (EUR/MWh)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h"},
    )
    st.plotly_chart(input_fig, use_container_width=True)

    dispatch_fig = go.Figure()
    for column, name in [
        ("wind_to_grid_mwh", "Wind to grid"),
        ("battery_charge_mwh", "Battery charge"),
        ("battery_discharge_mwh", "Battery discharge"),
        ("curtailment_mwh", "Curtailment"),
    ]:
        dispatch_fig.add_trace(
            go.Bar(x=dispatch["timestamp"], y=dispatch[column], name=name)
        )
    dispatch_fig.update_layout(
        barmode="group",
        title="Optimized hourly dispatch",
        yaxis_title="Energy (MWh)",
    )
    st.plotly_chart(dispatch_fig, use_container_width=True)

    soc_fig = go.Figure(
        go.Scatter(
            x=dispatch["timestamp"],
            y=dispatch["soc_mwh"],
            name="Battery SOC",
            mode="lines+markers",
        )
    )
    soc_fig.update_layout(title="Battery state of charge", yaxis_title="SOC (MWh)")
    st.plotly_chart(soc_fig, use_container_width=True)

    charging = dispatch.loc[dispatch["battery_charge_mwh"] > 1e-6]
    discharging = dispatch.loc[dispatch["battery_discharge_mwh"] > 1e-6]
    if not charging.empty and not discharging.empty:
        avg_charge_price = charging["price_eur_mwh"].mean()
        avg_discharge_price = discharging["price_eur_mwh"].mean()
        st.info(
            "The optimizer shifts wind energy away from lower-value hours into "
            f"higher-value hours: average charging price €{avg_charge_price:.1f}/MWh "
            f"versus average discharging price €{avg_discharge_price:.1f}/MWh in this run."
        )

    st.dataframe(dispatch, use_container_width=True, hide_index=True)
else:
    st.info("Adjust assumptions if needed, then click **Run optimization**.")
