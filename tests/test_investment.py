import math

import numpy as np
import pytest

from energy_hub.economics.investment import (
    InvestmentAssumptions,
    annual_cash_flows,
    battery_capex,
    evaluate_battery_investment,
    internal_rate_of_return,
    net_present_value,
    simple_payback_years,
)


def test_capex_splits_energy_and_power_components() -> None:
    assumptions = InvestmentAssumptions(
        energy_capex_eur_per_mwh=100_000.0, power_capex_eur_per_mw=250_000.0
    )

    assert battery_capex(10.0, 5.0, assumptions) == pytest.approx(1_000_000.0 + 1_250_000.0)


def test_npv_irr_and_payback_match_hand_calculation() -> None:
    flows = np.array([-100.0, 60.0, 60.0])

    assert net_present_value(0.10, flows) == pytest.approx(-100 + 60 / 1.1 + 60 / 1.21)
    # 60x + 60x^2 = 100 with x = 1 / (1 + r)
    x = (-1 + math.sqrt(1 + 20 / 3)) / 2
    assert internal_rate_of_return(flows) == pytest.approx(1 / x - 1, abs=1e-6)
    assert simple_payback_years(flows) == pytest.approx(1 + 40 / 60)


def test_projects_that_never_repay_have_no_payback_and_no_irr_when_flows_negative() -> None:
    assert simple_payback_years(np.array([-100.0, 10.0, 10.0])) is None
    assert internal_rate_of_return(np.array([-100.0, -5.0, -5.0])) is None


def test_cash_flows_apply_degradation_and_fixed_om() -> None:
    assumptions = InvestmentAssumptions(
        fixed_om_pct_of_capex=0.02, lifetime_years=3, annual_revenue_degradation=0.10
    )

    flows = annual_cash_flows(1_000.0, 200.0, assumptions)

    assert flows.tolist() == pytest.approx([-1_000.0, 200 - 20, 180 - 20, 162 - 20])


def test_evaluate_battery_investment_combines_capex_cash_flows_and_metrics() -> None:
    assumptions = InvestmentAssumptions(
        energy_capex_eur_per_mwh=100.0,
        power_capex_eur_per_mw=0.0,
        fixed_om_pct_of_capex=0.0,
        lifetime_years=2,
        discount_rate=0.10,
        annual_revenue_degradation=0.0,
    )

    result = evaluate_battery_investment(1.0, 1.0, 60.0, assumptions)

    assert result.capex_eur == pytest.approx(100.0)
    assert result.first_year_net_cash_flow_eur == pytest.approx(60.0)
    assert result.npv_eur == pytest.approx(-100 + 60 / 1.1 + 60 / 1.21)
    assert result.simple_payback_years == pytest.approx(1 + 40 / 60)


@pytest.mark.parametrize(
    "overrides",
    [
        {"energy_capex_eur_per_mwh": -1.0},
        {"fixed_om_pct_of_capex": 1.0},
        {"lifetime_years": 0},
        {"lifetime_years": 10.5},
        {"discount_rate": 1.5},
        {"annual_revenue_degradation": -0.1},
    ],
)
def test_invalid_investment_assumptions_raise(overrides: dict) -> None:
    with pytest.raises(ValueError):
        InvestmentAssumptions(**overrides)
