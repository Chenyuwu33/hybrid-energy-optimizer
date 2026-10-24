import pandas as pd
import pytest

from energy_hub.assets.battery import Battery
from energy_hub.config import GridChargingConfig
from energy_hub.optimization.dispatch import optimize_dispatch


def _inputs(prices: list[float], wind: list[float] | None = None) -> pd.DataFrame:
    if wind is None:
        wind = [10.0] * len(prices)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=len(prices), freq="h"),
            "wind_mwh": wind,
            "price_eur_mwh": prices,
        }
    )


def _battery(*, terminal: float | None = 0.0) -> Battery:
    return Battery(
        energy_capacity_mwh=20.0,
        charge_power_mw=10.0,
        discharge_power_mw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_mwh=0.0,
        max_soc_mwh=20.0,
        initial_soc_mwh=0.0,
        terminal_soc_mwh=terminal,
        throughput_cost_eur_per_mwh=0.0,
    )


def test_dispatch_respects_physics_and_shifts_energy_to_high_price() -> None:
    inputs = _inputs([10.0, 20.0, 100.0, 50.0])
    battery = _battery()
    result = optimize_dispatch(inputs, battery, solver="highs")
    dispatch = result.dispatch

    assert result.solver_status in {"optimal", "feasible"}
    flow_columns = [
        "wind_to_grid_mwh",
        "battery_charge_mwh",
        "battery_discharge_mwh",
        "grid_export_mwh",
        "curtailment_mwh",
        "soc_mwh",
    ]
    assert (dispatch[flow_columns] >= -1e-8).all().all()
    assert (
        dispatch["wind_to_grid_mwh"]
        + dispatch["battery_charge_mwh"]
        + dispatch["curtailment_mwh"]
    ).to_numpy() == pytest.approx(dispatch["wind_available_mwh"].to_numpy(), abs=1e-7)
    assert dispatch["battery_charge_mwh"].max() <= battery.charge_power_mw + 1e-8
    assert dispatch["battery_discharge_mwh"].max() <= battery.discharge_power_mw + 1e-8
    assert dispatch["soc_mwh"].min() >= battery.min_soc_mwh - 1e-8
    assert dispatch["soc_mwh"].max() <= battery.max_soc_mwh + 1e-8

    previous_soc = battery.initial_soc_mwh
    for row in dispatch.itertuples(index=False):
        expected_soc = (
            previous_soc
            + battery.charge_efficiency * row.battery_charge_mwh
            - row.battery_discharge_mwh / battery.discharge_efficiency
        )
        assert row.soc_mwh == pytest.approx(expected_soc, abs=1e-7)
        previous_soc = row.soc_mwh

    assert dispatch.iloc[0]["battery_charge_mwh"] == pytest.approx(10.0, abs=1e-7)
    assert dispatch.iloc[2]["battery_discharge_mwh"] == pytest.approx(10.0, abs=1e-7)
    assert dispatch.iloc[-1]["soc_mwh"] == pytest.approx(0.0, abs=1e-7)


def test_terminal_soc_is_respected() -> None:
    battery = _battery(terminal=5.0)
    result = optimize_dispatch(_inputs([10.0, 20.0, 100.0, 50.0]), battery)
    assert result.dispatch.iloc[-1]["soc_mwh"] == pytest.approx(5.0, abs=1e-7)


def test_negative_price_case_remains_physically_valid() -> None:
    result = optimize_dispatch(_inputs([-50.0, 0.0]), _battery())
    dispatch = result.dispatch
    assert (dispatch["grid_export_mwh"] >= -1e-8).all()
    assert dispatch.iloc[0]["wind_to_grid_mwh"] <= 1e-7
    assert (
        dispatch.iloc[0]["battery_charge_mwh"] + dispatch.iloc[0]["curtailment_mwh"]
    ) == pytest.approx(10.0, abs=1e-7)


def test_unknown_solver_raises_readable_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="not-a-solver"):
        optimize_dispatch(_inputs([10.0, 20.0]), _battery(), solver="not-a-solver")


def test_gurobi_without_pyomo_raises_readable_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="gurobi"):
        optimize_dispatch(_inputs([10.0, 20.0]), _battery(), solver="gurobi")


