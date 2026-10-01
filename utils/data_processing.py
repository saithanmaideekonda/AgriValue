"""Read-only loading, validation, cleaning, and summaries for the AgriValue workbook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "agri_value_market_data_final.xlsx"
CLEAN_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "clean_market_data.csv"

EXPECTED_COLUMNS = [
    "State", "District", "Market", "Commodity", "Variety", "Grade",
    "Arrival_Date", "Min_Price", "Max_Price", "Modal_Price", "Commodity_Code",
    "Price_Stability", "Market_Activity", "Market_Size", "District_Region", "Price_Unit",
]
CATEGORY_COLUMNS = [
    "Commodity", "State", "District", "Market", "Variety", "Grade",
    "Price_Stability", "Market_Activity", "Market_Size", "District_Region", "Price_Unit",
]
PRICE_COLUMNS = ["Min_Price", "Max_Price", "Modal_Price"]


class DatasetError(RuntimeError):
    """Raised when the source workbook is missing or has an unusable structure."""


def load_source_data(path: Path | str = RAW_DATA_PATH) -> pd.DataFrame:
    """Load the source workbook without changing its columns or records."""
    source_path = Path(path)
    if not source_path.is_file():
        raise DatasetError(f"Dataset file not found: {source_path}")
    try:
        if source_path.suffix.casefold() in {".xlsx", ".xlsm", ".xls"}:
            frame = pd.read_excel(source_path, sheet_name=0)
        elif source_path.suffix.casefold() == ".csv":
            frame = pd.read_csv(source_path, low_memory=False)
        else:
            raise DatasetError("Use an Excel workbook or CSV dataset file.")
    except DatasetError:
        raise
    except Exception as exc:
        raise DatasetError(f"Could not read the dataset: {exc}") from exc
    if frame.empty:
        raise DatasetError("The dataset has no records.")
    if frame.columns.tolist() != EXPECTED_COLUMNS:
        raise DatasetError(
            "The workbook does not match the final 16-column schema. "
            f"Expected {EXPECTED_COLUMNS}; found {frame.columns.tolist()}."
        )
    return frame


def _normalized(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    for column in CATEGORY_COLUMNS:
        if column in work:
            work[column] = work[column].astype("string").str.strip()
            work[column] = work[column].mask(work[column].eq(""), pd.NA)
    if "Arrival_Date" in work:
        work["Arrival_Date"] = pd.to_datetime(work["Arrival_Date"], format="mixed", errors="coerce")
    for column in PRICE_COLUMNS:
        if column in work:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    if "Commodity_Code" in work:
        work["Commodity_Code"] = pd.to_numeric(work["Commodity_Code"], errors="coerce")
    return work


def _validity_masks(work: pd.DataFrame) -> dict[str, pd.Series]:
    key_columns = [column for column in ["Commodity", "State", "District", "Market", "Price_Unit"] if column in work]
    missing_location = work[key_columns].isna().any(axis=1)
    modal = pd.to_numeric(work["Modal_Price"], errors="coerce")
    invalid_modal = modal.isna() | ~np.isfinite(modal)
    negative_or_zero = modal.le(0)
    invalid_range = pd.Series(False, index=work.index)
    if {"Min_Price", "Max_Price"}.issubset(work.columns):
        low = pd.to_numeric(work["Min_Price"], errors="coerce")
        high = pd.to_numeric(work["Max_Price"], errors="coerce")
        invalid_range = low.isna() | high.isna() | ~np.isfinite(low) | ~np.isfinite(high)
        invalid_range |= low.gt(high) | modal.lt(low) | modal.gt(high)
    return {
        "missing_location": missing_location,
        "invalid_modal": invalid_modal,
        "negative_or_zero": negative_or_zero,
        "invalid_range": invalid_range,
    }


def inspect_cleaning(frame: pd.DataFrame) -> dict[str, Any]:
    """Count data-quality issues without changing the master workbook."""
    work = _normalized(frame)
    masks = _validity_masks(work)
    invalid = pd.Series(False, index=work.index)
    for mask in masks.values():
        invalid |= mask
    valid = work.loc[~invalid]
    prices = pd.to_numeric(valid["Modal_Price"], errors="coerce").dropna()
    if len(prices):
        q1, q3 = prices.quantile([0.25, 0.75])
        iqr = q3 - q1
        outliers = int(((prices < q1 - 1.5 * iqr) | (prices > q3 + 1.5 * iqr)).sum())
    else:
        outliers = 0
    duplicates = int(valid.duplicated().sum())
    return {
        "source_records": int(len(frame)),
        "missing_cells": int(frame.isna().sum().sum()),
        "exact_duplicate_rows": int(frame.duplicated().sum()),
        "rows_missing_location_or_commodity": int(masks["missing_location"].sum()),
        "invalid_modal_price_rows": int(masks["invalid_modal"].sum()),
        "negative_or_zero_modal_price_rows": int(masks["negative_or_zero"].sum()),
        "invalid_min_max_or_modal_range_rows": int(masks["invalid_range"].sum()),
        "missing_or_invalid_date_rows": int(
            pd.to_datetime(frame["Arrival_Date"], errors="coerce").isna().sum()
        ) if "Arrival_Date" in frame else int(len(frame)),
        "modal_price_iqr_outlier_rows_retained": outliers,
        "duplicate_rows_removed": duplicates,
        "rows_removed": int(invalid.sum() + duplicates),
        "rows_after_cleaning": int(len(valid.drop_duplicates())),
        "cleaning_note": "The source workbook remains unchanged. Exact duplicate rows and invalid keys/prices/ranges are excluded from the working set. Missing dates and IQR flags are retained because date is optional and a mixed-commodity outlier flag alone does not establish an invalid value.",
    }


def prepare_market_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Create a cleaned working copy; retain the source columns and valid rows."""
    work = _normalized(frame)
    masks = _validity_masks(work)
    invalid = pd.Series(False, index=work.index)
    for mask in masks.values():
        invalid |= mask
    cleaned = work.loc[~invalid].drop_duplicates().copy()
    for column in CATEGORY_COLUMNS:
        if column in cleaned:
            cleaned[column] = cleaned[column].fillna("Unknown").astype(str)
    if "Arrival_Date" in cleaned:
        cleaned["Arrival_Date"] = pd.to_datetime(cleaned["Arrival_Date"], errors="coerce")
    return cleaned[EXPECTED_COLUMNS].reset_index(drop=True)


