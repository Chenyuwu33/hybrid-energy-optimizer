"""Streamlit view for capacity-based DK1 historical backtesting."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

from energy_hub.backtesting.service import (
    HistoricalBacktestRequest,
    run_historical_backtest,
    soc_percent_bounds,
)
from energy_hub.config import ProjectConfig
from energy_hub.data.energinet import EnerginetClient
from energy_hub.presentation.charts import (
    daily_battery_value_figure,
    daily_cycles_figure,
    daily_revenue_figure,
    historical_wind_price_figure,
)

# Settled production data is published with a lag, so default to a recent complete week
# that is very likely already available.
_DEFAULT_LAG_DAYS = 14
_DEFAULT_WINDOW_DAYS = 7
_CACHE_TTL_SECONDS = 6 * 60 * 60


@st.cache_data(ttl=_CACHE_TTL_SECONDS, show_spinner="Fetching Energinet data…")
def _fetch_inputs_cached(
    start: date, end: date, price_area: str, wind_capacity_mw: float
) -> pd.DataFrame:
    """Fetch normalized hourly inputs once per scenario and reuse them across reruns.

    Changing only battery assumptions reruns the optimizer without hitting the API again.
    """
    return EnerginetClient().fetch_hourly_inputs_for_capacity(
        start=start,
        end=end,
        price_area=price_area,
        wind_capacity_mw=wind_capacity_mw,
    )


class CachedEnerginetClient:
    """HistoricalDataClient backed by Streamlit's data cache."""

    def fetch_hourly_inputs_for_capacity(
        self, start: date, end: date, price_area: str, wind_capacity_mw: float
    ) -> pd.DataFrame:
        return _fetch_inputs_cached(start, end, price_area, float(wind_capacity_mw)).copy()


def default_period(today: date | None = None) -> tuple[date, date]:
    end = (today or date.today()) - timedelta(days=_DEFAULT_LAG_DAYS)
    return end - timedelta(days=_DEFAULT_WINDOW_DAYS), end


def _methodology_note() -> None:
    st.warning(
        "Methodology: the wind farm is hypothetical and uses a DK1 regional onshore-wind "
        "capacity-factor profile derived from settled onshore production and monthly onshore "
        "installed capacity. It is not an individual wind farm's SCADA trace. Historical "
        "prices and wind are realized values, so this is a perfect-information benchmark, "
        "not realized trading PnL or investment advice. An optional grid export limit applies to "
        "the optimizer and both baselines alike. Battery degradation is not yet included."
    )


def render_historical_backtest(base: ProjectConfig) -> None:
    """Render an interactive capacity-based DK1 historical backtest."""
    st.subheader("Historical DK1 backtest")
    st.caption("End date is exclusive. Historical settlement data can be published with delay.")
    _methodology_note()
    min_soc_pct, max_soc_pct = soc_percent_bounds(base.battery)
    default_soc_pct = min(max(50.0, min_soc_pct), max_soc_pct)

    with st.form("historical_backtest_form"):
        d1, d2, d3 = st.columns(3)
        with d1:
            area = st.selectbox("Market area", ["DK1"], index=0)
            default_start, default_end = default_period()
            start = st.date_input("Start date", value=default_start)
            end = st.date_input("End date (exclusive)", value=default_end)
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
                "Initial SOC (%)",
                min_value=min_soc_pct,
                max_value=max_soc_pct,
                value=default_soc_pct,
                help=f"Operating SOC range: {min_soc_pct:g}–{max_soc_pct:g}% of battery energy.",
            )
            terminal_soc_pct = st.number_input(
                "Terminal SOC (%)",
                min_value=min_soc_pct,
                max_value=max_soc_pct,
                value=default_soc_pct,
                help=f"Operating SOC range: {min_soc_pct:g}–{max_soc_pct:g}% of battery energy.",
            )
            grid_limit_input = st.number_input(
                "Grid export limit (MW)",
                min_value=0.0,
                value=float(base.grid_export_limit_mw or 0.0),
                help=(
                    "Maximum export at the connection point "
                    "(wind to grid + battery discharge). 0 = unconstrained."
                ),
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
            grid_export_limit_mw=float(grid_limit_input) if grid_limit_input > 0 else None,
        )
        bundle = run_historical_backtest(
            request, base.battery, client=CachedEnerginetClient()
        )
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

    st.plotly_chart(
        historical_wind_price_figure(bundle.inputs, request.grid_export_limit_mw),
        width="stretch",
    )
    daily = bundle.result.daily
    st.plotly_chart(daily_battery_value_figure(daily), width="stretch")
    st.plotly_chart(daily_revenue_figure(daily), width="stretch")
    st.plotly_chart(daily_cycles_figure(daily), width="stretch")

    st.subheader("Daily results")
    st.dataframe(daily, width="stretch", hide_index=True)
