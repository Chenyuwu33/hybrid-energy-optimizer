"""Streamlit view for the battery sizing sweep with NPV appraisal."""

from __future__ import annotations

from datetime import timedelta

import requests
import streamlit as st
from historical_backtest import CachedEnerginetClient, default_period

from energy_hub.backtesting.sizing import MAX_SWEEP_CASES, parse_number_list, run_sizing_sweep
from energy_hub.config import ProjectConfig
from energy_hub.data.io import load_hourly_inputs
from energy_hub.economics.investment import InvestmentAssumptions
from energy_hub.presentation.charts import sizing_npv_heatmap, sizing_value_capex_figure

_SAMPLE = "Synthetic 24-hour sample"
_HISTORICAL = "Historical DK1 (Energinet)"
_SIZING_WINDOW_DAYS = 14
_REPRESENTATIVE_DAYS = 28


def _format_table(table):
    shown = table.copy()
    shown["irr"] = shown["irr"].map(lambda v: "n/a" if v is None or v != v else f"{v:.1%}")
    shown["simple_payback_years"] = shown["simple_payback_years"].map(
        lambda v: "never" if v is None or v != v else f"{v:.1f}"
    )
    return shown.rename(
        columns={
            "power_mw": "Power (MW)",
            "duration_h": "Duration (h)",
            "energy_mwh": "Energy (MWh)",
            "period_battery_value_eur": "Period value (€)",
            "annual_battery_value_eur": "Annual value (€)",
            "annual_equivalent_full_cycles": "Cycles / year",
            "capex_eur": "Capex (€)",
            "annual_fixed_om_eur": "Fixed O&M (€/yr)",
            "npv_eur": "NPV (€)",
            "irr": "IRR",
            "simple_payback_years": "Payback (years)",
        }
    )


def render_bess_sizing(base: ProjectConfig) -> None:
    """Render the power x duration sizing sweep and its investment appraisal."""
    st.subheader("Battery sizing")
    st.caption(
        "Backtests every power x duration option on the same data and ranks them by NPV. "
        "Battery value = optimized revenue minus the battery-less curtail-negative baseline, "
        "scaled from the backtest period to one year."
    )
    st.warning(
        "Perfect-foresight backtest: annual values are an optimistic upper bound. The battery "
        "charges from wind only (no grid arbitrage or ancillary services), and the default "
        "costs are placeholders. Use project-specific quotes before drawing conclusions."
    )
    invest = base.investment

    with st.form("bess_sizing_form"):
        source = st.radio("Data", [_HISTORICAL, _SAMPLE], horizontal=True)
        d1, d2, d3 = st.columns(3)
        with d1:
            _, default_end = default_period()
            start = st.date_input(
                "Start date", value=default_end - timedelta(days=_SIZING_WINDOW_DAYS)
            )
            end = st.date_input("End date (exclusive)", value=default_end)
            wind_capacity_mw = st.number_input(
                "Hypothetical onshore wind farm (MW)", min_value=1.0, value=100.0
            )
        with d2:
            powers_text = st.text_input("Battery power options (MW)", value="10, 25, 50")
            durations_text = st.text_input("Duration options (hours)", value="1, 2, 4")
            grid_limit_input = st.number_input(
                "Grid export limit (MW)",
                min_value=0.0,
                value=float(base.grid_export_limit_mw or 0.0),
                help="0 = unconstrained. Applies to the optimizer and the baseline alike.",
            )
        with d3:
            energy_capex = st.number_input(
                "Energy capex (€/MWh)",
                min_value=0.0,
                value=float(invest.energy_capex_eur_per_mwh),
                step=10_000.0,
            )
            power_capex = st.number_input(
                "Power capex (€/MW)",
                min_value=0.0,
                value=float(invest.power_capex_eur_per_mw),
                step=10_000.0,
            )
            solver = st.selectbox("Solver", ["highs", "gurobi"], index=0, key="sizing_solver")
        with st.expander("More investment assumptions"):
            i1, i2 = st.columns(2)
            with i1:
                fixed_om_pct = st.number_input(
                    "Fixed O&M (% of capex per year)",
                    min_value=0.0,
                    max_value=99.0,
                    value=invest.fixed_om_pct_of_capex * 100.0,
                )
                lifetime = st.number_input(
                    "Lifetime (years)",
                    min_value=1,
                    max_value=50,
                    value=int(invest.lifetime_years),
                )
            with i2:
                discount_pct = st.number_input(
                    "Discount rate (%)",
                    min_value=-49.0,
                    max_value=99.0,
                    value=invest.discount_rate * 100.0,
                )
                degradation_pct = st.number_input(
                    "Annual value degradation (%)",
                    min_value=0.0,
                    max_value=99.0,
                    value=invest.annual_revenue_degradation * 100.0,
                    help="Yearly decline of battery value from capacity fade and cannibalisation.",
                )

        submitted = st.form_submit_button("Run sizing sweep", type="primary")

    if not submitted:
        st.info(
            f"Pick the data, size options (up to {MAX_SWEEP_CASES} combinations) and costs, "
            "then run the sweep."
        )
        return

    try:
        powers = parse_number_list(powers_text, "Battery power options")
        durations = parse_number_list(durations_text, "Duration options")
        assumptions = InvestmentAssumptions(
            energy_capex_eur_per_mwh=float(energy_capex),
            power_capex_eur_per_mw=float(power_capex),
            fixed_om_pct_of_capex=float(fixed_om_pct) / 100.0,
            lifetime_years=int(lifetime),
            discount_rate=float(discount_pct) / 100.0,
            annual_revenue_degradation=float(degradation_pct) / 100.0,
        )
        grid_limit = float(grid_limit_input) if grid_limit_input > 0 else None
        if source == _SAMPLE:
            inputs = load_hourly_inputs(base.input_csv)
        else:
            if start >= end:
                raise ValueError("start must be before end")
            inputs = CachedEnerginetClient().fetch_hourly_inputs_for_capacity(
                start=start, end=end, price_area="DK1", wind_capacity_mw=float(wind_capacity_mw)
            )
        with st.spinner(f"Backtesting {len(powers) * len(durations)} battery sizes…"):
            result = run_sizing_sweep(
                inputs,
                base.battery,
                powers,
                durations,
                assumptions,
                solver=solver,
                grid_export_limit_mw=grid_limit,
            )
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        st.error(str(exc))
        return

    best = result.best
    if best is None:
        st.error(
            "No size has a positive NPV under these assumptions. Larger price spreads, a "
            "tighter grid connection, lower capex or additional revenue streams would be needed."
        )
    else:
        irr = best["irr"]
        st.success(
            f"Highest NPV: **{best['power_mw']:g} MW / {best['duration_h']:g} h** "
            f"({best['energy_mwh']:g} MWh) — NPV €{best['npv_eur']:,.0f}"
            + ("" if irr is None or irr != irr else f", IRR {irr:.1%}")
        )
    if result.days < _REPRESENTATIVE_DAYS:
        st.caption(
            f"Only {result.days} day(s) were backtested and scaled "
            f"x{result.annualization_factor:.0f} to a year; seasonal effects are not captured."
        )

    st.plotly_chart(sizing_npv_heatmap(result.table), width="stretch")
    st.plotly_chart(sizing_value_capex_figure(result.table), width="stretch")
    st.dataframe(_format_table(result.table), width="stretch", hide_index=True)
    st.download_button(
        "Download results (CSV)",
        result.table.to_csv(index=False).encode("utf-8"),
        file_name="bess_sizing.csv",
        mime="text/csv",
    )
