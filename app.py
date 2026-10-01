"""AgriValue: Flask decision support for agricultural market price estimates."""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from flask import Flask, abort, jsonify, render_template, request, send_file, session

from utils.calculations import (
    InputError,
    make_quantity_range,
    read_nonnegative_number,
    recalculate_returns,
    supported_quantity_units,
)
from utils.data_processing import (
    RAW_DATA_PATH,
    DatasetError,
    inspect_cleaning,
    load_clean_market_data,
    load_source_data,
    make_dashboard_aggregates,
    make_dataset_summary,
    make_stability_data,
    make_source_stability_distribution,
)
from utils.model_training import METADATA_PATH, MODEL_PATH
from utils.prediction import (
    PredictionError,
    commodities_for_analysis,
    districts_for_analysis,
    estimate_markets,
    filtered_records,
    grades_for_analysis,
    load_model,
    markets_for_analysis,
    states_for_analysis,
    varieties_for_analysis,
)
from utils.reporting import build_pdf_report, build_workbook_report, build_csv_report


PROJECT_ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.update(SECRET_KEY="agrivalue-local-demo-key", MAX_CONTENT_LENGTH=2 * 1024 * 1024)

RAW_DATA: pd.DataFrame | None = None
MARKET_DATA: pd.DataFrame | None = None
MODEL = None
DATASET_ERROR: str | None = None
MODEL_ERROR: str | None = None
REPORT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()


def refresh_runtime() -> None:
    """Load the Excel master, build a separate clean working copy, and load the model."""
    global RAW_DATA, MARKET_DATA, MODEL, DATASET_ERROR, MODEL_ERROR
    RAW_DATA = MARKET_DATA = MODEL = None
    DATASET_ERROR = MODEL_ERROR = None
    try:
        RAW_DATA = load_source_data(RAW_DATA_PATH)
        MARKET_DATA = load_clean_market_data(RAW_DATA)
        if MARKET_DATA.empty:
            raise DatasetError("No valid market records are available after data checks.")
    except (DatasetError, OSError, ValueError) as exc:
        DATASET_ERROR = str(exc)
        return
    try:
        MODEL = load_model(MODEL_PATH)
    except PredictionError as exc:
        MODEL_ERROR = str(exc)


refresh_runtime()


def _base_context(active_page: str, **values: Any) -> dict[str, Any]:
    return {"active_page": active_page, "data_error": DATASET_ERROR, **values}


