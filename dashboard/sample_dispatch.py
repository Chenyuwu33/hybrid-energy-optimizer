"""Streamlit view for the original synthetic sample-dispatch workflow."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from energy_hub.config import ProjectConfig
from energy_hub.presentation.charts import (
    sample_dispatch_figure,
    sample_input_figure,
    sample_soc_figure,
)
from energy_hub.run import run_case


def render_sample_dispatch(base: ProjectConfig) -> None:
    """Render the original v0.1 synthetic-case workflow."""
    st.subheader("Sample dispatch")
    st.caption("Synthetic 24-hour case for transparent model validation and quick demos.")

    with st.form("sample_dispatch_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            energy_capacity = st.number_input(
                "Battery energy (MWh)",
                min_value=1.0,
                value=float(base.battery.energy_capacity_mwh),
            )
            charge_power = st.number_input(
                "Charge power (MW)",
                min_value=0.1,
                value=float(base.battery.charge_power_mw),
            )
        with c2:
            discharge_power = st.number_input(
                "Discharge power (MW)",
                min_value=0.1,
                value=float(base.battery.discharge_power_mw),
            )
            initial_soc = st.number_input(
                "Initial SOC (MWh)",
                min_value=0.0,
                value=float(base.battery.initial_soc_mwh),
            )
        with c3:
            terminal_soc = st.number_input(
                "Terminal SOC (MWh)",
                min_value=0.0,
                value=float(base.battery.terminal_soc_mwh or 0.0),
            )
            solver = st.selectbox("Solver", ["highs", "gurobi"], index=0)

        submitted = st.form_submit_button("Run sample optimization", type="primary")

    if not submitted:
        st.info("Adjust the sample assumptions, then run the optimization.")
        return

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
        return

    kpis = result.kpis
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baseline revenue", f"€{kpis['baseline_revenue_eur']:,.0f}")
    c2.metric("Optimized revenue", f"€{kpis['optimized_revenue_eur']:,.0f}")
    c3.metric(
        "Revenue uplift",
        f"€{kpis['revenue_uplift_eur']:,.0f}",
        f"{kpis['revenue_uplift_pct']:.1f}%",
    )
    c4.metric("Equivalent cycles", f"{kpis['equivalent_full_cycles']:.2f}")

    dispatch = result.dispatch
    st.plotly_chart(sample_input_figure(dispatch), use_container_width=True)
    st.plotly_chart(sample_dispatch_figure(dispatch), use_container_width=True)
    st.plotly_chart(sample_soc_figure(dispatch), use_container_width=True)

    charging = dispatch.loc[dispatch["battery_charge_mwh"] > 1e-6]
    discharging = dispatch.loc[dispatch["battery_discharge_mwh"] > 1e-6]
    if not charging.empty and not discharging.empty:
        avg_charge_price = charging["price_eur_mwh"].mean()
        avg_discharge_price = discharging["price_eur_mwh"].mean()
        st.info(
            "The optimizer shifts wind energy from lower-value hours to higher-value "
            f"hours: average charging price €{avg_charge_price:.1f}/MWh versus average "
            f"discharging price €{avg_discharge_price:.1f}/MWh."
        )

    st.dataframe(dispatch, use_container_width=True, hide_index=True)
