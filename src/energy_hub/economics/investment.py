"""Battery investment appraisal: capex, discounted cash flows, NPV, IRR and payback."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class InvestmentAssumptions:
    """Simple, transparent BESS investment assumptions.

    Capex is split into an energy component (cells, enclosures; scales with MWh) and a power
    component (inverters/PCS, transformer, grid connection, balance of plant; scales with MW),
    so that the sweep can trade off duration against power. Defaults are placeholders inside
    the 2025-2026 published range for European utility-scale systems; replace them with
    project-specific quotes for any real decision.
    """

    energy_capex_eur_per_mwh: float = 100_000.0
    power_capex_eur_per_mw: float = 250_000.0
    fixed_om_pct_of_capex: float = 0.02
    lifetime_years: int = 15
    discount_rate: float = 0.08
    annual_revenue_degradation: float = 0.02

    def __post_init__(self) -> None:
        if self.energy_capex_eur_per_mwh < 0 or self.power_capex_eur_per_mw < 0:
            raise ValueError("capex assumptions must be non-negative")
        if not 0.0 <= self.fixed_om_pct_of_capex < 1.0:
            raise ValueError("fixed_om_pct_of_capex must be in [0, 1)")
        if int(self.lifetime_years) != self.lifetime_years or not 1 <= self.lifetime_years <= 50:
            raise ValueError("lifetime_years must be an integer between 1 and 50")
        if not -0.5 < self.discount_rate < 1.0:
            raise ValueError("discount_rate must be between -50% and 100%")
        if not 0.0 <= self.annual_revenue_degradation < 1.0:
            raise ValueError("annual_revenue_degradation must be in [0, 1)")


@dataclass(frozen=True)
class InvestmentResult:
    capex_eur: float
    annual_fixed_om_eur: float
    first_year_net_cash_flow_eur: float
    npv_eur: float
    irr: float | None
    simple_payback_years: float | None


def battery_capex(
    energy_mwh: float, power_mw: float, assumptions: InvestmentAssumptions
) -> float:
    """Upfront capex for a battery of the given energy and power rating."""
    return (
        assumptions.energy_capex_eur_per_mwh * float(energy_mwh)
        + assumptions.power_capex_eur_per_mw * float(power_mw)
    )


def annual_cash_flows(
    capex_eur: float, first_year_value_eur: float, assumptions: InvestmentAssumptions
) -> np.ndarray:
    """Year-0 capex followed by yearly net operating cash flows.

    Operating value declines geometrically with ``annual_revenue_degradation`` (capacity fade
    and market cannibalisation); fixed O&M is a constant share of capex.
    """
    years = np.arange(1, int(assumptions.lifetime_years) + 1)
    value = first_year_value_eur * (1.0 - assumptions.annual_revenue_degradation) ** (years - 1)
    om = assumptions.fixed_om_pct_of_capex * capex_eur
    return np.concatenate([[-float(capex_eur)], value - om])


def net_present_value(rate: float, cash_flows: np.ndarray) -> float:
    """NPV with cash flow ``i`` discounted by ``(1 + rate) ** i``."""
    periods = np.arange(len(cash_flows))
    return float(np.sum(np.asarray(cash_flows, dtype=float) / (1.0 + rate) ** periods))


def internal_rate_of_return(cash_flows: np.ndarray) -> float | None:
    """IRR by bisection, or ``None`` when NPV does not change sign on (-99%, 1000%).

    A conventional investment (outflow first, inflows later) has a single IRR; projects whose
    operating cash flows never repay the capex have none, which is reported as ``None``.
    """
    low, high = -0.99, 10.0
    npv_low = net_present_value(low, cash_flows)
    npv_high = net_present_value(high, cash_flows)
    if not (math.isfinite(npv_low) and math.isfinite(npv_high)) or npv_low * npv_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2.0
        npv_mid = net_present_value(mid, cash_flows)
        if abs(npv_mid) < 1e-6 or high - low < 1e-10:
            return mid
        if npv_low * npv_mid < 0:
            high = mid
        else:
            low, npv_low = mid, npv_mid
    return (low + high) / 2.0


def simple_payback_years(cash_flows: np.ndarray) -> float | None:
    """Undiscounted years until cumulative cash flow turns non-negative (interpolated)."""
    cumulative = np.cumsum(np.asarray(cash_flows, dtype=float))
    if cumulative[0] >= 0:
        return 0.0
    for year in range(1, len(cumulative)):
        if cumulative[year] >= 0:
            inflow = cash_flows[year]
            return float(year - 1 + (-cumulative[year - 1]) / inflow)
    return None


def evaluate_battery_investment(
    energy_mwh: float,
    power_mw: float,
    first_year_value_eur: float,
    assumptions: InvestmentAssumptions,
) -> InvestmentResult:
    """Appraise a battery whose first-year operating value is ``first_year_value_eur``."""
    capex = battery_capex(energy_mwh, power_mw, assumptions)
    flows = annual_cash_flows(capex, first_year_value_eur, assumptions)
    return InvestmentResult(
        capex_eur=capex,
        annual_fixed_om_eur=assumptions.fixed_om_pct_of_capex * capex,
        first_year_net_cash_flow_eur=float(flows[1]),
        npv_eur=net_present_value(assumptions.discount_rate, flows),
        irr=internal_rate_of_return(flows),
        simple_payback_years=simple_payback_years(flows),
    )