def _recommendation_for_markets(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Select every market tied for the highest valid calculated net return."""
    valid = []
    for item in markets:
        if not str(item.get("market") or "").strip():
            continue
        try:
            revenue_value = float(item.get("expected_revenue"))
            return_value = float(item.get("estimated_net_return"))
            price_value = float(item.get("estimated_price_source_units"))
            quantity_value = float(item.get("quantity"))
            transport_value = float(item.get("transport_cost"))
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in (revenue_value, return_value, price_value, quantity_value, transport_value)):
            valid.append((item, return_value))
    if not valid:
        return {"available": False, "markets": []}
    highest_return = max(value for _, value in valid)
    return {
        "available": True,
        "markets": [item for item, value in valid if value == highest_return],
    }


def _metadata() -> dict[str, Any] | None:
    if not METADATA_PATH.is_file():
        return None
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _price_unit_label(price_unit: str | None) -> str:
    return str(price_unit).strip() if price_unit else "Price unit not available"


def _quantity_units(frame: pd.DataFrame | None) -> list[str]:
    """Return quantity units safe for every observed source unit in this selection."""
    if frame is None or frame.empty or "Price_Unit" not in frame:
        return []
    source_units = frame["Price_Unit"].dropna().astype(str).unique().tolist()
    supported = [set(supported_quantity_units(unit)) for unit in source_units]
    if not supported:
        return []
    return [unit for unit in ("kg", "quintal", "number") if all(unit in options for options in supported)]


def _register_report(payload: dict[str, Any]) -> str:
    report_id = uuid4().hex
    REPORT_CACHE[report_id] = payload
    while len(REPORT_CACHE) > 25:
        REPORT_CACHE.popitem(last=False)
    return report_id


def _make_report_payload(
    inputs: dict[str, Any], markets: list[dict[str, Any]], frame: pd.DataFrame,
    quantity: float, quantity_unit: str, transport_cost: float,
    quantity_rows: list[dict[str, Any]] | None = None,
    quantity_note: str = "Select a market and confirm its source price unit to calculate a quantity range.",
) -> dict[str, Any]:
    stability = make_stability_data(frame, "Market")
    if quantity_rows is None:
        quantity_rows = []
        for item in markets:
            if item.get("expected_revenue") is None or item.get("estimated_net_return") is None:
                continue
            quantity_rows.append({
                "market": item.get("market"), "quantity": float(quantity), "quantity_unit": quantity_unit,
                "estimated_price": item.get("estimated_price_source_units"), "price_unit": item.get("price_unit"),
                "expected_revenue": item.get("expected_revenue"),
                "transport_cost": item.get("transport_cost"),
                "estimated_net_return": item.get("estimated_net_return"),
                "difference_from_previous": None,
            })
    return {
        "inputs": inputs,
        "markets": markets,
        "stability": stability,
        "quantity_range": quantity_rows or [],
        "quantity_note": quantity_note,
        "price_unit_label": _price_unit_label(markets[0].get("price_unit") if markets else None),
        "model": _metadata() or {},
        "analysis_note": "Insufficient data for this section using the selected filters.",
        "historical_record_count": int(len(frame)),
    }


def _validate_selection(
    state: str,
    district: str,
    selected_markets: list[str],
    commodity: str,
    variety: str = "",
    grade: str = "",
    quantity_unit: str = "",
) -> None:
    if MARKET_DATA is None:
        raise InputError(DATASET_ERROR or "Dataset is not available.")
    if state not in states_for_analysis(MARKET_DATA):
        raise InputError("Select a state available in the dataset.")
    if district not in districts_for_analysis(MARKET_DATA, state=state):
        raise InputError("Select a district with records in the selected state.")
    if not selected_markets:
        raise InputError("Select at least one market.")
    if len(selected_markets) > 100:
        raise InputError("Compare up to 100 markets at a time.")
    location_rows = filtered_records(MARKET_DATA, State=state, District=district, Market=selected_markets)
    if location_rows.empty:
        raise InputError("Select markets with records in the chosen state and district.")
    if commodity not in commodities_for_analysis(location_rows):
        raise InputError("Select a commodity available in the chosen market or markets.")
    available_varieties = varieties_for_analysis(MARKET_DATA, commodity, state, district, selected_markets)
    if variety and variety not in available_varieties:
        raise InputError("Select a variety present in the chosen markets.")
    available_grades = grades_for_analysis(
        MARKET_DATA, commodity, state, district, selected_markets, variety
    )
    if grade and grade not in available_grades:
        raise InputError("Select a grade present in the chosen markets and variety.")
    available_markets = markets_for_analysis(MARKET_DATA, state=state, district=district)
    if any(market not in available_markets for market in selected_markets):
        raise InputError("One or more markets do not match the selected state and district.")
    matching = filtered_records(
        MARKET_DATA, State=state, District=district, Market=selected_markets,
        Commodity=commodity, Variety=variety, Grade=grade,
    )
    if quantity_unit not in _quantity_units(matching):
        raise InputError("Choose a quantity unit supported by all selected source price units.")


def _choices() -> list[str]:
    return commodities_for_analysis(MARKET_DATA) if MARKET_DATA is not None else []


def _analysis_context(**values: Any) -> dict[str, Any]:
    return _base_context(
        "analysis",
        commodities=_choices(),
        states=states_for_analysis(MARKET_DATA) if MARKET_DATA is not None else [],
        model_error=MODEL_ERROR,
        **values,
    )


def _analysis_error(message: str, status: int = 400, **prior: Any):
    return render_template(
        "analysis.html",
        **_analysis_context(
            selected_commodity=prior.get("commodity", ""),
            selected_state=prior.get("state", ""),
            selected_district=prior.get("district", ""),
            selected_markets=prior.get("markets", []),
            selected_variety=prior.get("variety", ""),
            selected_grade=prior.get("grade", ""),
            quantity=prior.get("quantity", ""),
            quantity_unit=prior.get("quantity_unit", ""),
            transport_cost=prior.get("transport_cost", ""),
            error=message,
        ),
    ), status


@app.get("/")
def home():
    summary = make_dataset_summary(RAW_DATA) if RAW_DATA is not None else None
    return render_template("index.html", **_base_context("home", summary=summary))


@app.get("/analysis")
def analysis():
    return render_template(
        "analysis.html",
        **_analysis_context(
            selected_commodity="",
            selected_state="",
            selected_district="",
            selected_markets=[],
            quantity="",
            quantity_unit="",
            transport_cost="",
            selected_variety="",
            selected_grade="",
            error=None,
        ),
    )


@app.post("/predict")
def predict():
    if DATASET_ERROR or MARKET_DATA is None:
        return _analysis_error(DATASET_ERROR or "The dataset is not ready.", 503)
    if MODEL is None:
        return _analysis_error(MODEL_ERROR or "The price model is not available.", 503)

    commodity = (request.form.get("commodity") or "").strip()
    state = (request.form.get("state") or "").strip()
    district = (request.form.get("district") or "").strip()
    selected_markets = list(dict.fromkeys(value.strip() for value in request.form.getlist("markets") if value.strip()))
    quantity_text = request.form.get("quantity", "")
    quantity_unit = (request.form.get("quantity_unit") or "").strip()
    transport_text = request.form.get("transport_cost", "")
    variety = (request.form.get("variety") or "").strip()
    grade = (request.form.get("grade") or "").strip()
    prior = {
        "commodity": commodity, "state": state, "district": district,
        "markets": selected_markets, "quantity": quantity_text,
        "quantity_unit": quantity_unit, "transport_cost": transport_text,
        "variety": variety, "grade": grade,
    }
    try:
        _validate_selection(state, district, selected_markets, commodity, variety, grade, quantity_unit)
        quantity = read_nonnegative_number(quantity_text, "Quantity", allow_zero=False)
        transport_cost = read_nonnegative_number(transport_text, "User-Entered Transportation Cost", allow_zero=True)
        markets = estimate_markets(
            MODEL, MARKET_DATA, commodity, state, district, selected_markets,
            quantity, quantity_unit, transport_cost, variety=variety, grade=grade,
        )
    except (InputError, PredictionError) as exc:
        return _analysis_error(str(exc), 422, **prior)
    if not markets:
        return _analysis_error("No matching markets were found for these selections.", **prior)

    active_data = filtered_records(
        MARKET_DATA, Commodity=commodity, State=state, District=district,
        Market=selected_markets, Variety=variety, Grade=grade,
    )
    aggregates = make_dashboard_aggregates(active_data)
    range_market_index = next(
        (index for index, item in enumerate(markets)
         if item.get("estimated_net_return") is not None and item.get("expected_revenue") is not None),
        None,
    )
    range_minimum = max(quantity / 2, 0.01)
    range_step = range_minimum
    range_maximum = max(quantity * 2, range_minimum + range_step * 3)
    quantity_range: list[dict[str, Any]] = []
    quantity_range_note = "Select a market with a supported price unit to calculate quantity scenarios."
    if range_market_index is not None:
        range_market = markets[range_market_index]
        quantity_range = make_quantity_range(
            range_market["estimated_price_source_units"], range_market["price_unit"],
            quantity_unit, range_minimum, range_maximum, range_step, transport_cost,
        )
        for row in quantity_range:
            row["market"] = range_market["market"]
        quantity_range_note = "Transportation cost is user-entered and held fixed across this quantity range."
    chart_data = {
        "source_stability_labels": make_source_stability_distribution(active_data),
    }
    report_payload = _make_report_payload(
        {"commodity": commodity, "state": state, "district": district,
         "markets": selected_markets, "variety": variety, "grade": grade,
         "quantity": quantity, "quantity_unit": quantity_unit,
         "transport_cost": transport_cost,
         "minimum_quantity": range_minimum, "maximum_quantity": range_maximum,
         "quantity_step": range_step,
         "quantity_range_market": markets[range_market_index]["market"] if range_market_index is not None else ""},
        markets, active_data, quantity, quantity_unit, transport_cost,
        quantity_rows=quantity_range, quantity_note=quantity_range_note,
    )
    report_id = _register_report(report_payload)
    session["latest_report_id"] = report_id
    return render_template(
        "results.html",
        **_base_context(
            "analysis", markets=markets,
            commodity=commodity, state=state, district=district, quantity=quantity,
            quantity_unit=quantity_unit, transport_cost=transport_cost,
            quantity_units=_quantity_units(active_data),
              aggregates=aggregates, chart_data=chart_data, report_id=report_id,
            recommendation=_recommendation_for_markets(markets),
              quantity_range=quantity_range, quantity_range_note=quantity_range_note,
              range_market_index=range_market_index,
              range_minimum=range_minimum, range_maximum=range_maximum, range_step=range_step,
              has_price_chart=bool(markets),
              has_return_chart=any(item.get("estimated_net_return") is not None for item in markets),
            selected_variety=variety, selected_grade=grade,
        ),
    )


@app.post("/calculate")
def calculate():
    """Recalculate results and quantity scenarios through the shared finance helpers."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the what-if values as JSON."}), 400
    try:
        quantity = read_nonnegative_number(payload.get("quantity"), "Quantity", allow_zero=False)
        transport = read_nonnegative_number(payload.get("transport_cost"), "Transportation cost", allow_zero=True)
        quantity_unit = str(payload.get("quantity_unit") or "").strip()
        if not quantity_unit:
            raise InputError("Choose the quantity unit that matches the market price unit.")
        values = payload.get("markets")
        if not isinstance(values, list) or not values or len(values) > 100:
            raise InputError("Provide between 1 and 100 compared markets.")
        if any(not isinstance(value, dict) for value in values):
            raise InputError("Each compared market must include an estimated price.")
        results = recalculate_returns(values, quantity, quantity_unit, transport)
        range_config = payload.get("quantity_range")
        quantity_range = []
        range_result = None
        if range_config is not None:
            if not isinstance(range_config, dict):
                raise InputError("Provide valid quantity-range inputs.")
            try:
                range_market_index = int(range_config.get("market_index"))
            except (TypeError, ValueError):
                raise InputError("Choose a market for quantity-range analysis.") from None
            if range_market_index < 0 or range_market_index >= len(results):
                raise InputError("Choose a market available in this comparison.")
            range_result = results[range_market_index]
            quantity_range = make_quantity_range(
                values[range_market_index].get("estimated_price_source_units"),
                str(range_result.get("price_unit", "")), quantity_unit,
                range_config.get("minimum_quantity"), range_config.get("maximum_quantity"),
                range_config.get("quantity_step"), transport,
            )
            for row in quantity_range:
                row["market"] = range_result["market"]

        report_id = str(payload.get("report_id") or "").strip()
        if report_id:
            if session.get("latest_report_id") != report_id:
                raise InputError("This comparison report has expired. Run the market analysis again.")
            report = REPORT_CACHE.get(report_id)
            if report is None or len(report.get("markets", [])) != len(values):
                raise InputError("This comparison report has expired. Run the market analysis again.")
            original_markets = report["markets"]
            for index, (original, submitted, calculated) in enumerate(zip(original_markets, values, results)):
                try:
                    submitted_price = float(submitted.get("estimated_price_source_units"))
                    original_price = float(original.get("estimated_price_source_units"))
                except (TypeError, ValueError):
                    raise InputError("The market estimates do not match this comparison.") from None
                if (
                    str(submitted.get("market", "")) != str(original.get("market", ""))
                    or str(submitted.get("price_unit", "")) != str(original.get("price_unit", ""))
                    or submitted_price != original_price
                ):
                    raise InputError("The market estimates do not match this comparison.")
                original.update({
                    "quantity": calculated["quantity"],
                    "quantity_unit": calculated["quantity_unit"],
                    "expected_revenue": calculated["expected_revenue"],
                    "transport_cost": calculated["transport_cost"],
                    "estimated_net_return": calculated["estimated_net_return"],
                })
            report["inputs"].update({
                "quantity": quantity, "quantity_unit": quantity_unit,
                "transport_cost": transport,
            })
            if range_config is not None and range_result is not None:
                report["inputs"].update({
                    "minimum_quantity": read_nonnegative_number(
                        range_config.get("minimum_quantity"), "Minimum quantity", allow_zero=False
                    ),
                    "maximum_quantity": read_nonnegative_number(
                        range_config.get("maximum_quantity"), "Maximum quantity", allow_zero=False
                    ),
                    "quantity_step": range_config.get("quantity_step"),
                    "quantity_range_market": range_result["market"],
                })
                report["quantity_range"] = quantity_range
                report["quantity_note"] = "Transportation cost is user-entered and held fixed across this quantity range."
    except InputError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "quantity": quantity, "quantity_unit": quantity_unit,
        "transport_cost": transport, "markets": results,
        "quantity_range": quantity_range,
    })


