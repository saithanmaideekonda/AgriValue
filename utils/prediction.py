"""Dynamic market filters, model estimates, and observed market profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from utils.calculations import calculate_financials
from utils.data_processing import make_stability_data
from utils.model_training import MODEL_PATH, model_features


class PredictionError(RuntimeError):
    """Raised when a market price cannot be estimated safely."""


def load_model(path: Path | str = MODEL_PATH):
    model_path = Path(path)
    if not model_path.is_file():
        raise PredictionError("The trained model is missing. Run: python -m utils.model_training")
    try:
        return joblib.load(model_path)
    except Exception as exc:
        raise PredictionError(f"Could not load the saved model: {exc}") from exc


def _choices(series: pd.Series) -> list[str]:
    values = series.dropna().astype(str).str.strip()
    return sorted(values[values.ne("") & values.str.casefold().ne("unknown")].unique().tolist(), key=str.casefold)


def _filter(data: pd.DataFrame, **criteria: str | list[str]) -> pd.DataFrame:
    subset = data
    for column, value in criteria.items():
        if column not in subset:
            continue
        if isinstance(value, list):
            if value:
                subset = subset[subset[column].astype(str).isin(value)]
        elif value:
            subset = subset[subset[column].astype(str).eq(str(value))]
    return subset


def filtered_records(data: pd.DataFrame, **criteria: str | list[str]) -> pd.DataFrame:
    """Return a filtered copy using exact values from the loaded dataset."""
    return _filter(data, **criteria).copy()


def commodities_for_analysis(data: pd.DataFrame, state: str = "", district: str = "", market: str = "") -> list[str]:
    return _choices(_filter(data, State=state, District=district, Market=market)["Commodity"])


def states_for_analysis(data: pd.DataFrame, commodity: str = "") -> list[str]:
    return _choices(_filter(data, Commodity=commodity)["State"])


def districts_for_analysis(data: pd.DataFrame, commodity: str = "", state: str = "") -> list[str]:
    return _choices(_filter(data, Commodity=commodity, State=state)["District"])


def markets_for_analysis(
    data: pd.DataFrame, commodity: str = "", state: str = "", district: str = "",
    variety: str = "", grade: str = "",
) -> list[str]:
    subset = _filter(data, Commodity=commodity, State=state, District=district, Variety=variety, Grade=grade)
    return _choices(subset["Market"])


def varieties_for_analysis(
    data: pd.DataFrame, commodity: str = "", state: str = "", district: str = "",
    markets: list[str] | None = None, grade: str = "",
) -> list[str]:
    subset = _filter(data, Commodity=commodity, State=state, District=district, Market=markets or [], Grade=grade)
    return _choices(subset["Variety"]) if "Variety" in subset else []


def grades_for_analysis(
    data: pd.DataFrame, commodity: str = "", state: str = "", district: str = "",
    markets: list[str] | None = None, variety: str = "",
) -> list[str]:
    subset = _filter(data, Commodity=commodity, State=state, District=district, Market=markets or [], Variety=variety)
    return _choices(subset["Grade"]) if "Grade" in subset else []


def _mode(values: pd.Series, fallback: str = "Not supplied") -> str:
    cleaned = values.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned.ne("") & cleaned.str.casefold().ne("unknown")]
    if cleaned.empty:
        return fallback
    counts = cleaned.value_counts()
    winners = counts[counts.eq(counts.max())].index.tolist()
    return str(winners[0]) if len(winners) == 1 else "Mixed labels"


def estimate_markets(
    model,
    data: pd.DataFrame,
    commodity: str,
    state: str,
    district: str,
    selected_markets: list[str],
    quantity: float,
    quantity_unit: str,
    transport_cost: float,
    variety: str = "",
    grade: str = "",
) -> list[dict[str, Any]]:
    """Estimate selected markets and calculate returns only for supported source units."""
    subset = _filter(
        data, Commodity=commodity, State=state, District=district,
        Market=selected_markets, Variety=variety, Grade=grade,
    )
    if subset.empty:
        raise PredictionError("No matching market records were found for these filters.")
    features = model_features(data)
    if not features:
        raise PredictionError("The model input fields are not available in the dataset.")
    feature_frame = subset[features].copy()
    for column in features:
        feature_frame[column] = feature_frame[column].fillna("Unknown").astype(str)
    try:
        predictions = np.asarray(model.predict(feature_frame), dtype=float)
    except Exception as exc:
        raise PredictionError(f"Could not estimate prices for these markets: {exc}") from exc
    if not np.isfinite(predictions).all() or (predictions <= 0).any():
        raise PredictionError("The model returned an invalid price estimate. Review the source and model before comparing markets.")
    predicted = subset[["Market", "Price_Unit"]].copy()
    predicted["_estimate"] = predictions
    by_market_unit = predicted.groupby(["Market", "Price_Unit"], dropna=False)["_estimate"].mean().to_dict()

    results: list[dict[str, Any]] = []
    for (market, price_unit), group in subset.groupby(["Market", "Price_Unit"], sort=False, dropna=False):
        modal = pd.to_numeric(group["Modal_Price"], errors="coerce").dropna()
        min_prices = pd.to_numeric(group.get("Min_Price", pd.Series(index=group.index, dtype=float)), errors="coerce").dropna()
        max_prices = pd.to_numeric(group.get("Max_Price", pd.Series(index=group.index, dtype=float)), errors="coerce").dropna()
        stability = make_stability_data(group, "Market")
        stability_row = stability[0] if stability else {}
        source_estimate = float(by_market_unit[(market, price_unit)])
        unit_text = str(price_unit) if pd.notna(price_unit) else "Not supplied"
        try:
            financials = calculate_financials(source_estimate, unit_text, quantity, quantity_unit, transport_cost)
        except ValueError:
            financials = {"expected_revenue": None, "transport_cost": float(transport_cost), "estimated_net_return": None}
        dates = pd.to_datetime(group.get("Arrival_Date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
        results.append({
            "commodity": commodity,
            "market": str(market),
            "district": district,
            "state": state,
            "region": _mode(group["District_Region"]) if "District_Region" in group else "Not supplied",
            "variety": variety or _mode(group["Variety"]) if "Variety" in group else variety or "Not supplied",
            "grade": grade or _mode(group["Grade"]) if "Grade" in group else grade or "Not supplied",
            "estimated_price_source_units": source_estimate,
            "price_unit": unit_text,
            "quantity": float(quantity),
            "quantity_unit": quantity_unit,
            **financials,
            "stability_cv": stability_row.get("coefficient_of_variation"),
            "stability": (
                f"CV {stability_row['coefficient_of_variation']:.2f}%"
                if stability_row.get("coefficient_of_variation") is not None
                else "Insufficient observations"
            ),
            "source_stability_label": _mode(group["Price_Stability"]) if "Price_Stability" in group else "Not supplied",
            "activity": _mode(group["Market_Activity"]) if "Market_Activity" in group else "Not supplied",
            "market_size": _mode(group["Market_Size"]) if "Market_Size" in group else "Not supplied",
            "observed_average": float(modal.mean()) if len(modal) else None,
            "observed_minimum": float(min_prices.min()) if len(min_prices) else None,
            "observed_maximum": float(max_prices.max()) if len(max_prices) else None,
            "record_count": int(len(group)),
            "latest_observation_date": dates.max().strftime("%Y-%m-%d") if len(dates) else "Unavailable",
        })
    return sorted(results, key=lambda item: item["market"].casefold())
