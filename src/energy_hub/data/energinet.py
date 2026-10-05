"""Energinet Energi Data Service ingestion for historical market backtests."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from energy_hub.data.wind_capacity import (
    aggregate_dk1_onshore_wind_capacity,
    normalize_capacity_records,
    scale_dk1_onshore_wind_to_farm,
)

DAY_AHEAD_CUTOFF = date(2025, 10, 1)
BASE_URL = "https://api.energidataservice.dk/dataset"

_PRICE_COLUMNS = {
    "Elspotprices": ("HourUTC", "SpotPriceEUR"),
    "DayAheadPrices": ("TimeUTC", "DayAheadPriceEUR"),
}
_WIND_COLUMNS = [
    "OffshoreWindGe100MW_MWh",
    "OffshoreWindLt100MW_MWh",
    "OnshoreWindGe50kW_MWh",
    "OnshoreWindLt50kW_MWh",
]
_ONSHORE_WIND_COLUMNS = ["OnshoreWindGe50kW_MWh", "OnshoreWindLt50kW_MWh"]


def price_datasets_for_period(start: date, end: date) -> list[str]:
    """Return the Energinet price datasets needed for an end-exclusive period."""
    if start >= end:
        raise ValueError("start must be before end")
    if end <= DAY_AHEAD_CUTOFF:
        return ["Elspotprices"]
    if start >= DAY_AHEAD_CUTOFF:
        return ["DayAheadPrices"]
    return ["Elspotprices", "DayAheadPrices"]


def _utc_naive(values: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values, utc=True, errors="raise")
    return timestamps.dt.tz_convert(None)


def _first_day_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _trim_utc_period(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    utc_start = pd.Timestamp(start.isoformat())
    utc_end = pd.Timestamp(end.isoformat())
    return frame.loc[
        (frame["timestamp"] >= utc_start) & (frame["timestamp"] < utc_end)
    ].reset_index(drop=True)


def normalize_price_records(records: list[dict[str, Any]], dataset: str) -> pd.DataFrame:
    """Normalize legacy hourly or current 15-minute day-ahead prices to hourly EUR/MWh."""
    if dataset not in _PRICE_COLUMNS:
        raise ValueError(f"unsupported price dataset: {dataset}")
    timestamp_column, price_column = _PRICE_COLUMNS[dataset]
    if not records:
        return pd.DataFrame(columns=["timestamp", "price_eur_mwh"])

    raw = pd.DataFrame(records)
    missing = {timestamp_column, price_column} - set(raw.columns)
    if missing:
        raise ValueError(f"price records missing required columns: {sorted(missing)}")

    normalized = pd.DataFrame(
        {
            "timestamp": _utc_naive(raw[timestamp_column]),
            "price_eur_mwh": pd.to_numeric(raw[price_column], errors="raise"),
        }
    )
    if dataset == "DayAheadPrices":
        if normalized["timestamp"].duplicated().any():
            raise ValueError("DayAheadPrices contains duplicate 15-minute timestamps")
        normalized["hour"] = normalized["timestamp"].dt.floor("h")
        grouped = normalized.groupby("hour", sort=True)
        for hour, group in grouped:
            offsets = sorted((group["timestamp"] - hour).dt.total_seconds().astype(int).tolist())
            if offsets != [0, 900, 1800, 2700]:
                raise ValueError(
                    "DayAheadPrices requires four 15-minute prices per hour; "
                    f"incomplete hour: {hour}"
                )
        normalized = grouped["price_eur_mwh"].mean().rename_axis("timestamp").reset_index()

    return (
        normalized[["timestamp", "price_eur_mwh"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def normalize_wind_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize aggregate and onshore settled wind production to hourly series."""
    columns = ["timestamp", "dk1_wind_mwh", "dk1_onshore_wind_mwh"]
    if not records:
        return pd.DataFrame(columns=columns)
    raw = pd.DataFrame(records)
    missing = {"HourUTC", *_WIND_COLUMNS} - set(raw.columns)
    if missing:
        raise ValueError(f"wind records missing required columns: {sorted(missing)}")

    numeric = raw[_WIND_COLUMNS].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    result = pd.DataFrame(
        {
            "timestamp": _utc_naive(raw["HourUTC"]),
            "dk1_wind_mwh": numeric.sum(axis=1),
            "dk1_onshore_wind_mwh": numeric[_ONSHORE_WIND_COLUMNS].sum(axis=1),
        }
    )
    return result.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def build_hourly_inputs(
    prices: pd.DataFrame,
    wind: pd.DataFrame,
    wind_share: float,
) -> pd.DataFrame:
    """Merge real DK prices and aggregate wind into the optimizer's hourly input schema.

    ``wind_share`` is a transparent scenario assumption: 0.05 represents a hypothetical
    portfolio whose hourly generation is 5% of the settled aggregate wind generation in
    the selected Danish bidding zone. It is not a claim about a specific physical wind farm.
    """
    if not 0.0 < wind_share <= 1.0:
        raise ValueError("wind_share must be greater than 0 and no greater than 1")

    merged = prices.merge(wind, on="timestamp", how="inner", validate="one_to_one")
    if merged.empty:
        raise ValueError("price and wind datasets have no overlapping hourly timestamps")

    result = merged[["timestamp", "dk1_wind_mwh", "price_eur_mwh"]].copy()
    result["wind_mwh"] = result.pop("dk1_wind_mwh") * float(wind_share)
    return result[["timestamp", "wind_mwh", "price_eur_mwh"]].sort_values(
        "timestamp"
    ).reset_index(drop=True)