def save_clean_market_data(frame: pd.DataFrame) -> None:
    CLEAN_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CLEAN_DATA_PATH, index=False, date_format="%Y-%m-%d")


def load_clean_market_data(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rebuild the processed working file from the current master on every run."""
    source = frame if frame is not None else load_source_data()
    cleaned = prepare_market_data(source)
    save_clean_market_data(cleaned)
    return cleaned


def _count_dict(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    values = series.dropna().astype(str).str.strip()
    values = values[values.ne("")]
    return {str(key): int(value) for key, value in values.value_counts().items()}


def _price_summary(series: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"average": None, "minimum": None, "maximum": None}
    return {"average": float(values.mean()), "minimum": float(values.min()), "maximum": float(values.max())}


def make_dataset_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Calculate source counts, coverage, missingness, and raw price statistics."""
    dates = pd.to_datetime(frame["Arrival_Date"], errors="coerce").dropna() if "Arrival_Date" in frame else pd.Series(dtype="datetime64[ns]")
    unit_stats = []
    for unit, group in frame.groupby("Price_Unit", dropna=True, sort=True):
        unit_stats.append({
            "price_unit": str(unit), "records": int(len(group)),
            "min_price": _price_summary(group["Min_Price"]),
            "max_price": _price_summary(group["Max_Price"]),
            "modal_price": _price_summary(group["Modal_Price"]),
        })
    one_unit = len(unit_stats) == 1
    prices = _price_summary(frame["Modal_Price"]) if one_unit else {"average": None, "minimum": None, "maximum": None}
    dimensions = ["Commodity", "State", "District", "Market", "Variety", "Grade", "District_Region", "Market_Size", "Market_Activity", "Price_Stability", "Price_Unit"]
    distributions = {column: _count_dict(frame[column]) if column in frame else {} for column in dimensions}
    return {
        "total_records": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": frame.columns.tolist(),
        "commodity_count": int(frame["Commodity"].nunique(dropna=True)),
        "state_count": int(frame["State"].nunique(dropna=True)),
        "district_count": int(frame["District"].nunique(dropna=True)),
        "market_count": int(frame["Market"].nunique(dropna=True)),
        "variety_count": int(frame["Variety"].nunique(dropna=True)) if "Variety" in frame else 0,
        "grade_count": int(frame["Grade"].nunique(dropna=True)) if "Grade" in frame else 0,
        "date_start": dates.min().strftime("%d %b %Y") if len(dates) else "Unavailable",
        "date_end": dates.max().strftime("%d %b %Y") if len(dates) else "Unavailable",
        "valid_date_records": int(len(dates)),
        "unique_dates": int(dates.nunique()),
        "average_modal_price": prices["average"],
        "minimum_modal_price": prices["minimum"],
        "maximum_modal_price": prices["maximum"],
        "distributions": distributions,
        "price_unit_distribution": distributions["Price_Unit"],
        "price_statistics_by_unit": unit_stats,
        "missing_cells": int(frame.isna().sum().sum()),
        "missing_values_by_column": {str(k): int(v) for k, v in frame.isna().sum().items() if v},
        "duplicate_rows": int(frame.duplicated().sum()),
        "price_unit_note": "Each price uses the row's source Price_Unit. No automatic conversion between units is applied.",
    }


def _mode_label(frame: pd.DataFrame, column: str) -> str:
    if column not in frame:
        return "Not available"
    counts = _count_dict(frame[column])
    if not counts:
        return "Not available"
    highest = max(counts.values())
    winners = [name for name, count in counts.items() if count == highest]
    return winners[0] if len(winners) == 1 else "Mixed labels"


def _average_rows(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    if group_column not in frame or "Modal_Price" not in frame:
        return []
    work = frame[[group_column, "Modal_Price", "Price_Unit"]].copy()
    work["Modal_Price"] = pd.to_numeric(work["Modal_Price"], errors="coerce")
    work = work.dropna(subset=[group_column, "Modal_Price", "Price_Unit"])
    grouped = work.groupby([group_column, "Price_Unit"], dropna=True)["Modal_Price"].agg(["mean", "size"]).sort_values("mean", ascending=False)
    return [{"label": str(key[0]), "price_unit": str(key[1]), "average": float(row["mean"]), "records": int(row["size"])} for key, row in grouped.iterrows()]


def make_stability_data(frame: pd.DataFrame, group_column: str = "Market") -> list[dict[str, Any]]:
    """Observed-row mean, sample standard deviation, and CV by label and price unit."""
    if group_column not in frame or "Modal_Price" not in frame:
        return []
    work = frame[[group_column, "Modal_Price", "Price_Unit", "Arrival_Date"]].copy()
    work[group_column] = work[group_column].astype("string").str.strip()
    work["Modal_Price"] = pd.to_numeric(work["Modal_Price"], errors="coerce")
    work = work.dropna(subset=[group_column, "Modal_Price", "Price_Unit"])
    rows = []
    for (label, price_unit), group in work.groupby([group_column, "Price_Unit"], sort=False):
        prices = group["Modal_Price"].astype(float)
        mean = float(prices.mean())
        std = float(prices.std(ddof=1)) if len(prices) >= 2 else None
        cv = (std / mean * 100.0) if std is not None and mean != 0 else None
        dates = pd.to_datetime(group["Arrival_Date"], errors="coerce").dropna()
        rows.append({
            "label": str(label), "price_unit": str(price_unit), "mean": mean,
            "minimum": float(prices.min()), "maximum": float(prices.max()), "standard_deviation": std,
            "coefficient_of_variation": cv, "records": int(len(prices)),
            "unique_dates": int(dates.nunique()) if len(dates) else 0,
        })
    return rows


def make_source_stability_distribution(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Count source-provided stability classifications without treating them as predictions."""
    if "Price_Stability" not in frame:
        return []
    labels = frame["Price_Stability"].dropna().astype(str).str.strip()
    labels = labels[labels.ne("") & labels.str.casefold().ne("unknown")]
    counts = labels.value_counts()
    return [
        {"label": str(label), "records": int(count)}
        for label, count in counts.sort_values(ascending=False).items()
    ]


def make_dashboard_aggregates(frame: pd.DataFrame) -> dict[str, Any]:
    """Provide actual-record summaries for price comparisons and insight cards."""
    prices = pd.to_numeric(frame.get("Modal_Price", pd.Series(dtype=float)), errors="coerce")
    return {
        "regions": _average_rows(frame, "District_Region"),
        "varieties": _average_rows(frame, "Variety"),
        "grades": _average_rows(frame, "Grade"),
        "stability": make_stability_data(frame),
        "insights": {
            "price_stability_label": _mode_label(frame, "Price_Stability"),
            "market_activity": _mode_label(frame, "Market_Activity"),
            "market_size": _mode_label(frame, "Market_Size"),
            "popular_variety": _mode_label(frame, "Variety"),
            "regional_average": float(prices.mean()) if prices.notna().any() else None,
            "regional_label": _mode_label(frame, "District_Region"),
            "total_records": int(len(frame)),
        },
    }
