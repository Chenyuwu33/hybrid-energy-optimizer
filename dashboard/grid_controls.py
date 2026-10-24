"""Shared Streamlit inputs for the grid connection (export limit and grid charging)."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from energy_hub.config import GridChargingConfig, ProjectConfig

GRID_LIMIT_HELP = (
    "Maximum export at the connection point (wind to grid + battery discharge). 0 = unconstrained."
)


def grid_limit_input(base: ProjectConfig) -> float | None:
    """Number input for the export limit; returns ``None`` for an unconstrained connection."""
    value = st.number_input(
        "Grid export limit (MW)",
        min_value=0.0,
        value=float(base.grid_export_limit_mw or 0.0),
        help=GRID_LIMIT_HELP,
    )
    return float(value) if value > 0 else None


def grid_charging_inputs(base: ProjectConfig, key: str) -> GridChargingConfig:
    """Checkbox, import fee and import limit for buying grid electricity to charge."""
    defaults = base.grid_charging
    enabled = st.checkbox(
        "Allow grid charging (arbitrage)",
        value=defaults.enabled,
        key=f"{key}_grid_charging",
        help=(
            "Let the battery buy electricity from the grid to charge, paying the market price "
            "plus the import fee. Often not allowed under wind support schemes."
        ),
    )
    fee = st.number_input(
        "Grid import fee (€/MWh)",
        min_value=0.0,
        value=float(defaults.import_fee_eur_per_mwh),
        key=f"{key}_import_fee",
        help="Tariffs and levies added to the market price per imported MWh. "
        "Energinet's 2026 system tariff is about €10/MWh.",
    )
    limit = st.number_input(
        "Grid import limit (MW)",
        min_value=0.0,
        value=float(defaults.import_limit_mw or 0.0),
        key=f"{key}_import_limit",
        help="0 = unconstrained.",
    )
    return replace(
        defaults,
        enabled=bool(enabled),
        import_fee_eur_per_mwh=float(fee),
        import_limit_mw=float(limit) if limit > 0 else None,
    )
