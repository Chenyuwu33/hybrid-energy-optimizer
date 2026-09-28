# Case Study 02 — DK1 Historical Wind + BESS Backtest

## Question

How would a hypothetical wind-plus-battery portfolio have behaved across historical DK1 market conditions, and how much value is attributable to the battery rather than simply avoiding negative-price export?

## Why this case exists

The original v0.1 sample proves that the optimization model behaves correctly on a controlled synthetic day. It does not show how the model behaves against real Danish market variability.

This case introduces official historical Energinet data and a clearer benchmark hierarchy.

## Data

The workflow downloads data from Energinet Energi Data Service:

- historical DK1 electricity prices,
- settled DK1 onshore/offshore wind production,
- explicit UTC timestamp fields.

Price-data handling changes across the September/October 2025 market transition:

- legacy `Elspotprices` is already hourly,
- current `DayAheadPrices` is 15-minute and is averaged to hourly resolution for the v0.2 optimizer.

Settled wind categories are summed to an aggregate DK1 profile.

## Portfolio assumption

This case deliberately does not pretend that aggregate DK1 wind is a specific wind farm.

The user supplies a scenario parameter:

```text
wind_share = hypothetical portfolio generation / aggregate DK1 wind generation
```

For example, `wind_share = 0.05` applies 5% of the observed DK1 wind-production profile to the modeled portfolio.

This is useful for software and methodology development, but a real asset study should replace this assumption with measured SCADA/meter data or a site-specific production model.

## Three strategies compared

### A. Sell all wind

```text
wind -> grid
```

All modeled wind is exported regardless of price, including negative-price hours.

### B. Curtail at negative prices

```text
if price >= 0: wind -> grid
if price < 0:  wind -> curtailment
```

This is a stronger no-battery baseline because it captures the simple value of not exporting during negative-price hours.

### C. Optimize wind + battery

The LP decides hourly:

```text
wind -> grid
wind -> battery
wind -> curtailment
battery -> grid
```

subject to the configured BESS power, energy, efficiency, SOC, terminal-SOC, and throughput-cost assumptions.

## Main KPI distinction

The most important v0.2 metric is:

```text
battery_incremental_vs_curtail_eur
```

calculated as:

```text
optimized revenue - curtail-negative baseline revenue
```

This prevents the battery from receiving credit for a decision that could be made without storage.

## Historical replay semantics

Each complete UTC day is optimized independently. The model uses realized historical prices and wind values for that day, so the result is a **perfect-foresight benchmark**.

It answers:

> How much dispatch value was theoretically available with perfect information?

It does **not** answer:

> How much money would a live trader definitely have earned?

Forecasting error, imbalance settlement, market access, bidding constraints, and rolling-horizon operation are future extensions.

## Run the case

Example:

```bash
energy-hub backtest \
  --config configs/base.yaml \
  --start 2026-09-01 \
  --end 2026-09-08 \
  --area DK1 \
  --wind-share 0.05 \
  --solver highs
```

The end date is exclusive.

Generated outputs:

```text
outputs/backtest_inputs.csv
outputs/backtest_daily.csv
outputs/backtest_summary.json
```

## What to inspect

Useful questions for analysis include:

1. How often did negative prices make the sell-all baseline worse than simple curtailment?
2. How much additional value did storage create after that baseline correction?
3. How many equivalent full cycles were required to create that value?
4. How sensitive are the results to battery energy capacity, power rating, efficiency, and throughput/degradation cost?
5. Does battery value come from a few extreme-price days or from persistent daily spreads?

These questions are the bridge from a software demo toward BESS investment and operating analysis.

## Next extensions

This case is designed to grow into several child studies:

- battery degradation cost and cycle economics,
- BESS sizing and NPV/IRR,
- forecast accuracy versus economic value,
- rolling-horizon dispatch,
- day-ahead versus intraday/balancing opportunities,
- and asset-specific SCADA replacement of the aggregate-wind scaling assumption.
