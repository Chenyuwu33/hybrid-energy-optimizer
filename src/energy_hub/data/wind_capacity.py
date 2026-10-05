"""DK1 onshore wind-capacity normalization for hypothetical farm profiles."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Danmarks Statistik municipality codes for Region Syddanmark, Region Midtjylland,
# and Region Nordjylland. These regions form West Denmark (DK1). Special/non-municipality
# records such as "1" are intentionally excluded.
DK1_MUNICIPALITY_CODES = frozenset(
    {
        "410",
        "420",
        "430",
        "440",
        "450",
        "461",
        "479",
        "480",
        "482",
        "492",
        "510",
        "530",
        "540",
        "550",
        "561",
        "563",
        "573",
        "575",
        "580",
        "607",
        "615",
        "621",
        "630",
        "657",
        "661",
        "665",
        "671",
        "706",
        "707",
        "710",
        "727",
        "730",
        "740",
        "741",
        "746",
        "751",
        "756",
        "760",
        "766",
        "773",
        "779",
        "787",
        "791",
        "810",
        "813",
        "820",
        "825",
        "840",
        "846",
        "849",
        "851",
        "860",
    }
)


def normalize_capacity_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize Energinet CapacityPerMunicipality records for onshore wind."""
    columns = ["month", "municipality_no", "onshore_wind_capacity_mw"]
    if not records:
        return pd.DataFrame(columns=columns)

    raw = pd.DataFrame(records)
    required = {"Month", "MunicipalityNo", "OnshoreWindCapacity"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"capacity records missing required columns: {sorted(missing)}")

    month = pd.to_datetime(raw["Month"], errors="raise").dt.to_period("M").dt.to_timestamp()
    result = pd.DataFrame(
        {
            "month": month,
            "municipality_no": raw["MunicipalityNo"].astype(str),
            "onshore_wind_capacity_mw": pd.to_numeric(
                raw["OnshoreWindCapacity"], errors="raise"
            ),
        }
    )
    if (result["onshore_wind_capacity_mw"] < 0).any():
        raise ValueError("onshore wind installed capacity cannot be negative")
    return result[columns].sort_values(["month", "municipality_no"]).reset_index(drop=True)


def aggregate_dk1_onshore_wind_capacity(capacity: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly onshore wind capacity for explicitly mapped DK1 municipalities."""
    required = {"month", "municipality_no", "onshore_wind_capacity_mw"}
    missing = required - set(capacity.columns)
    if missing:
        raise ValueError(f"capacity table missing required columns: {sorted(missing)}")

    in_dk1 = capacity["municipality_no"].astype(str).isin(DK1_MUNICIPALITY_CODES)
    selected = capacity.loc[in_dk1].copy()
    if selected.empty:
        return pd.DataFrame(columns=["month", "dk1_onshore_capacity_mw"])

    selected["month"] = pd.to_datetime(selected["month"], errors="raise")
    result = (
        selected.groupby("month", as_index=False, sort=True)["onshore_wind_capacity_mw"]
        .sum()
        .rename(columns={"onshore_wind_capacity_mw": "dk1_onshore_capacity_mw"})
    )
    return result


def scale_dk1_onshore_wind_to_farm(
    wind: pd.DataFrame,
    monthly_capacity: pd.DataFrame,
    wind_capacity_mw: float,
) -> pd.DataFrame:
    """Scale the DK1 onshore regional capacity-factor shape to a hypothetical wind farm."""
    if wind_capacity_mw <= 0:
        raise ValueError("wind_capacity_mw must be positive")

    wind_required = {"timestamp", "dk1_onshore_wind_mwh"}
    capacity_required = {"month", "dk1_onshore_capacity_mw"}
    missing_wind = wind_required - set(wind.columns)
    missing_capacity = capacity_required - set(monthly_capacity.columns)
    if missing_wind:
        raise ValueError(f"wind table missing required columns: {sorted(missing_wind)}")
    if missing_capacity:
        raise ValueError(f"capacity table missing required columns: {sorted(missing_capacity)}")

    hourly = wind[["timestamp", "dk1_onshore_wind_mwh"]].copy()
    hourly["timestamp"] = pd.to_datetime(hourly["timestamp"], errors="raise")
    hourly["month"] = hourly["timestamp"].dt.to_period("M").dt.to_timestamp()

    capacity = monthly_capacity[["month", "dk1_onshore_capacity_mw"]].copy()
    capacity["month"] = pd.to_datetime(capacity["month"], errors="raise")
    merged = hourly.merge(capacity, on="month", how="left", validate="many_to_one")

    if merged["dk1_onshore_capacity_mw"].isna().any():
        missing_mask = merged["dk1_onshore_capacity_mw"].isna()
        missing_months = sorted(merged.loc[missing_mask, "month"].unique())
        raise ValueError(f"missing DK1 installed capacity for month(s): {missing_months}")
    if (merged["dk1_onshore_capacity_mw"] <= 0).any():
        raise ValueError("DK1 installed capacity must be positive")

    regional_cf = merged["dk1_onshore_wind_mwh"] / merged["dk1_onshore_capacity_mw"]
    if (regional_cf < -1e-9).any() or (regional_cf > 1.0 + 1e-6).any():
        raise ValueError("regional wind capacity factor must be between 0 and 1")
    regional_cf = regional_cf.clip(lower=0.0, upper=1.0)

    return pd.DataFrame(
        {
            "timestamp": merged["timestamp"],
            "wind_mwh": regional_cf * float(wind_capacity_mw),
        }
    ).reset_index(drop=True)