@app.get("/api/states")
def api_states():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    return jsonify({"states": states_for_analysis(MARKET_DATA)})


@app.get("/api/districts")
def api_districts():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    state = (request.args.get("state") or "").strip()
    if state not in states_for_analysis(MARKET_DATA):
        return jsonify({"error": "Choose a state available in the dataset."}), 400
    return jsonify({"districts": districts_for_analysis(MARKET_DATA, state=state)})


@app.get("/api/markets")
def api_markets():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    state = (request.args.get("state") or "").strip()
    district = (request.args.get("district") or "").strip()
    commodity = (request.args.get("commodity") or "").strip()
    variety = (request.args.get("variety") or "").strip()
    grade = (request.args.get("grade") or "").strip()
    if district not in districts_for_analysis(MARKET_DATA, state=state):
        return jsonify({"error": "Choose a district with matching records."}), 400
    return jsonify({"markets": markets_for_analysis(MARKET_DATA, commodity, state, district, variety, grade)})


@app.get("/api/commodities")
def api_commodities():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    state = (request.args.get("state") or "").strip()
    district = (request.args.get("district") or "").strip()
    markets = request.args.getlist("market")
    rows = filtered_records(MARKET_DATA, State=state, District=district, Market=markets)
    return jsonify({"commodities": commodities_for_analysis(rows)})


