"""Train and evaluate one explainable price model for every dataset commodity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from utils.data_processing import (
    CLEAN_DATA_PATH,
    PROJECT_ROOT,
    inspect_cleaning,
    load_source_data,
    prepare_market_data,
    save_clean_market_data,
)


FEATURES = [
    "Commodity", "State", "District", "Market", "Variety", "Grade",
    "District_Region", "Price_Unit",
]
TARGET = "Modal_Price"
MODEL_PATH = PROJECT_ROOT / "models" / "price_model.pkl"
METADATA_PATH = PROJECT_ROOT / "models" / "model_metadata.json"


def model_features(frame: pd.DataFrame) -> list[str]:
    """Choose only available pre-sale categorical fields; never price-derived labels."""
    return [column for column in FEATURES if column in frame.columns]


def make_pipeline(features: list[str] | None = None) -> TransformedTargetRegressor:
    selected = features or FEATURES
    encoder = ColumnTransformer(
        transformers=[
            (
                "categories",
                OneHotEncoder(handle_unknown="ignore", min_frequency=2),
                selected,
            )
        ],
        remainder="drop",
    )
    regression_pipeline = Pipeline(
        steps=[("preprocessing", encoder), ("regression", LinearRegression())]
    )
    return TransformedTargetRegressor(
        regressor=regression_pipeline,
        func=np.log1p,
        inverse_func=np.expm1,
    )


def _split_indices(frame: pd.DataFrame) -> tuple[pd.Index, pd.Index, str]:
    """Use a date-ordered holdout when dates span time; otherwise a seeded split."""
    if "Arrival_Date" in frame:
        dates = pd.to_datetime(frame["Arrival_Date"], errors="coerce")
        unique_dates = dates.dropna().nunique()
        if unique_dates >= 5:
            ordered = frame.assign(_split_date=dates).sort_values("_split_date", kind="stable")
            dated = ordered[ordered["_split_date"].notna()]
            cutoff = max(1, int(len(dated) * 0.8))
            cutoff = min(cutoff, len(dated) - 1)
            training = pd.Index(ordered.index[ordered["_split_date"].isna()].tolist() + dated.index[:cutoff].tolist())
            testing = pd.Index(dated.index[cutoff:].tolist())
            if len(training) and len(testing):
                return training, testing, "Chronological 80/20 holdout by Arrival_Date; undated records kept in training."
    train, test = train_test_split(frame.index, test_size=0.20, random_state=42)
    return pd.Index(train), pd.Index(test), "Seeded random 80/20 holdout (42); source has insufficient distinct dates for a chronological split."


def _feature_frame(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    result = frame[features].copy()
    for column in features:
        result[column] = result[column].astype("string").fillna("Unknown").astype(str)
    return result


def train_and_save() -> dict[str, Any]:
    """Calculate holdout metrics and save a multi-commodity serving pipeline."""
    raw = load_source_data()
    cleaning = inspect_cleaning(raw)
    cleaned = prepare_market_data(raw)
    features = model_features(cleaned)
    if len(cleaned) < 10 or not features:
        raise ValueError("At least 10 valid market records and one model feature are required.")
    if cleaned[TARGET].nunique() < 2:
        raise ValueError("The target column needs at least two distinct valid prices to train.")
    save_clean_market_data(cleaned)

    x = _feature_frame(cleaned, features)
    y = pd.to_numeric(cleaned[TARGET], errors="coerce").astype(float)
    train_index, test_index, split_method = _split_indices(cleaned)
    evaluation_model = make_pipeline(features)
    evaluation_model.fit(x.loc[train_index], y.loc[train_index])
    predictions = evaluation_model.predict(x.loc[test_index])

    final_model = make_pipeline(features)
    final_model.fit(x, y)
    testing_target = y.loc[test_index]
    metadata: dict[str, Any] = {
        "model_name": "Linear Regression (log-transformed target)",
        "model_type": "TransformedTargetRegressor around a scikit-learn Pipeline (OneHotEncoder + LinearRegression)",
        "target_variable": TARGET,
        "target_unit": "The model estimates Modal_Price in the row's source Price_Unit.",
        "training_records": int(len(train_index)),
        "testing_records": int(len(test_index)),
        "mae": float(mean_absolute_error(testing_target, predictions)),
        "rmse": float(np.sqrt(mean_squared_error(testing_target, predictions))),
        "r2": float(r2_score(testing_target, predictions)) if len(testing_target) >= 2 else None,
        "features_used": features,
        "excluded_features": [
            "Modal_Price (target)", "Min_Price", "Max_Price", "Commodity_Code (identifier)",
            "Arrival_Date (single-date snapshot and missing rows)",
            "Price_Stability, Market_Activity, Market_Size (source summaries that may use aggregate information)",
        ],
        "preprocessing": "OneHotEncoder for the eight categorical inputs; infrequent categories (below 2 rows) grouped; unknown categories ignored; missing category values represented as Unknown. Modal_Price is fit as log1p(price) and predictions are transformed back with expm1, keeping estimates positive while reducing the influence of the skewed price range.",
        "training_approach": "One general model trained on all valid commodities, with Commodity included as an encoded feature.",
        "split_method": split_method,
        "records_after_cleaning": int(len(cleaned)),
        "commodity_count": int(cleaned["Commodity"].nunique()),
        "commodities": sorted(cleaned["Commodity"].astype(str).unique().tolist()),
        "date_range": [
            str(pd.to_datetime(cleaned["Arrival_Date"], errors="coerce").min().date())
            if pd.to_datetime(cleaned["Arrival_Date"], errors="coerce").notna().any() else None,
            str(pd.to_datetime(cleaned["Arrival_Date"], errors="coerce").max().date())
            if pd.to_datetime(cleaned["Arrival_Date"], errors="coerce").notna().any() else None,
        ],
        "unique_dates": int(pd.to_datetime(cleaned["Arrival_Date"], errors="coerce").nunique()) if "Arrival_Date" in cleaned else 0,
        "cleaning": cleaning,
        "model_note": "The model excludes the target, same-observation low/high prices, the identifier, the date, and aggregate source labels that may depend on complete market information.",
        "evaluation_note": "The source has limited temporal coverage. The available valid rows have only one distinct date, so the holdout metrics measure a same-snapshot split and do not demonstrate future-price accuracy.",
        "model_fit_for_predictions": "All valid, deduplicated market rows across all available commodities.",
        "source_rows": int(len(raw)),
        "source_columns": int(len(raw.columns)),
        "price_units": sorted(cleaned["Price_Unit"].dropna().astype(str).unique().tolist()),
        "processed_data_path": str(CLEAN_DATA_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_model, MODEL_PATH)
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    print(json.dumps(train_and_save(), indent=2))
