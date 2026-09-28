"""Command-line interface for the Hybrid Energy Optimizer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import requests

from energy_hub.assets.battery import Battery
from energy_hub.backtesting.runner import BacktestResult, run_daily_backtest
from energy_hub.config import load_config
from energy_hub.data.energinet import EnerginetClient
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
    return parser


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


def _run_single_case(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = run_case(config, solver_override=args.solver)
    _write_outputs(config.output_dir, result.dispatch, result.kpis)

    print("Hybrid Energy Optimizer")
    print(f"Baseline revenue:  €{result.kpis['baseline_revenue_eur']:,.2f}")
    print(f"Optimized revenue: €{result.kpis['optimized_revenue_eur']:,.2f}")
    print(f"Revenue uplift:     €{result.kpis['revenue_uplift_eur']:,.2f}")
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
    output_dir = Path(args.output_dir) if args.output_dir else config.output_dir

    client = EnerginetClient()
    inputs = client.fetch_hourly_inputs(
        start=start,
        end=end,
        price_area=args.area,
        wind_share=args.wind_share,
    )
    result = run_daily_backtest(inputs, battery, solver=solver)
    _write_backtest_outputs(output_dir, inputs, result)

    print("Historical backtest")
    print(f"Area:                       {args.area}")
    print(f"Period:                     {start.isoformat()} to {end.isoformat()} (end exclusive)")
    print(f"Portfolio wind share:       {args.wind_share:.2%}")
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
        parser.error("a command is required")
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
