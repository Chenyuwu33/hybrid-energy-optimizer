# Hybrid Energy Optimizer

A Python decision-support platform for a practical renewable-energy problem:

> Given wind generation, electricity prices, and battery constraints, when should a renewable asset sell electricity, charge, discharge, or curtail generation?

The repository is designed as a reusable foundation for energy analytics and optimization rather than a one-off notebook.

- **v0.1:** synthetic 24-hour wind + BESS dispatch optimization
- **v0.2:** historical DK1 data ingestion from Energinet and daily backtesting

> **Important:** this is an educational and decision-support prototype. It is not operational, trading, investment, or safety advice for any real asset.

## What the project does

For every hourly time step, the optimizer decides how available wind energy is split between:

- direct grid export,
- battery charging,
- curtailment,
- and later battery discharge.

It respects battery power, energy, efficiency, SOC, terminal-SOC, and optional throughput-cost constraints.

The project now supports two workflows:

1. **Single-case optimization** from a local hourly CSV.
2. **Historical DK1 backtesting** using official Energinet Energi Data Service data.

## Architecture

```text
                 Data sources
            +---------+----------+
            |                    |
      local CSV             Energinet API
            |                    |
            |             price + wind data
            |                    |
            +----------+---------+
                       |
                       v
              hourly input schema
           timestamp / wind / price
                       |
                       v
               Battery parameters
                       |
                       v
             Dispatch optimization
             Pyomo + HiGHS/Gurobi
          SciPy-HiGHS fallback path
                       |
               +-------+--------+
               |                |
               v                v
           one-day run     daily backtest
               |                |
               +-------+--------+
                       |
                       v
               Economic KPIs
                       |
                 +-----+-----+
                 |           |
                 v           v
                CLI      Streamlit
```

Core calculations live under `src/energy_hub/`. Presentation code does not contain optimization equations.

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

### 2. Run the synthetic v0.1 case

```bash
energy-hub run --config configs/base.yaml --solver highs
```

Outputs:

```text
outputs/dispatch.csv
outputs/kpis.json
```

### 3. Run a historical DK1 backtest

The command below downloads official historical market and settlement data from Energinet and replays seven complete UTC days:

```bash
energy-hub backtest \
  --config configs/base.yaml \
  --start 2026-09-01 \
  --end 2026-09-08 \
  --area DK1 \
  --wind-share 0.05 \
  --solver highs
```

On Windows Command Prompt, put the command on one line or replace the line-continuation syntax as appropriate.

Outputs:

```text
outputs/backtest_inputs.csv
outputs/backtest_daily.csv
outputs/backtest_summary.json
```

The summary separates three strategies:

- **Sell-all baseline:** export all available wind, including during negative prices.
- **Curtail-negative baseline:** export wind when the hourly price is non-negative and curtail at negative prices.
- **Optimized:** coordinate wind, curtailment, and the battery using the dispatch optimizer.

This separation makes `battery_incremental_vs_curtail_eur` more meaningful than the original v0.1 uplift, because it does not credit the battery for the simple decision to avoid negative-price export.

## Real-data methodology and limitations