@app.get("/api/varieties")
def api_varieties():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    commodity, state, district = (request.args.get(key, "").strip() for key in ("commodity", "state", "district"))
    markets = request.args.getlist("market")
    if not commodity:
        return jsonify({"varieties": []})
    return jsonify({"varieties": varieties_for_analysis(MARKET_DATA, commodity, state, district, markets)})


@app.get("/api/grades")
def api_grades():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    commodity, state, district = (request.args.get(key, "").strip() for key in ("commodity", "state", "district"))
    markets = request.args.getlist("market")
    variety = (request.args.get("variety") or "").strip()
    if not commodity:
        return jsonify({"grades": []})
    return jsonify({"grades": grades_for_analysis(MARKET_DATA, commodity, state, district, markets, variety)})


@app.get("/api/quantity-units")
def api_quantity_units():
    if MARKET_DATA is None:
        return jsonify({"error": DATASET_ERROR or "Dataset is not available."}), 503
    filters = {key.title(): (request.args.get(key) or "").strip() for key in ("state", "district", "commodity", "variety", "grade")}
    markets = request.args.getlist("market")
    if markets:
        filters["Market"] = markets
    rows = filtered_records(MARKET_DATA, **filters)
    return jsonify({"quantity_units": _quantity_units(rows), "price_units": sorted(rows["Price_Unit"].dropna().astype(str).unique().tolist())})


