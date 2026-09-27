"""Command-line interface for the Hybrid Energy Optimizer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from energy_hub.config import load_config
from energy_hub.run import run_case


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energy-hub",
        description="Optimize wind-plus-battery dispatch for an hourly market scenario.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run an optimization case")
    run_parser.add_argument("--config", required=True, help="Path to YAML configuration")
    run_parser.add_argument(
        "--solver",
        choices=["highs", "gurobi"],
        default=None,
        help="Override the solver specified in the YAML configuration",
    )
    return parser


def _write_outputs(output_dir: Path, dispatch, kpis: dict[str, float | str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch.to_csv(output_dir / "dispatch.csv", index=False)
    (output_dir / "kpis.json").write_text(
        json.dumps(kpis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process-style exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.error("a command is required")

    try:
        config = load_config(args.config)
        result = run_case(config, solver_override=args.solver)
        _write_outputs(config.output_dir, result.dispatch, result.kpis)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Hybrid Energy Optimizer")
    print(f"Baseline revenue:  €{result.kpis['baseline_revenue_eur']:,.2f}")
    print(f"Optimized revenue: €{result.kpis['optimized_revenue_eur']:,.2f}")
    print(f"Revenue uplift:     €{result.kpis['revenue_uplift_eur']:,.2f}")
    print(f"Solver status:      {result.kpis['solver_status']}")
    print(f"Results written to: {config.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
