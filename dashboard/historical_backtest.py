"""Streamlit view for capacity-based DK1 historical backtesting."""

from __future__ import annotations

from datetime import date

import requests
import streamlit as st

from energy_hub.backtesting.service import (
    HistoricalBacktestRequest,
    run_historical_backtest,
)
from energy_hub.config import ProjectConfig
from energy_hub.presentation.charts import (
    daily_battery_value_figure,
    daily_cycles_figure,
    daily_revenue_figure,
    historical_wind_price_figure,
)


def _methodology_note() -> None:
    st.warning(
        "Methodology: the wind farm is hypothetical and uses a DK1 regional onshore-wind "
        "capacity-factor profile derived from settled onshore production and monthly onshore "
        "installed capacity. It is not an individual wind farm's SCADA trace. Historical "
        "prices and wind are realized values, so this is a perfect-information benchmark, "
        "not realized trading PnL or investment advice. Battery degradation and grid-connection "
        "limits are not yet included in v0.2.1."
    )


def render_historical_backtest(base: ProjectConfig) -> None:
    """Render an interactive capacity-based DK1 historical backtest."""
    st.subheader("Historical DK1 backtest")
    st.caption("End date is exclusive. Historical settlement data can be published with delay.")
    _methodology_note()

    with st.form("historical_backtest_form"):
        d1, d2, d3 = st.columns(3)
        with d1:
            area = st.selectbox("Market area", ["DK1"], index=0)
            start = st.date_input("Start date", value=date(2026, 9, 1))
            end = st.date_input("End date (exclusive)", value=date(2026, 9, 8))
        with d2:
            wind_capacity_mw = st.number_input(
                "Hypothetical onshore wind farm (MW)", min_value=1.0, value=100.0
            )
            battery_energy_mwh = st.number_input(
                "Battery energy (MWh)",
                min_value=1.0,
                value=float(base.battery.energy_capacity_mwh),
            )
            charge_power_mw = st.number_input(
                "Battery charge power (MW)",
                min_value=0.1,
                value=float(base.battery.charge_power_mw),
            )
        with d3:
            discharge_power_mw = st.number_input(
                "Battery discharge power (MW)",
                min_value=0.1,
                value=float(base.battery.discharge_power_mw),
            )
            initial_soc_pct = st.number_input(
                "Initial SOC (%)", min_value=0.0, max_value=100.0, value=50.0
            )
            terminal_soc_pct = st.number_input(
                "Terminal SOC (%)", min_value=0.0, max_value=100.0, value=50.0
            )
            solver = st.selectbox("Historical solver", ["highs", "gurobi"], index=0)

        submitted = st.form_submit_button("Run historical backtest", type="primary")

    if not submitted:
        st.info("Choose the historical period and asset sizes, then run the backtest.")
        return

    try:
        request = HistoricalBacktestRequest(
            start=start,
            end=end,
            area=area,
            wind_capacity_mw=float(wind_capacity_mw),
            battery_energy_mwh=float(battery_energy_mwh),
            charge_power_mw=float(charge_power_mw),
            discharge_power_mw=float(discharge_power_mw),
            initial_soc_pct=float(initial_soc_pct),
            terminal_soc_pct=float(terminal_soc_pct),
            solver=solver,
        )
        bundle = run_historical_backtest(request, base.battery)
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        st.error(str(exc))
        return

    summary = bundle.result.summary
    top = st.columns(4)
    top[0].metric("Days backtested", f"{summary['days']}")
    top[1].metric("Wind energy", f"{summary['wind_mwh']:,.0f} MWh")
    top[2].metric(
        "Sell-all baseline", f"€{summary['baseline_sell_all_revenue_eur']:,.0f}"
    )
    top[3].metric(
        "Curtail-negative baseline",
        f"€{summary['baseline_curtail_negative_revenue_eur']:,.0f}",
    )

    bottom = st.columns(4)
    bottom[0].metric("Optimized revenue", f"€{summary['optimized_revenue_eur']:,.0f}")
    bottom[1].metric(
        "Battery incremental value",
        f"€{summary['battery_incremental_vs_curtail_eur']:,.0f}",
    )
    bottom[2].metric(
        "Total uplift vs sell-all",
        f"€{summary['total_uplift_vs_sell_all_eur']:,.0f}",
    )
    bottom[3].metric("Equivalent full cycles", f"{summary['equivalent_full_cycles']:.2f}")

    st.plotly_chart(historical_wind_price_figure(bundle.inputs), use_container_width=True)
    daily = bundle.result.daily
    st.plotly_chart(daily_battery_value_figure(daily), use_container_width=True)
    st.plotly_chart(daily_revenue_figure(daily), use_container_width=True)
    st.plotly_chart(daily_cycles_figure(daily), use_container_width=True)

    st.subheader("Daily results")
    st.dataframe(daily, use_container_width=True, hide_index=True)