The historical workflow uses the official [Energinet Energi Data Service](https://www.energidataservice.dk/guides/api-guides).

### Electricity prices

Energinet's legacy `Elspotprices` series stopped updating after September 2025. Current `DayAheadPrices` data use a 15-minute market time unit. Because the current optimizer is still hourly, v0.2 averages the four 15-minute day-ahead prices within each UTC hour before optimization.

### Wind production

The project uses settled wind-production fields from `ProductionConsumptionSettlement` and sums the available onshore/offshore wind categories for DK1.

The current model **does not claim that DK1 aggregate production represents a specific wind farm**. The `--wind-share` parameter is an explicit scenario assumption. For example:

```text
--wind-share 0.05
```

means:

> model a hypothetical portfolio whose hourly output profile is 5% of the settled aggregate DK1 wind-production profile.

A future asset-specific study should replace this scaling assumption with real SCADA, metered production, or a site-specific wind/power model.

### Historical replay, not live trading

The daily backtest is a **perfect-information historical benchmark**: each day's realized historical prices and wind values are known to the optimizer. It therefore measures the value available under perfect foresight and should not be presented as achievable live-trading performance.

Future versions will introduce forecast errors and rolling-horizon decisions.

### Time handling

Energi Data Service interprets bare API `start`/`end` values in Danish local time. v0.2 pads the requested API range, converts the datasets' UTC timestamp fields, and then trims the merged data to exact end-exclusive UTC calendar days before backtesting.

## Synthetic reference result

A reference run of the included synthetic v0.1 case produced approximately:

| KPI | Value |
|---|---:|
| Baseline revenue | €65,977 |
| Optimized revenue | €80,061 |
| Revenue uplift | €14,084 |
| Solver status | optimal |

These figures are only a reproducibility check for the synthetic sample and are not an estimate of commercial battery returns.

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

The battery can currently charge from wind only. Grid-to-battery arbitrage is deliberately left for a later market-focused extension.

## Dashboard

Launch the interactive synthetic-case dashboard:

```bash
streamlit run dashboard/app.py
```

The v0.2 historical workflow is currently CLI-first. A later dashboard update will add date-range selection and historical backtest visualization after the data/backend behavior is stable.

## Optional Gurobi

If you have a valid Gurobi installation/license:

```bash
python -m pip install -e ".[gurobi]"
energy-hub run --config configs/base.yaml --solver gurobi
```

## Project structure

```text
hybrid-energy-optimizer/
├── src/energy_hub/
│   ├── assets/
│   ├── backtesting/
│   │   └── runner.py
│   ├── data/
│   │   ├── energinet.py
│   │   └── io.py
│   ├── economics/
│   ├── optimization/
│   ├── cli.py
│   ├── config.py
│   └── run.py
├── dashboard/app.py
├── configs/base.yaml
├── data/sample/sample_24h.csv
├── case_studies/
│   ├── 01_wind_battery_dispatch/
│   └── 02_dk1_historical_backtest/
├── tests/
├── .github/workflows/tests.yml
├── Dockerfile
└── pyproject.toml
```

## Testing

Run:

```bash
pytest -q
ruff check .
```

The automated suite covers, among other things:

- input-data validation,
- battery parameter validation,
- energy balance and SOC constraints,
- solver behavior,
- legacy hourly and current 15-minute Energinet price normalization,
- DK1 wind-category aggregation,
- Danish-local API range to UTC-day trimming,
- scenario wind-share scaling,
- daily historical replay,
- improved economic baselines,
- CLI file generation,
- and presentation-layer isolation.

GitHub Actions installs the project on Python 3.11, runs Ruff and Pytest, and runs the original deterministic sample case. CI does not call the live Energinet API, so temporary external API/network outages do not make the repository test suite flaky.

## Docker

Build:

```bash
docker build -t hybrid-energy-optimizer:0.2 .
```

Run the included synthetic case:

```bash
docker run --rm hybrid-energy-optimizer:0.2 \
  energy-hub run --config configs/base.yaml --solver highs
```

A live Energinet backtest also requires network access from the container.

## Roadmap

Completed foundation:

- [x] Wind + BESS dispatch optimizer
- [x] CLI / Streamlit / tests / CI / Docker
- [x] Energinet historical price and settlement-data ingestion
- [x] Historical daily backtesting with multiple baselines

Next candidates:

1. Persist normalized data in PostgreSQL and cache API responses
2. Add battery degradation economics and BESS sizing studies
3. Add historical backtest views to Streamlit
4. Add wind- and price-forecast models and quantify forecast economic value
5. Add rolling-horizon optimization under forecast error
6. Add day-ahead / intraday / balancing-market extensions
7. Add electrolyzer and hydrogen-production optimization
8. Add SCADA and renewable-asset performance analytics
9. Add grid constraints and optimal power flow
10. Add cloud deployment and API service layer

## Case studies

- [`01_wind_battery_dispatch`](case_studies/01_wind_battery_dispatch/README.md) — synthetic 24-hour dispatch foundation
- [`02_dk1_historical_backtest`](case_studies/02_dk1_historical_backtest/README.md) — historical DK1 data and improved baseline methodology

Future studies should reuse the core package rather than duplicate asset or optimization logic.

## Contributing

Issues and pull requests are welcome. Keep new functionality modular, add tests for new behavior, and preserve the separation between data ingestion, optimization, economics, and presentation code.

## License

MIT License. See [`LICENSE`](LICENSE).
