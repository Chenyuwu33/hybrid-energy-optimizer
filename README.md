# Hybrid Energy Optimizer

A decision-support prototype for a practical renewable-energy operating problem:

> Given hourly wind generation and electricity prices, when should a wind asset sell electricity, charge a battery, discharge stored energy, or curtail generation?

The project is designed as a reusable foundation for hybrid renewable-energy analysis rather than a one-off notebook. Version 0.1 focuses on **wind + BESS + hourly market prices** and compares optimized dispatch against the simple baseline of selling all available wind directly to the grid.

> **Important:** v0.1 is an educational and decision-support prototype. It is not operational, trading, investment, or safety advice for any real asset. The included 24-hour dataset is synthetic and does not represent an actual Danish wind farm.

## What the project does

For every hourly time step, the optimizer decides how available wind energy is split between:

- direct grid export,
- battery charging,
- curtailment,
- and later battery discharge.

It respects battery power, energy, efficiency, SOC, and optional terminal-SOC constraints. The result is compared with a no-storage baseline using the same wind and price series.

The repository exposes the same core logic through:

- a Python package,
- the `energy-hub` command-line tool,
- an interactive Streamlit dashboard,
- automated tests and CI,
- and a Docker image definition.

## Architecture

```text
Hourly wind + prices
        |
        v
Data validation
        |
        v
Battery parameters
        |
        v
Dispatch optimization
 Pyomo + HiGHS / Gurobi
 SciPy-HiGHS compatibility fallback
        |
        v
Economic KPIs
        |
   +----+----+
   |         |
   v         v
  CLI    Streamlit
```

Core calculations live under `src/energy_hub/`. The Streamlit application is presentation-only and does not contain optimization equations.

## Quick start

### 1. Create an environment

```bash
python -m venv .venv
```

Activate it, then install the project:

```bash
python -m pip install -e ".[dev]"
```

Python 3.11 or newer is required.

### 2. Run the included case

```bash
energy-hub run --config configs/base.yaml --solver highs
```

The command writes:

```text
outputs/dispatch.csv
outputs/kpis.json
```

### 3. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

### Optional Gurobi

If you have a valid Gurobi installation/license:

```bash
python -m pip install -e ".[gurobi]"
energy-hub run --config configs/base.yaml --solver gurobi
```

## Example result

A reference run of the included synthetic case produced approximately:

| KPI | Value |
|---|---:|
| Baseline revenue | €65,977 |
| Optimized revenue | €80,061 |
| Revenue uplift | €14,084 |
| Solver status | optimal |

These figures are **only a reproducibility check for the synthetic sample**. They should not be interpreted as achievable project economics.
Because the v0.1 baseline is defined as forced direct export of all wind, the reported uplift can include value from avoiding negative-price export through curtailment as well as value from battery shifting. It is therefore **not a pure battery incremental-revenue estimate**.

The sample intentionally includes negative, low, and high price periods so the storage decision is visible. During lower-value hours, the optimizer can charge or curtail instead of exporting; during higher-value hours it can discharge previously stored energy.

## Mathematical formulation

For every hour `t`:

```text
wind_available[t]
  = wind_to_grid[t] + battery_charge[t] + curtailment[t]

grid_export[t]
  = wind_to_grid[t] + battery_discharge[t]

soc[t]
  = soc[t-1]
  + charge_efficiency * battery_charge[t]
  - battery_discharge[t] / discharge_efficiency
```

The objective maximizes:

```text
sum(price[t] * grid_export[t])
- throughput_cost * sum(charge[t] + discharge[t])
```

Version 0.1 allows the battery to charge from wind only. Grid-to-battery arbitrage is deliberately left for a later market-focused case study.

## Project structure

```text
hybrid-energy-optimizer/
├── src/energy_hub/
│   ├── assets/
│   ├── data/
│   ├── economics/
│   ├── optimization/
│   ├── cli.py
│   ├── config.py
│   └── run.py
├── dashboard/app.py
├── configs/base.yaml
├── data/sample/sample_24h.csv
├── case_studies/01_wind_battery_dispatch/
├── tests/
├── docs/superpowers/
├── .github/workflows/tests.yml
├── Dockerfile
└── pyproject.toml
```

## Testing

Run the test suite:

```bash
pytest -q
```

Run linting:

```bash
ruff check .
```

The tests cover:

- malformed, missing, duplicate, non-hourly, and negative-wind inputs,
- negative electricity prices,
- invalid battery parameters,
- wind-energy balance,
- charge/discharge and SOC limits,
- charge/discharge efficiencies,
- terminal SOC,
- unavailable solver requests,
- zero-wind KPI behavior,
- CLI output generation,
- and presentation-layer isolation from the core package.

GitHub Actions installs the project on Python 3.11, runs Ruff and Pytest, and executes the included sample case with HiGHS.

## Docker

Build:

```bash
docker build -t hybrid-energy-optimizer:0.1 .
```

Run the included case:

```bash
docker run --rm hybrid-energy-optimizer:0.1 \
  energy-hub run --config configs/base.yaml --solver highs
```

## Roadmap

The v0.1 architecture is intentionally small. Planned extensions can be developed as independent case studies on top of the same core platform:

1. Energinet API ingestion and PostgreSQL data pipeline
2. Wind-power forecasting and forecast-error economics
3. BESS sizing, degradation, NPV, IRR, and scenario analysis
4. Day-ahead / intraday market backtesting and PnL
5. Electrolyzer and hydrogen-production optimization
6. Waste-heat / district-heating integration
7. SCADA and renewable-asset performance analytics
8. Grid constraints and optimal power flow
9. Rolling-horizon and stochastic optimization
10. Cloud deployment and API service layer

## Case studies

The first case study is documented in:

[`case_studies/01_wind_battery_dispatch/README.md`](case_studies/01_wind_battery_dispatch/README.md)

Future studies should reuse the core package rather than duplicate asset or optimization logic.

## Contributing

Issues and pull requests are welcome once the repository is public. Keep new functionality modular, add tests for new behavior, and preserve the separation between core calculations and presentation code.

## License

MIT License. See [`LICENSE`](LICENSE).