@app.get("/visual-analysis")
def visual_analysis():
    selected = {key: (request.args.get(key) or "").strip() for key in ("commodity", "state", "district", "variety", "grade")}
    selected["markets"] = list(dict.fromkeys(value.strip() for value in request.args.getlist("market") if value.strip()))
    selected.update({
        "minimum_quantity": request.args.get("minimum_quantity", "100"),
        "maximum_quantity": request.args.get("maximum_quantity", "1000"),
        "quantity_step": request.args.get("quantity_step", "100"),
        "transport_cost": request.args.get("transport_cost", "0"),
        "quantity_unit": (request.args.get("quantity_unit") or "").strip(),
        "range_market_index": (request.args.get("range_market_index") or "").strip(),
        "range_minimum_quantity": request.args.get("range_minimum_quantity", request.args.get("minimum_quantity", "100")),
        "range_maximum_quantity": request.args.get("range_maximum_quantity", request.args.get("maximum_quantity", "1000")),
        "range_quantity_step": request.args.get("range_quantity_step", request.args.get("quantity_step", "100")),
        "range_quantity_unit": (request.args.get("range_quantity_unit") or "").strip(),
        "range_transport_cost": request.args.get("range_transport_cost", request.args.get("transport_cost", "0")),
    })
    values: dict[str, Any] = {"quantity_range": [], "market_comparison": [], "quantity_market_options": [], "records": 0, "error": None, "report_id": None, "analyzed": request.args.get("analyze") == "1", "quantity_note": "Select one market to calculate quantity scenarios."}
    filtered = MARKET_DATA.iloc[0:0].copy() if MARKET_DATA is not None else pd.DataFrame()
    try:
        if values["analyzed"]:
            if MARKET_DATA is None or MODEL is None:
                raise InputError(DATASET_ERROR or MODEL_ERROR or "The dataset or price model is not available.")
            commodity = selected["commodity"]
            if selected["state"] not in states_for_analysis(MARKET_DATA):
                raise InputError("Select a state available in the dataset.")
            if selected["district"] not in districts_for_analysis(MARKET_DATA, state=selected["state"]):
                raise InputError("Select a district with records in the selected state.")
            if commodity not in commodities_for_analysis(
                filtered_records(MARKET_DATA, State=selected["state"], District=selected["district"], Market=selected["markets"])
            ):
                raise InputError("Select a commodity with records in this location and market selection.")
            available_markets = markets_for_analysis(
                MARKET_DATA, commodity, selected["state"], selected["district"], selected["variety"], selected["grade"]
            )
            if any(market not in available_markets for market in selected["markets"]):
                raise InputError("Select markets with records matching the other filters.")
            if len(selected["markets"]) > 100:
                raise InputError("Compare up to 100 markets at a time.")
            if selected["variety"] and selected["variety"] not in varieties_for_analysis(
                MARKET_DATA, commodity, selected["state"], selected["district"], selected["markets"]
            ):
                raise InputError("Select a variety with matching records.")
            if selected["grade"] and selected["grade"] not in grades_for_analysis(
                MARKET_DATA, commodity, selected["state"], selected["district"], selected["markets"], selected["variety"]
            ):
                raise InputError("Select a grade with matching records.")
            transport_value = read_nonnegative_number(selected["transport_cost"], "Transportation cost", allow_zero=True)
            filters = {"Commodity": commodity, "State": selected["state"], "District": selected["district"]}
            if selected["markets"]:
                filters["Market"] = selected["markets"]
            if selected["variety"]:
                filters["Variety"] = selected["variety"]
            if selected["grade"]:
                filters["Grade"] = selected["grade"]
            filtered = filtered_records(MARKET_DATA, **filters)
            if filtered.empty:
                raise InputError("No records match the selected filters.")
            values["records"] = len(filtered)
            selected_for_comparison = selected["markets"] or markets_for_analysis(
                MARKET_DATA, commodity, selected["state"], selected["district"], selected["variety"], selected["grade"]
            )
            if len(selected_for_comparison) > 100:
                raise InputError("This location has more than 100 matching markets. Select specific markets to compare.")
            quantity = read_nonnegative_number(selected["minimum_quantity"], "Minimum quantity", allow_zero=False)
            unit_for_prediction = selected["quantity_unit"] or next(iter(_quantity_units(filtered)), "")
            market_comparison = estimate_markets(
                MODEL, MARKET_DATA, commodity, selected["state"], selected["district"], selected_for_comparison,
                quantity, unit_for_prediction, transport_value, variety=selected["variety"], grade=selected["grade"],
            )
            values["market_comparison"] = market_comparison
            values["quantity_market_options"] = [
                {
                    "index": index,
                    "market": item["market"],
                    "price_unit": item["price_unit"],
                    "quantity_units": supported_quantity_units(item["price_unit"]),
                }
                for index, item in enumerate(market_comparison)
            ]
            quantity_rows: list[dict[str, Any]] = []
            quantity_note = "Select exactly one market and a supported quantity unit to calculate quantity scenarios."
            range_market_index = None
            if selected["range_market_index"]:
                try:
                    range_market_index = int(selected["range_market_index"])
                except ValueError:
                    raise InputError("Choose one market for quantity analysis.") from None
                if range_market_index < 0 or range_market_index >= len(market_comparison):
                    raise InputError("Choose a market available in the current filters.")
            elif len(selected["markets"]) == 1:
                matching_indices = [
                    index for index, item in enumerate(market_comparison)
                    if item["market"] == selected["markets"][0]
                ]
                if len(matching_indices) == 1:
                    range_market_index = matching_indices[0]

            values["selected_range_market_index"] = range_market_index
            if range_market_index is not None:
                predicted = market_comparison[range_market_index]
                allowed_units = supported_quantity_units(predicted["price_unit"])
                range_unit = selected["range_quantity_unit"] or selected["quantity_unit"]
                if range_unit not in allowed_units:
                    quantity_note = "The selected source price unit does not support the chosen quantity unit."
                else:
                    q_min = read_nonnegative_number(selected["range_minimum_quantity"], "Minimum quantity", allow_zero=False)
                    q_max = read_nonnegative_number(selected["range_maximum_quantity"], "Maximum quantity", allow_zero=False)
                    q_step = read_nonnegative_number(selected["range_quantity_step"], "Quantity step", allow_zero=False)
                    range_transport = read_nonnegative_number(
                        selected["range_transport_cost"], "Transportation cost", allow_zero=True
                    )
                    quantity_rows = make_quantity_range(
                        predicted["estimated_price_source_units"], predicted["price_unit"],
                        range_unit, q_min, q_max, q_step, range_transport,
                    )
                    for row in quantity_rows:
                        row["market"] = predicted["market"]
                    quantity_note = "Transportation cost is user-entered and held fixed across this quantity range."
            values["quantity_range"] = quantity_rows
            values["quantity_note"] = quantity_note
            report_inputs = {**selected, "market": selected["markets"]}
            report_id = _register_report(_make_report_payload(
                report_inputs, market_comparison, filtered, quantity, selected["quantity_unit"], transport_value,
                quantity_rows=quantity_rows, quantity_note=quantity_note,
            ))
            session["latest_report_id"] = report_id
            values["report_id"] = report_id
    except InputError as exc:
        values["error"] = str(exc)
    return render_template(
        "visual_analysis.html",
        **_base_context("visual", states=states_for_analysis(MARKET_DATA) if MARKET_DATA is not None else [],
                        commodities=_choices(), quantity_units=_quantity_units(filtered), filters=selected, **values),
    ), 400 if values["error"] else 200


