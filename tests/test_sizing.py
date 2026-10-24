import pandas as pd
import pytest

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import run_daily_backtest
from energy_hub.backtesting.sizing import SIZING_COLUMNS, parse_number_list, run_sizing_sweep
from energy_hub.config import load_config, resize_battery_config
from energy_hub.economics.investment import InvestmentAssumptions


def _two_day_inputs() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=48, freq="h")
    prices = [10.0 if (hour % 24) < 12 else 120.0 for hour in range(48)]
    return pd.DataFrame(
        {"timestamp": timestamps, "wind_mwh": [40.0] * 48, "price_eur_mwh": prices}
    )


def test_sweep_backtests_every_power_duration_combination() -> None:
    base = load_config("configs/base.yaml").battery

    result = run_sizing_sweep(_two_day_inputs(), base, [25, 10], [2, 1])

    table = result.table
    assert list(table.columns) == SIZING_COLUMNS
    assert table[["power_mw", "duration_h"]].values.tolist() == [
        [10.0, 1.0],
        [10.0, 2.0],
        [25.0, 1.0],
        [25.0, 2.0],
    ]
    assert table["energy_mwh"].tolist() == pytest.approx([10.0, 20.0, 25.0, 50.0])
    assert result.days == 2
    assert result.annualization_factor == pytest.approx(365 / 2)


def test_sweep_values_match_the_daily_backtest_and_investment_appraisal() -> None:
    base = load_config("configs/base.yaml").battery
    assumptions = InvestmentAssumptions(
        energy_capex_eur_per_mwh=50_000.0, power_capex_eur_per_mw=100_000.0
    )

    result = run_sizing_sweep(
        _two_day_inputs(), base, [10], [2], assumptions, grid_export_limit_mw=35.0
    )

    battery = Battery.from_config(
        resize_battery_config(
            base,
            energy_capacity_mwh=20.0,
            charge_power_mw=10.0,
            discharge_power_mw=10.0,
            initial_soc_pct=50.0,
            terminal_soc_pct=50.0,
        )
    )
    backtest = run_daily_backtest(_two_day_inputs(), battery, grid_export_limit_mw=35.0)
    row = result.table.iloc[0]
    period_value = backtest.summary["battery_incremental_vs_curtail_eur"]
    assert row["period_battery_value_eur"] == pytest.approx(period_value)
    assert row["annual_battery_value_eur"] == pytest.approx(period_value * 365 / 2)
    assert row["capex_eur"] == pytest.approx(20 * 50_000 + 10 * 100_000)
    assert result.grid_export_limit_mw == 35.0


def test_best_is_highest_positive_npv_or_none() -> None:
    base = load_config("configs/base.yaml").battery
    cheap = InvestmentAssumptions(energy_capex_eur_per_mwh=1.0, power_capex_eur_per_mw=1.0)
    expensive = InvestmentAssumptions(
        energy_capex_eur_per_mwh=10_000_000.0, power_capex_eur_per_mw=10_000_000.0
    )

    good = run_sizing_sweep(_two_day_inputs(), base, [5, 10], [1, 2], cheap)
    bad = run_sizing_sweep(_two_day_inputs(), base, [5, 10], [1, 2], expensive)

    assert good.best is not None
    assert good.best["npv_eur"] == pytest.approx(good.table["npv_eur"].max())
    assert bad.best is None


def test_sweep_rejects_too_many_or_invalid_options() -> None:
    base = load_config("configs/base.yaml").battery

    with pytest.raises(ValueError, match="limited to"):
        run_sizing_sweep(_two_day_inputs(), base, range(1, 12), range(1, 7))
    with pytest.raises(ValueError, match="positive"):
        run_sizing_sweep(_two_day_inputs(), base, [0, 10], [1])


def test_parse_number_list_sorts_deduplicates_and_validates() -> None:
    assert parse_number_list("25, 10;10 ,50", "powers") == [10.0, 25.0, 50.0]
    with pytest.raises(ValueError, match="comma-separated"):
        parse_number_list("10, abc", "powers")
    with pytest.raises(ValueError, match="at least one"):
        parse_number_list(" , ", "powers")
