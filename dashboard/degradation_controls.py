"""Shared Streamlit inputs for the cycle-based battery degradation model."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from energy_hub.config import DegradationConfig, ProjectConfig


def degradation_inputs(base: ProjectConfig, key: str) -> DegradationConfig:
    """Checkbox plus replacement cost and cycle life; returns the resulting configuration."""
    defaults = base.degradation
    enabled = st.checkbox(
        "Price battery degradation",
        value=defaults.enabled,
        key=f"{key}_degradation",
        help=(
            "Charge every MWh cycled through the battery its share of cell replacement cost, so "
            "the optimizer only trades when the spread pays for the wear."
        ),
    )
    c1, c2 = st.columns(2)
    with c1:
        replacement = st.number_input(
            "Cell replacement cost (€/MWh)",
            min_value=0.0,
            value=float(defaults.cell_replacement_cost_eur_per_mwh),
            step=5_000.0,
            key=f"{key}_replacement_cost",
        )
    with c2:
        cycle_life = st.number_input(
            "Cycle life (full cycles)",
            min_value=100.0,
            value=float(defaults.cycle_life_full_cycles),
            step=500.0,
            key=f"{key}_cycle_life",
        )
    configured = replace(
        defaults,
        enabled=bool(enabled),
        cell_replacement_cost_eur_per_mwh=float(replacement),
        cycle_life_full_cycles=float(cycle_life),
    )
    if configured.enabled:
        st.caption(
            f"= €{configured.cost_eur_per_mwh_throughput:.2f} per MWh charged or discharged "
            f"(€{2 * configured.cost_eur_per_mwh_throughput:.2f} per full-cycle MWh)."
        )
    return configured