@app.get("/reports")
def reports():
    report_id = session.get("latest_report_id")
    available = report_id in REPORT_CACHE if report_id else False
    return render_template("reports.html", **_base_context("reports", report_id=report_id if available else None))


@app.get("/results")
def saved_results():
    report_id = session.get("latest_report_id")
    payload = REPORT_CACHE.get(report_id) if report_id else None
    recommendation = _recommendation_for_markets(payload.get("markets", [])) if payload else {"available": False, "markets": []}
    return render_template(
        "saved_results.html",
        **_base_context("results", payload=payload, recommendation=recommendation,
                        report_id=report_id if payload else None),
    )


@app.get("/reports/<report_id>/<file_format>")
def download_report(report_id: str, file_format: str):
    payload = REPORT_CACHE.get(report_id)
    if payload is None:
        abort(404)
    builders = {"csv": (build_csv_report, "text/csv", "agrivalue_analysis.csv"),
                "xlsx": (build_workbook_report, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "agrivalue_analysis.xlsx"),
                "pdf": (build_pdf_report, "application/pdf", "agrivalue_analysis.pdf")}
    if file_format not in builders:
        abort(404)
    builder, mime_type, filename = builders[file_format]
    try:
        stream = builder(payload)
    except Exception as exc:
        app.logger.exception("Could not generate %s report", file_format)
        return render_template("error.html", **_base_context("reports", message=f"Could not generate the report: {exc}")), 500
    return send_file(stream, mimetype=mime_type, as_attachment=True, download_name=filename)


@app.get("/model-info")
def model_info():
    return render_template("model_info.html", **_base_context("model", metadata=_metadata(), model_error=MODEL_ERROR))


@app.get("/dataset-summary")
def dataset_summary():
    if RAW_DATA is None or MARKET_DATA is None:
        return render_template("dataset_summary.html", **_base_context("dataset", summary=None, cleaning=None)), 503
    return render_template(
        "dataset_summary.html",
        **_base_context("dataset", summary=make_dataset_summary(RAW_DATA), cleaning=inspect_cleaning(RAW_DATA)),
    )


@app.get("/about")
def about():
    return render_template("about.html", **_base_context("about"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", **_base_context("", message="That page could not be found.")), 404


@app.errorhandler(500)
def internal_error(_error):
    return render_template("error.html", **_base_context("", message="The app could not complete that request.")), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
