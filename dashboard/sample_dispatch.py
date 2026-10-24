"""Streamlit view for the original synthetic sample-dispatch workflow."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st
from degradation_controls import degradation_inputs
from grid_controls import grid_charging_inputs, grid_limit_input

from energy_hub.config import ProjectConfig, resize_battery_config, soc_percent_bounds
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
    base_battery = base.battery
    min_soc_pct, max_soc_pct = soc_percent_bounds(base_battery)

    def _base_pct(value_mwh: float | None) -> float:
        mwh = value_mwh if value_mwh is not None else base_battery.initial_soc_mwh
        pct = mwh / base_battery.energy_capacity_mwh * 100.0
        return min(max(pct, min_soc_pct), max_soc_pct)

    soc_help = f"Operating SOC range: {min_soc_pct:g}–{max_soc_pct:g}% of battery energy."

    with st.form("sample_dispatch_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            energy_capacity = st.number_input(
                "Battery energy (MWh)",
                min_value=1.0,
                value=float(base_battery.energy_capacity_mwh),
            )
            charge_power = st.number_input(
                "Charge power (MW)",
                min_value=0.1,
                value=float(base_battery.charge_power_mw),
            )
        with c2:
            discharge_power = st.number_input(
                "Discharge power (MW)",
                min_value=0.1,
                value=float(base_battery.discharge_power_mw),
            )
            initial_soc_pct = st.number_input(
                "Initial SOC (%)",
                min_value=min_soc_pct,
                max_value=max_soc_pct,
                value=_base_pct(base_battery.initial_soc_mwh),
                help=soc_help,
            )
        with c3:
            terminal_soc_pct = st.number_input(
                "Terminal SOC (%)",
                min_value=min_soc_pct,
                max_value=max_soc_pct,
                value=_base_pct(base_battery.terminal_soc_mwh),
                help=soc_help,
            )
            grid_limit = grid_limit_input(base)
            solver = st.selectbox("Solver", ["highs", "gurobi"], index=0)

        with st.expander("Grid charging (arbitrage)"):
            grid_charging = grid_charging_inputs(base, "sample")
        with st.expander("Battery degradation"):
            degradation = degradation_inputs(base, "sample")

        submitted = st.form_submit_button("Run sample optimization", type="primary")

    if not submitted:
        st.info("Adjust the sample assumptions, then run the optimization.")
        return

    try:
        battery = resize_battery_config(
            base_battery,
            energy_capacity_mwh=float(energy_capacity),
            charge_power_mw=float(charge_power),
            discharge_power_mw=float(discharge_power),
            initial_soc_pct=float(initial_soc_pct),
            terminal_soc_pct=float(terminal_soc_pct),
        )
        config = replace(
            base,
            battery=battery,
            grid_export_limit_mw=grid_limit,
            grid_charging=grid_charging,
            degradation=degradation,
        )
        result = run_case(config, solver_override=solver)
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
        return

    kpis = result.kpis
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Sell-all baseline", f"€{kpis['baseline_revenue_eur']:,.0f}")
    c2.metric("Optimized revenue", f"€{kpis['optimized_revenue_eur']:,.0f}")
    c3.metric(
        "Uplift vs sell-all",
        f"€{kpis['revenue_uplift_eur']:,.0f}",
        f"{kpis['revenue_uplift_pct']:.1f}%",
    )
    c4.metric(
        "Battery incremental value",
        f"€{kpis['battery_incremental_value_eur']:,.0f}",
        help="Optimized revenue minus a wind-only baseline that curtails at negative prices.",
    )
    c5.metric("Equivalent cycles", f"{kpis['equivalent_full_cycles']:.2f}")
    if degradation.enabled:
        st.caption(
            f"Battery degradation cost €{kpis['degradation_cost_eur']:,.0f} "
            f"({kpis['cycle_life_consumed_pct']:.3f}% of cycle life used), already deducted "
            "from the optimized revenue."
        )
    if grid_charging.enabled:
        st.caption(
            f"Grid charging: {kpis['total_grid_import_mwh']:,.1f} MWh bought for "
            f"€{kpis['grid_import_cost_eur']:,.0f} (including the import fee), already "
            "deducted from the optimized revenue."
        )
    if grid_limit is not None:
        st.caption(
            f"Grid export limit {grid_limit:g} MW was binding in "
            f"{kpis['grid_limit_binding_hours']:.0f} of {len(result.dispatch)} hours; "
            f"{kpis['wind_above_grid_limit_mwh']:,.0f} MWh of wind exceeded the limit. "
            "Both baselines curtail that excess, since they have no battery."
        )

    dispatch = result.dispatch
    st.plotly_chart(sample_input_figure(dispatch), width="stretch")
    st.plotly_chart(sample_dispatch_figure(dispatch, grid_limit), width="stretch")
    st.plotly_chart(sample_soc_figure(dispatch), width="stretch")

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

    st.dataframe(dispatch, width="stretch", hide_index=True)