def test_grid_export_limit_caps_export_and_battery_absorbs_excess_wind() -> None:
    # 30 MWh wind in cheap hours behind a 20 MW connection, nothing in expensive hours.
    inputs = _inputs([10.0, 10.0, 100.0, 100.0], wind=[30.0, 30.0, 0.0, 0.0])
    battery = _battery()

    result = optimize_dispatch(inputs, battery, solver="highs", grid_export_limit_mw=20.0)
    dispatch = result.dispatch

    assert dispatch["grid_export_mwh"].max() <= 20.0 + 1e-7
    # 20 MWh exported per cheap hour, a net 10 MWh stored each, released in expensive hours.
    net_storage = dispatch["battery_charge_mwh"] - dispatch["battery_discharge_mwh"]
    assert net_storage.tolist() == pytest.approx([10.0, 10.0, -10.0, -10.0])
    assert dispatch["grid_export_mwh"].tolist() == pytest.approx([20.0, 20.0, 10.0, 10.0])
    assert result.objective_eur == pytest.approx(2 * 20 * 10.0 + 2 * 10 * 100.0)


def test_grid_export_limit_also_caps_battery_discharge() -> None:
    inputs = _inputs([10.0, 100.0], wind=[20.0, 15.0])
    battery = _battery()

    result = optimize_dispatch(inputs, battery, solver="highs", grid_export_limit_mw=20.0)

    # Hour 1 already has 15 MWh of wind, so only 5 MWh of headroom is left for discharge;
    # storing more than that in hour 0 is worthless. (Charge/discharge splits within an hour
    # are not unique with lossless storage, so only exports and the hour-1 shift are checked.)
    dispatch = result.dispatch
    assert dispatch["grid_export_mwh"].tolist() == pytest.approx([15.0, 20.0])
    assert dispatch["wind_to_grid_mwh"].iloc[1] + dispatch["battery_discharge_mwh"].iloc[
        1
    ] == pytest.approx(20.0)
    assert dispatch["battery_discharge_mwh"].iloc[1] >= 5.0 - 1e-7
    assert result.objective_eur == pytest.approx(15.0 * 10.0 + 20.0 * 100.0)


@pytest.mark.parametrize("limit", [0.0, -5.0, float("nan"), float("inf")])
def test_invalid_grid_export_limit_raises_value_error(limit: float) -> None:
    with pytest.raises(ValueError, match="grid_export_limit_mw"):
        optimize_dispatch(_inputs([10.0]), _battery(), grid_export_limit_mw=limit)


def test_lossless_storage_does_not_charge_and_discharge_in_the_same_hour() -> None:
    # Wind above a grid limit with free, lossless storage: cycling within an hour is exactly
    # as profitable as not cycling, so only the solver's tie-break keeps throughput honest.
    inputs = _inputs([10.0, 10.0, 100.0, 100.0], wind=[30.0, 30.0, 0.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), solver="highs", grid_export_limit_mw=20.0)

    dispatch = result.dispatch
    both = (dispatch["battery_charge_mwh"] > 1e-7) & (dispatch["battery_discharge_mwh"] > 1e-7)
    assert not both.any()
    assert dispatch["battery_charge_mwh"].sum() == pytest.approx(20.0)
    # The reported objective is pure market revenue; the tie-break cost is not included.
    assert result.objective_eur == pytest.approx(2 * 20 * 10.0 + 2 * 10 * 100.0, abs=1e-9)


def _grid_charging(fee: float = 0.0, limit: float | None = None) -> GridChargingConfig:
    return GridChargingConfig(enabled=True, import_fee_eur_per_mwh=fee, import_limit_mw=limit)


def test_grid_charging_is_off_by_default_even_when_profitable() -> None:
    inputs = _inputs([10.0, 100.0], wind=[0.0, 0.0])

    for charging in (None, GridChargingConfig(enabled=False)):
        dispatch = optimize_dispatch(inputs, _battery(), grid_charging=charging).dispatch
        assert dispatch["grid_import_mwh"].sum() == pytest.approx(0.0)


