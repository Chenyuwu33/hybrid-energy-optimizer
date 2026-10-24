# Case Study 01 — Wind + Battery Dispatch

## Operational question

A wind-asset analyst has hourly wind availability and electricity prices. Without storage, all available wind is sold directly to the grid. With a battery, some wind can instead be shifted from lower-value hours to higher-value hours.

The question is:

> How should the battery be operated over the horizon, and how much does that change the realized operating value relative to direct wind export?

## Baseline

The baseline uses no storage optimization:

```text
baseline_grid_export[t] = wind_available[t]
```

Its revenue is the hourly sum of wind generation multiplied by electricity price.

## Optimized case

The optimized case chooses:

- wind-to-grid energy,
- battery charging,
- battery discharging,
- curtailment,
- and end-of-hour state of charge.

Charging is wind-origin only in v0.1. The model enforces physical battery limits and returns the same 24-hour horizon in a machine-readable dispatch table.

## Included assumptions

The sample configuration uses:

- 100 MWh battery energy capacity,
- 25 MW charge power,
- 25 MW discharge power,
- 95% charge efficiency,
- 95% discharge efficiency,
- 50 MWh initial SOC,
- 50 MWh terminal SOC,
- zero throughput cost in the reference run.

The input price/wind data are synthetic and were created to exercise negative-, low-, and high-price behavior. They do **not** represent a real Danish asset or a historical DK1 day.

## Reference KPIs

A reference execution with `--no-degradation` (the v0.1 assumption of free cycling) produced approximately:

```text
Baseline revenue   €65,977
Optimized revenue  €80,061
Revenue uplift     €14,084
Battery value      €12,567
Solver status      optimal
```

With the default degradation cost (€5/MWh throughput) the battery value falls to about €10,378 after €2,092 of wear.

The purpose of these numbers is to verify model behavior and reproducibility, not to estimate commercial BESS returns.
The sell-all baseline exports all wind, so the revenue uplift includes avoided negative-price export through curtailment in addition to storage shifting. `kpis.json` therefore also reports `baseline_curtail_negative_revenue_eur` (a wind-only asset that curtails at negative prices) and `battery_incremental_value_eur` (optimized revenue minus that baseline), which isolates the value created by the battery itself. In this case about €1,500 of the €14,084 uplift comes from curtailment alone.

## Reproduce

From the repository root:

```bash
python -m pip install -e ".[dev]"
energy-hub run --config configs/base.yaml --solver highs --no-degradation
```

Inspect:

```text
outputs/dispatch.csv
outputs/kpis.json
```

Or launch:

```bash
streamlit run dashboard/app.py
```

## What to examine

A useful review of the dispatch should ask:

1. Is wind balance closed every hour?
2. Does SOC remain inside its limits?
3. Is low-price wind more likely to charge the battery or be curtailed?
4. Is stored energy released in higher-price periods?
5. Does the terminal SOC target prevent the optimizer from creating artificial end-of-horizon value?
6. How much of the revenue uplift remains after adding a battery throughput/degradation cost?

These questions form the bridge from the v0.1 demonstration to later studies on degradation, sizing, forecasting, market backtesting, and investment economics.
