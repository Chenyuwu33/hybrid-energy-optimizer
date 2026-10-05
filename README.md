# Hybrid Energy Optimizer

A Python decision-support platform for a practical renewable-energy problem:

> Given wind generation, electricity prices, and battery constraints, when should a renewable asset sell electricity, charge, discharge, or curtail generation?

The repository is designed as a reusable foundation for energy analytics and optimization rather than a one-off notebook.

- **v0.1:** synthetic 24-hour wind + BESS dispatch optimization
- **v0.2:** historical DK1 data ingestion from Energinet and daily backtesting
- **v0.2.1:** interactive historical Streamlit dashboard with wind-farm and BESS sizing inputs

> **Important:** this is an educational and decision-support prototype. It is not operational, trading, investment, or safety advice for any real asset.

## What the project does

For every hourly time step, the optimizer decides how available wind energy is split between:

- direct grid export,
- battery charging,
- curtailment,
- and later battery discharge.

It respects battery power, energy, efficiency, SOC, terminal-SOC, and optional throughput-cost constraints.

The project supports three user workflows:

1. **Single-case optimization** from a local hourly CSV.
2. **Historical DK1 CLI backtesting** using official Energinet data and the v0.2 `wind_share` scenario assumption.
3. **Interactive historical DK1 dashboard backtesting** using a hypothetical onshore wind-farm rated capacity and user-defined BESS size.

## Architecture

```text
                 Data sources
            +---------+----------+
            |                    |
      local CSV             Energinet API
            |             price / wind /
            |           installed capacity
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

Core calculations live under `src/energy_hub/`. Streamlit collects inputs and displays results; it does not duplicate optimization equations.

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

### 2. Run the synthetic reference case

```bash
energy-hub run --config configs/base.yaml --solver highs
```

Outputs:

```text
outputs/dispatch.csv
outputs/kpis.json
```

### 3. Run the v0.2-compatible historical CLI backtest

The command below replays seven complete UTC days using a hypothetical portfolio equal to 5% of aggregate settled DK1 wind production:

```bash
energy-hub backtest \
  --config configs/base.yaml \
  --start 2026-09-01 \
  --end 2026-09-08 \
  --area DK1 \
  --wind-share 0.05 \
  --solver highs
```

On Windows Command Prompt, put the command on one line or use CMD's `^` line-continuation syntax rather than `\`.

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

`battery_incremental_vs_curtail_eur` isolates modeled battery value from the simpler decision to avoid negative-price export.

### 4. Launch the v0.2.1 dashboard

```bash
streamlit run dashboard/app.py
```

The dashboard contains two tabs:

#### Sample Dispatch

Preserves the transparent v0.1 synthetic case. Users can change BESS energy, charge/discharge power, initial/terminal SOC, and solver, then inspect revenue, cycling, dispatch, and SOC.

#### Historical DK1 Backtest

Users can choose:

- start and end date (`end` is exclusive),
- hypothetical **onshore** wind-farm capacity in MW,
- BESS energy capacity in MWh,
- charge and discharge power in MW,
- initial and terminal SOC in percent,
- HiGHS or Gurobi.

The dashboard reports:

- days backtested,
- total modeled wind energy,
- sell-all baseline revenue,
- curtail-negative baseline revenue,
- optimized revenue,
- battery incremental value,
- total uplift versus sell-all,
- equivalent full cycles,
- historical wind/price chart,
- daily battery-value chart,
- daily revenue comparison,
- daily cycling,
- and the daily result table.

## Real-data methodology and limitations

The historical workflows use the official Energinet Energi Data Service.

### Electricity prices

Legacy `Elspotprices` data are used before October 2025. From October 2025, `DayAheadPrices` use a 15-minute market time unit. Because the optimizer is currently hourly, the four complete quarter-hour prices within each UTC hour are averaged. Missing or duplicate quarter-hour groups are rejected rather than silently averaged.

### Wind production: two explicit scenario paths

The project deliberately keeps two different historical scaling assumptions separate.

**CLI `--wind-share` path:**

The v0.2-compatible CLI sums the available settled onshore and offshore DK1 wind-production categories and applies an explicit portfolio share. For example, `--wind-share 0.05` means a hypothetical portfolio whose hourly production is 5% of aggregate settled DK1 wind production. It is not a specific physical wind farm.

**Dashboard wind-capacity path:**

v0.2.1 gives users the more intuitive input `wind_capacity_mw`. This pathway uses:

1. settled **DK1 onshore** hourly wind production,
2. monthly municipality-level onshore installed wind capacity,
3. an explicit West Denmark/DK1 municipality mapping,
4. a regional hourly onshore capacity factor,
5. scaling of that regional profile to the selected hypothetical wind-farm MW.

For hour `t` in month `m`:

```text
regional_cf[t]
  = DK1_onshore_generation_mwh[t]
  / DK1_onshore_installed_capacity_mw[m]

hypothetical_wind_mwh[t]
  = regional_cf[t] * wind_capacity_mw
