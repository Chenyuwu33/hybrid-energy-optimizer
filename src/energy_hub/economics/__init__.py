"""Economic metrics for dispatch cases."""

from energy_hub.economics.investment import (
    InvestmentAssumptions,
    InvestmentResult,
    evaluate_battery_investment,
)
from energy_hub.economics.metrics import (
    calculate_baseline_revenue,
    calculate_curtail_negative_revenue,
    calculate_kpis,
)

__all__ = [
    "InvestmentAssumptions",
    "InvestmentResult",
    "calculate_baseline_revenue",
    "calculate_curtail_negative_revenue",
    "calculate_kpis",
    "evaluate_battery_investment",
]
