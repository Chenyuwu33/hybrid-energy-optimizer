"""Command-line interface for the Hybrid Energy Optimizer."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import requests

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import BacktestResult, run_daily_backtest
from energy_hub.backtesting.sizing import SizingResult, parse_number_list, run_sizing_sweep
from energy_hub.config import load_config
from energy_hub.data.energinet import EnerginetClient
from energy_hub.data.io import load_hourly_inputs
from energy_hub.run import run_case


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energy-hub",
        description="Optimize and backtest wind-plus-battery dispatch scenarios.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an optimization case from a CSV")
    run_parser.add_argument("--config", required=True, help="Path to YAML configuration")
    run_parser.add_argument(
        "--solver",
        choices=["highs", "gurobi"],
        default=None,
        help="Override the solver specified in the YAML configuration",
    )
    _add_grid_limit_argument(run_parser)

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Fetch historical Energinet data and replay complete UTC days",
    )
    backtest_parser.add_argument("--config", required=True, help="Path to YAML configuration")
    backtest_parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD, inclusive")
    backtest_parser.add_argument("--end", required=True, help="End date YYYY-MM-DD, exclusive")
    backtest_parser.add_argument(
        "--area",
        choices=["DK1"],
        default="DK1",
        help="Danish bidding zone for v0.2 (currently DK1)",
    )
    backtest_parser.add_argument(
        "--wind-share",
        required=True,
        type=float,
        help="Hypothetical portfolio share of aggregate settled wind, in (0, 1]",
    )
    backtest_parser.add_argument(
        "--solver",
        choices=["highs", "gurobi"],
        default=None,
        help="Override the solver specified in the YAML configuration",
    )
    backtest_parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory; defaults to output_dir from the YAML configuration",
    )
    _add_grid_limit_argument(backtest_parser)

    size_parser = subparsers.add_parser(
        "size",
        help="Sweep battery power x duration and rank sizes by NPV",
        description=(
            "Backtest every power x duration combination and appraise each with the "
            "investment assumptions from the YAML configuration. Uses the configured "
            "input CSV unless --start/--end/--wind-share select historical Energinet data."
        ),
    )
    size_parser.add_argument("--config", required=True, help="Path to YAML configuration")
    size_parser.add_argument(
        "--powers", required=True, help="Comma-separated battery power options in MW, e.g. 10,25,50"
    )
    size_parser.add_argument(
        "--durations", required=True, help="Comma-separated durations in hours, e.g. 1,2,4"
    )
    size_parser.add_argument("--start", default=None, help="Historical start date YYYY-MM-DD")
    size_parser.add_argument(
        "--end", default=None, help="Historical end date YYYY-MM-DD, exclusive"
    )
    size_parser.add_argument("--area", choices=["DK1"], default="DK1", help="Danish bidding zone")
    size_parser.add_argument(
        "--wind-share",
        type=float,
        default=None,
        help="Historical portfolio share of aggregate settled wind, in (0, 1]",
    )
    size_parser.add_argument(
        "--solver",
        choices=["highs", "gurobi"],
        default=None,
        help="Override the solver specified in the YAML configuration",
    )
    size_parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory; defaults to output_dir from the YAML configuration",
    )
    _add_grid_limit_argument(size_parser)
    return parser


def _add_grid_limit_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--grid-limit-mw",
        type=float,
        default=None,
        help="Override grid_export_limit_mw from the YAML configuration (MW at the "
        "connection point; applies to the optimizer and the baselines)",
    )


def _effective_grid_limit(args: argparse.Namespace, config) -> float | None:
    if args.grid_limit_mw is None:
        return config.grid_export_limit_mw
    if not args.grid_limit_mw > 0:
        raise ValueError("--grid-limit-mw must be positive")
    return float(args.grid_limit_mw)


def _write_outputs(output_dir: Path, dispatch, kpis: dict[str, float | str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch.to_csv(output_dir / "dispatch.csv", index=False)
    (output_dir / "kpis.json").write_text(
        json.dumps(kpis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_backtest_outputs(
    output_dir: Path,
    inputs,
    result: BacktestResult,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs.to_csv(output_dir / "backtest_inputs.csv", index=False)
    result.daily.to_csv(output_dir / "backtest_daily.csv", index=False)
    (output_dir / "backtest_summary.json").write_text(
        json.dumps(result.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_sizing_outputs(output_dir: Path, result: SizingResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result.table.to_csv(output_dir / "sizing.csv", index=False)
    best = result.best
    summary = {
        "days": result.days,
        "annualization_factor": result.annualization_factor,
        "grid_export_limit_mw": result.grid_export_limit_mw,
        "assumptions": vars(result.assumptions),
        "best_size": None if best is None else {
            "power_mw": float(best["power_mw"]),
            "duration_h": float(best["duration_h"]),
            "energy_mwh": float(best["energy_mwh"]),
            "npv_eur": float(best["npv_eur"]),
            "irr": _optional_float(best["irr"]),
        },
    }
    (output_dir / "sizing_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _optional_float(value: object) -> float | None:
    """Convert a possibly missing (None/NaN) table value to float or None."""
    if value is None:
        return None
    number = float(value)
    return None if number != number else number


def _sizing_inputs(args: argparse.Namespace, config):
    historical = [args.start, args.end, args.wind_share]
    if all(value is None for value in historical):
        return load_hourly_inputs(config.input_csv), str(config.input_csv)
    if any(value is None for value in historical):
        raise ValueError("historical sizing needs --start, --end and --wind-share together")
    if not 0.0 < args.wind_share <= 1.0:
        raise ValueError("--wind-share must be greater than 0 and no greater than 1")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start >= end:
        raise ValueError("--start must be before --end")
    inputs = EnerginetClient().fetch_hourly_inputs(
        start=start, end=end, price_area=args.area, wind_share=args.wind_share
    )
    return inputs, f"Energinet {args.area} {start.isoformat()} to {end.isoformat()}"


def _run_sizing(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    powers = parse_number_list(args.powers, "--powers")
    durations = parse_number_list(args.durations, "--durations")
    grid_limit = _effective_grid_limit(args, config)
    output_dir = Path(args.output_dir) if args.output_dir else config.output_dir
    inputs, source = _sizing_inputs(args, config)

    result = run_sizing_sweep(
        inputs,
        config.battery,
        powers,
        durations,
        config.investment,
        solver=args.solver or config.solver,
        grid_export_limit_mw=grid_limit,
    )
    _write_sizing_outputs(output_dir, result)

    print("Battery sizing sweep")
    print(
        f"Data:               {source} ({result.days} day(s), "
        f"x{result.annualization_factor:.1f} to annual)"
    )
    if grid_limit is not None:
        print(f"Grid export limit:  {grid_limit:g} MW")
    print()
    print(f"{'Power':>8} {'Hours':>6} {'Annual value':>14} {'Capex':>14} {'NPV':>14} {'IRR':>7}")
    for row in result.table.itertuples():
        irr_value = _optional_float(row.irr)
        irr = "n/a" if irr_value is None else f"{irr_value:.1%}"
        print(
            f"{row.power_mw:>6g}MW {row.duration_h:>5g}h €{row.annual_battery_value_eur:>12,.0f} "
            f"€{row.capex_eur:>12,.0f} €{row.npv_eur:>12,.0f} {irr:>7}"
        )
    print()
    best = result.best
    if best is None:
        print("No size has a positive NPV under these assumptions.")
    else:
        print(
            f"Best NPV: {best['power_mw']:g} MW / {best['duration_h']:g} h "
            f"({best['energy_mwh']:g} MWh), NPV €{best['npv_eur']:,.0f}"
        )
    if result.days < 28:
        print(
            "Warning: fewer than 28 days were backtested; "
            "annualized values may be unrepresentative."
        )
    print(f"Results written to: {output_dir}")
    return 0


def _run_single_case(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    config = replace(config, grid_export_limit_mw=_effective_grid_limit(args, config))
    result = run_case(config, solver_override=args.solver)
    _write_outputs(config.output_dir, result.dispatch, result.kpis)

    print("Hybrid Energy Optimizer")
    print(f"Baseline revenue:  €{result.kpis['baseline_revenue_eur']:,.2f}")
    print(f"Optimized revenue: €{result.kpis['optimized_revenue_eur']:,.2f}")
    print(f"Revenue uplift:     €{result.kpis['revenue_uplift_eur']:,.2f}")
    print(f"Battery value:      €{result.kpis['battery_incremental_value_eur']:,.2f}")
    if config.grid_export_limit_mw is not None:
        print(f"Grid export limit:  {config.grid_export_limit_mw:g} MW")
    print(f"Solver status:      {result.kpis['solver_status']}")
    print(f"Results written to: {config.output_dir}")
    return 0


def _run_historical_backtest(args: argparse.Namespace) -> int:
    if not 0.0 < args.wind_share <= 1.0:
        raise ValueError("--wind-share must be greater than 0 and no greater than 1")

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start >= end:
        raise ValueError("--start must be before --end")

    config = load_config(args.config)
    battery = Battery.from_config(config.battery)
    solver = args.solver or config.solver
    grid_limit = _effective_grid_limit(args, config)
    output_dir = Path(args.output_dir) if args.output_dir else config.output_dir

    client = EnerginetClient()
    inputs = client.fetch_hourly_inputs(
        start=start,
        end=end,
        price_area=args.area,
        wind_share=args.wind_share,
    )
    result = run_daily_backtest(inputs, battery, solver=solver, grid_export_limit_mw=grid_limit)
    _write_backtest_outputs(output_dir, inputs, result)

    print("Historical backtest")
    print(f"Area:                       {args.area}")
    print(f"Period:                     {start.isoformat()} to {end.isoformat()} (end exclusive)")
    print(f"Portfolio wind share:       {args.wind_share:.2%}")
    if grid_limit is not None:
        print(f"Grid export limit:          {grid_limit:g} MW")
    print(f"Days replayed:              {result.summary['days']}")
    print(
        "Sell-all baseline:          "
        f"€{result.summary['baseline_sell_all_revenue_eur']:,.2f}"
    )
    print(
        "Curtail-negative baseline:  "
        f"€{result.summary['baseline_curtail_negative_revenue_eur']:,.2f}"
    )
    print(f"Optimized revenue:          €{result.summary['optimized_revenue_eur']:,.2f}")
    print(
        "Battery incremental value:  "
        f"€{result.summary['battery_incremental_vs_curtail_eur']:,.2f}"
    )
    print(f"Results written to:         {output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process-style exit code."""
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return _run_single_case(args)
        if args.command == "backtest":
            return _run_historical_backtest(args)
        if args.command == "size":
            return _run_sizing(args)
        parser.error("a command is required")
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
