"""Interactive Streamlit dashboard for synthetic and historical workflows."""

from dataclasses import replace
from pathlib import Path

import streamlit as st
from bess_sizing import render_bess_sizing
from historical_backtest import render_historical_backtest
from sample_dispatch import render_sample_dispatch

from energy_hub.config import ProjectConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG_PATH = REPO_ROOT / "configs" / "base.yaml"


@st.cache_resource
def load_base_config() -> ProjectConfig:
    """Load the base config with repo-relative paths, independent of the working directory.

    Streamlit Community Cloud, Docker and local runs may start from different directories.
    """
    config = load_config(BASE_CONFIG_PATH)
    if not config.input_csv.is_absolute():
        config = replace(config, input_csv=REPO_ROOT / config.input_csv)
    return config


st.set_page_config(page_title="Hybrid Energy Optimizer", layout="wide")
st.title("Hybrid Energy Optimizer")
st.caption("Wind + battery decision-support prototype")
st.markdown(
    """
Explore the optimizer with a transparent synthetic 24-hour sample, a capacity-based
historical DK1 backtest using official Energinet data, and a battery sizing sweep with
NPV appraisal. All workflows reuse the same wind + BESS optimization core.
"""
)

base = load_base_config()
sample_tab, historical_tab, sizing_tab = st.tabs(
    ["Sample Dispatch", "Historical DK1 Backtest", "BESS Sizing"]
)

with sample_tab:
    render_sample_dispatch(base)

with historical_tab:
    render_historical_backtest(base)

with sizing_tab:
    render_bess_sizing(base)