```

This is a **regional-profile approximation**, not SCADA data from an individual wind farm. Regional aggregation smooths spatial variability and should not be interpreted as a site-specific production trace.

The capacity-based v0.2.1 path is intentionally onshore-only. Offshore capacity records are not forced into a municipality-based DK1 mapping when their location encoding is ambiguous. A future offshore study should use an explicit offshore asset/price-area mapping.

### Historical replay, not live trading

The daily backtest is a **perfect-information historical benchmark**: each day's realized historical prices and wind values are known to the optimizer. It measures an upper-bound-like operational value under the current assumptions and should not be presented as achievable live-trading PnL.

### Current economic and grid limitations

v0.2.1 still does not model several effects needed for an investment-grade study, including:

- battery degradation economics beyond the configurable generic throughput-cost hook,
- grid-connection export limits,
- forecast error and rolling-horizon operation,
- imbalance settlement,
- intraday/balancing/reserve-market participation,
- site-specific SCADA or wake/power-curve modeling.

These limitations are also shown inside the historical dashboard.

### Time handling

Energi Data Service interprets bare API `start`/`end` values in Danish local time. The client pads API requests, normalizes explicit UTC timestamp fields, and trims the data to exact end-exclusive UTC calendar days before backtesting. The daily runner requires exactly 24 hourly records per UTC day.

## Synthetic reference result

A reference run of the included synthetic case produced approximately:

| KPI | Value |
|---|---:|
| Baseline revenue | €65,977 |
| Optimized revenue | €80,061 |
| Revenue uplift | €14,084 |
| Solver status | optimal |

These figures are only a reproducibility check for the synthetic sample and are not a commercial-return estimate.

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

## Project structure

```text
hybrid-energy-optimizer/
├── src/energy_hub/
│   ├── assets/
│   ├── backtesting/
│   │   ├── runner.py
│   │   └── service.py
│   ├── data/
│   │   ├── energinet.py
│   │   ├── io.py
│   │   └── wind_capacity.py
│   ├── economics/
│   ├── optimization/
│   ├── presentation/
│   │   └── charts.py
│   ├── cli.py
│   ├── config.py
│   └── run.py
├── dashboard/
│   ├── app.py
│   ├── sample_dispatch.py
│   └── historical_backtest.py
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
ruff check .
pytest -q
python -m compileall -q src dashboard
energy-hub run --config configs/base.yaml --solver highs
```

The automated suite covers, among other things:

- input-data validation,
- battery parameter validation,
- energy balance and SOC constraints,
- solver behavior,
- legacy hourly and current 15-minute price normalization,
- rejection of incomplete quarter-hour price groups,
- aggregate and onshore DK1 wind normalization,
- Danish-local API range to UTC-day trimming,
- legacy wind-share scaling,
- municipality-based DK1 onshore installed-capacity aggregation,
- regional capacity-factor and hypothetical wind-farm scaling,
- missing-capacity and impossible-capacity-factor rejection,
- historical dashboard request validation and SOC conversion,
- daily replay and economic baselines,
- pure chart-helper output,
- CLI file generation,
- and package/project version synchronization.

GitHub Actions installs the project on Python 3.11, runs Ruff and Pytest, and runs the deterministic synthetic sample. CI deliberately does not call the live Energinet API, so temporary external API/network outages do not make the test suite flaky.

## Docker

Build:

```bash
docker build -t hybrid-energy-optimizer:0.2.1 .
```

Run the included synthetic case:

```bash
docker run --rm hybrid-energy-optimizer:0.2.1 \
  energy-hub run --config configs/base.yaml --solver highs
```

A live Energinet backtest requires network access from the container.

## Roadmap

Completed foundation:

- [x] Wind + BESS dispatch optimizer
- [x] CLI / Streamlit / tests / CI / Docker
- [x] Energinet historical price and settlement-data ingestion
- [x] Historical daily backtesting with multiple baselines
- [x] Interactive historical DK1 dashboard with capacity-based onshore profile scaling

Next priorities:

1. Add battery degradation economics and BESS sizing sensitivity
2. Add a grid-connection export limit
3. Add hourly historical dispatch export and deeper diagnostic views
4. Persist/cache normalized market data
5. Add wind- and price-forecast models and quantify forecast economic value
6. Add rolling-horizon optimization under forecast error
7. Add day-ahead / intraday / balancing-market extensions
8. Add electrolyzer and hydrogen-production optimization
9. Add grid constraints, ED/DC-OPF, and congestion analysis
10. Add cloud deployment and API service layer

## Case studies

- [`01_wind_battery_dispatch`](case_studies/01_wind_battery_dispatch/README.md) — synthetic 24-hour dispatch foundation
- [`02_dk1_historical_backtest`](case_studies/02_dk1_historical_backtest/README.md) — historical DK1 data and improved baseline methodology

Future studies should reuse the core package rather than duplicate asset or optimization logic.

## Contributing

Issues and pull requests are welcome. Keep new functionality modular, add tests for new behavior, and preserve the separation between data ingestion, optimization, economics, and presentation code.

## License

MIT License. See [`LICENSE`](LICENSE).
