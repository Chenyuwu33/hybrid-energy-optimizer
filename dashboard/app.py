"""Interactive Streamlit dashboard for synthetic and historical workflows."""

import streamlit as st
from historical_backtest import render_historical_backtest
from sample_dispatch import render_sample_dispatch

from energy_hub.config import load_config

st.set_page_config(page_title="Hybrid Energy Optimizer", layout="wide")
st.title("Hybrid Energy Optimizer")
st.caption("Wind + battery decision-support prototype")
st.markdown(
    """
Explore the optimizer in two ways: a transparent synthetic 24-hour sample and a
capacity-based historical DK1 backtest using official Energinet data. Both workflows
reuse the same wind + BESS optimization core.
"""
)

base = load_config("configs/base.yaml")
sample_tab, historical_tab = st.tabs(["Sample Dispatch", "Historical DK1 Backtest"])

with sample_tab:
    render_sample_dispatch(base)

with historical_tab:
    render_historical_backtest(base)