class EnerginetClient:
    """Small HTTP client for the official Energi Data Service dataset API."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.session = session or self._build_session()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def fetch_dataset(
        self,
        dataset: str,
        *,
        start: date,
        end: date,
        price_area: str | None,
        columns: list[str],
        sort: str,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "columns": ",".join(columns),
            "sort": sort,
            "limit": 0,
        }
        if price_area is not None:
            params["filter"] = json.dumps(
                {"PriceArea": [price_area]}, separators=(",", ":")
            )
        response = self.session.get(
            f"{BASE_URL}/{dataset}",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("records")
        if not isinstance(records, list):
            raise RuntimeError(f"Energinet dataset '{dataset}' returned an invalid response")
        return records

    def fetch_hourly_prices(self, start: date, end: date, price_area: str) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for dataset in price_datasets_for_period(start, end):
            if dataset == "Elspotprices":
                part_start = start
                part_end = min(end, DAY_AHEAD_CUTOFF)
                columns = ["HourUTC", "PriceArea", "SpotPriceEUR"]
                sort = "HourUTC asc"
            else:
                part_start = max(start, DAY_AHEAD_CUTOFF)
                part_end = end
                columns = ["TimeUTC", "PriceArea", "DayAheadPriceEUR"]
                sort = "TimeUTC asc"
            if part_start >= part_end:
                continue
            records = self.fetch_dataset(
                dataset,
                start=part_start,
                end=part_end,
                price_area=price_area,
                columns=columns,
                sort=sort,
            )
            frames.append(normalize_price_records(records, dataset))

        if not frames:
            return pd.DataFrame(columns=["timestamp", "price_eur_mwh"])
        return (
            pd.concat(frames, ignore_index=True)
            .sort_values("timestamp")
            .drop_duplicates("timestamp")
            .reset_index(drop=True)
        )

    def fetch_hourly_wind(self, start: date, end: date, price_area: str) -> pd.DataFrame:
        columns = ["HourUTC", "PriceArea", *_WIND_COLUMNS]
        records = self.fetch_dataset(
            "ProductionConsumptionSettlement",
            start=start,
            end=end,
            price_area=price_area,
            columns=columns,
            sort="HourUTC asc",
        )
        return normalize_wind_records(records)

    def fetch_monthly_wind_capacity(self, start: date, end: date) -> pd.DataFrame:
        """Fetch monthly DK1 onshore installed capacity from municipality records."""
        records = self.fetch_dataset(
            "CapacityPerMunicipality",
            start=start,
            end=end,
            price_area=None,
            columns=["Month", "MunicipalityNo", "OnshoreWindCapacity"],
            sort="Month asc",
        )
        return aggregate_dk1_onshore_wind_capacity(normalize_capacity_records(records))

    def fetch_hourly_inputs(
        self,
        start: date,
        end: date,
        price_area: str,
        wind_share: float,
    ) -> pd.DataFrame:
        """Fetch enough Danish-local data to return exact end-exclusive UTC calendar days."""
        if start >= end:
            raise ValueError("start must be before end")

        # Energi Data Service interprets bare start/end dates in Danish local time.
        # Pad the API request, then trim after converting the records' explicit UTC fields.
        api_start = start - timedelta(days=1)
        api_end = end + timedelta(days=1)
        prices = self.fetch_hourly_prices(api_start, api_end, price_area)
        wind = self.fetch_hourly_wind(api_start, api_end, price_area)
        inputs = build_hourly_inputs(prices, wind, wind_share)

        trimmed = _trim_utc_period(inputs, start, end)
        if trimmed.empty:
            raise ValueError("Energinet data contains no records in the requested UTC period")
        return trimmed

    def fetch_hourly_inputs_for_capacity(
        self,
        start: date,
        end: date,
        price_area: str,
        wind_capacity_mw: float,
    ) -> pd.DataFrame:
        """Return exact UTC-day inputs for a hypothetical DK1 onshore wind farm."""
        if start >= end:
            raise ValueError("start must be before end")
        if price_area != "DK1":
            raise ValueError("capacity-based wind normalization currently supports DK1 only")

        api_start = start - timedelta(days=1)
        api_end = end + timedelta(days=1)
        prices = self.fetch_hourly_prices(api_start, api_end, price_area)
        wind = self.fetch_hourly_wind(api_start, api_end, price_area)

        requested_prices = _trim_utc_period(prices, start, end)
        requested_wind = _trim_utc_period(wind, start, end)
        if requested_prices.empty or requested_wind.empty:
            raise ValueError("Energinet data contains no records in the requested UTC period")

        capacity_start = date(start.year, start.month, 1)
        last_requested_day = end - timedelta(days=1)
        capacity_end = _first_day_of_next_month(last_requested_day)
        capacity = self.fetch_monthly_wind_capacity(capacity_start, capacity_end)
        scaled_wind = scale_dk1_onshore_wind_to_farm(
            requested_wind, capacity, wind_capacity_mw
        )

        inputs = requested_prices.merge(
            scaled_wind, on="timestamp", how="inner", validate="one_to_one"
        )
        if inputs.empty:
            raise ValueError("price and scaled wind datasets have no overlapping hourly timestamps")
        return inputs[["timestamp", "wind_mwh", "price_eur_mwh"]].sort_values(
            "timestamp"
        ).reset_index(drop=True)