def test_grid_charging_buys_cheap_sells_dear_net_of_import_fee() -> None:
    inputs = _inputs([10.0, 100.0], wind=[0.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), grid_charging=_grid_charging(fee=5.0))

    dispatch = result.dispatch
    assert dispatch["grid_import_mwh"].tolist() == pytest.approx([10.0, 0.0])
    assert dispatch["battery_discharge_mwh"].tolist() == pytest.approx([0.0, 10.0])
    assert dispatch["battery_charge_from_wind_mwh"].sum() == pytest.approx(0.0)
    assert result.objective_eur == pytest.approx(10 * 100.0 - 10 * (10.0 + 5.0))


def test_import_fee_larger_than_the_spread_prevents_arbitrage() -> None:
    inputs = _inputs([10.0, 15.0], wind=[0.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), grid_charging=_grid_charging(fee=10.0))

    assert result.dispatch["grid_import_mwh"].sum() == pytest.approx(0.0)
    assert result.objective_eur == pytest.approx(0.0)


def test_wind_and_grid_charging_share_the_battery_charge_power() -> None:
    inputs = _inputs([10.0, 100.0], wind=[6.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), grid_charging=_grid_charging(fee=5.0))

    dispatch = result.dispatch
    # Charging from wind forgoes 10 EUR/MWh of export; importing costs 15, so wind goes first
    # and the grid tops up to the 10 MW charge limit.
    assert dispatch["battery_charge_from_wind_mwh"].iloc[0] == pytest.approx(6.0)
    assert dispatch["grid_import_mwh"].iloc[0] == pytest.approx(4.0)
    assert dispatch["battery_charge_mwh"].max() <= 10.0 + 1e-7
    assert result.objective_eur == pytest.approx(10 * 100.0 - 4 * 15.0)


def test_grid_import_limit_caps_hourly_imports() -> None:
    inputs = _inputs([10.0, 100.0], wind=[0.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), grid_charging=_grid_charging(limit=3.0))

    assert result.dispatch["grid_import_mwh"].max() <= 3.0 + 1e-7
    assert result.objective_eur == pytest.approx(3 * 100.0 - 3 * 10.0)


def test_grid_charging_is_paid_to_import_at_negative_prices() -> None:
    inputs = _inputs([-20.0, 50.0], wind=[0.0, 0.0])

    result = optimize_dispatch(inputs, _battery(), grid_charging=_grid_charging())

    assert result.dispatch["grid_import_mwh"].iloc[0] == pytest.approx(10.0)
    assert result.objective_eur == pytest.approx(10 * 20.0 + 10 * 50.0)


def test_dispatch_reports_wind_and_grid_charging_separately() -> None:
    dispatch = optimize_dispatch(_inputs([10.0, 20.0]), _battery()).dispatch

    assert {"battery_charge_from_wind_mwh", "grid_import_mwh"}.issubset(dispatch.columns)
    assert (
        dispatch["wind_to_grid_mwh"]
        + dispatch["battery_charge_from_wind_mwh"]
        + dispatch["curtailment_mwh"]
    ).to_numpy() == pytest.approx(dispatch["wind_available_mwh"].to_numpy())


def test_degradation_cost_blocks_trades_whose_spread_does_not_pay_for_wear() -> None:
    from dataclasses import replace

    # Shifting 1 MWh costs 2 MWh of throughput: at 5 EUR/MWh that is 10 EUR per MWh shifted.
    worn = replace(_battery(), degradation_cost_eur_per_mwh=5.0)

    small_spread = _inputs([50.0, 58.0], wind=[10.0, 0.0])
    assert optimize_dispatch(small_spread, _battery()).dispatch[
        "battery_discharge_mwh"
    ].sum() == pytest.approx(10.0)
    blocked = optimize_dispatch(small_spread, worn)
    assert blocked.dispatch["battery_discharge_mwh"].sum() == pytest.approx(0.0)
    assert blocked.objective_eur == pytest.approx(10 * 50.0)

    large_spread = _inputs([50.0, 70.0], wind=[10.0, 0.0])
    traded = optimize_dispatch(large_spread, worn)
    assert traded.dispatch["battery_discharge_mwh"].sum() == pytest.approx(10.0)
    # Revenue 10 x 70 minus 20 MWh throughput x 5 EUR/MWh degradation.
    assert traded.objective_eur == pytest.approx(10 * 70.0 - 20 * 5.0)
