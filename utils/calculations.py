"""Input validation and net-return arithmetic shared by the web routes."""

from __future__ import annotations

import math
from typing import Any


class InputError(ValueError):
    """A friendly validation message suitable for the browser."""


def read_nonnegative_number(value: Any, label: str, *, allow_zero: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InputError(f"Enter a valid {label.lower()}.") from None
    if not math.isfinite(number):
        raise InputError(f"Enter a finite {label.lower()}.")
    if number < 0 or (number == 0 and not allow_zero):
        wording = "zero or greater" if allow_zero else "greater than zero"
        raise InputError(f"{label} must be {wording}.")
    if number > 1_000_000_000:
        raise InputError(f"{label} is above the supported limit.")
    return number


def price_denominator(price_unit: Any) -> str | None:
    """Return a supported denominator for a source unit without guessing."""
    if not isinstance(price_unit, str) or "/" not in price_unit:
        return None
    denominator = price_unit.rsplit("/", 1)[-1].strip().casefold()
    denominator = denominator.replace("₹", "").replace("rs", "").strip(" .")
    aliases = {
        "kg": "kg", "kilogram": "kg", "kilograms": "kg",
        "quintal": "quintal", "quintals": "quintal", "qtl": "quintal",
        "number": "number", "numbers": "number", "no": "number", "nos": "number",
    }
    return aliases.get(denominator)


def supported_quantity_units(price_unit: Any) -> list[str]:
    denominator = price_denominator(price_unit)
    if denominator == "quintal":
        return ["kg", "quintal"]
    if denominator == "kg":
        return ["kg"]
    if denominator == "number":
        return ["number"]
    return []


def quantity_in_price_units(quantity: float, quantity_unit: str, price_unit: str) -> float:
    """Convert only explicitly supported weight/count unit combinations."""
    denominator = price_denominator(price_unit)
    unit = str(quantity_unit or "").strip().casefold()
    if denominator == "kg" and unit == "kg":
        return float(quantity)
    if denominator == "quintal" and unit == "kg":
        return float(quantity) / 100.0
    if denominator == "quintal" and unit == "quintal":
        return float(quantity)
    if denominator == "number" and unit == "number":
        return float(quantity)
    raise InputError(
        f"The source price unit {price_unit!r} cannot be safely combined with quantity in {quantity_unit!r}."
    )


def calculate_financials(
    source_price: float, price_unit: str, quantity: float,
    quantity_unit: str, transport_cost: float,
) -> dict[str, float]:
    """Calculate expected revenue and estimated net return in rupees."""
    price = read_nonnegative_number(source_price, "Estimated price", allow_zero=False)
    qty = read_nonnegative_number(quantity, "Quantity", allow_zero=False)
    transport = read_nonnegative_number(transport_cost, "Transportation cost", allow_zero=True)
    matching_quantity = quantity_in_price_units(qty, quantity_unit, price_unit)
    revenue = price * matching_quantity
    return {
        "expected_revenue": float(revenue),
        "transport_cost": float(transport),
        "estimated_net_return": float(revenue - transport),
    }


def recalculate_returns(
    markets: list[dict[str, Any]], quantity: float, quantity_unit: str, transport_cost: float
) -> list[dict[str, Any]]:
    """Recalculate each selected market using its actual source price unit."""
    if not markets:
        raise InputError("At least one compared market is required.")
    output = []
    for market in markets:
        name = str(market.get("market", "")).strip()
        if not name:
            raise InputError("A market name is missing from the comparison.")
        results = calculate_financials(
            market.get("estimated_price_source_units"), str(market.get("price_unit", "")),
            quantity, quantity_unit, transport_cost,
        )
        output.append(
            {
                "market": name,
                "price_unit": market.get("price_unit"),
                "quantity": float(quantity),
                "quantity_unit": quantity_unit,
                **results,
            }
        )
    return output


def make_quantity_range(
    source_price: float,
    price_unit: str,
    quantity_unit: str,
    minimum_quantity: float,
    maximum_quantity: float,
    quantity_step: float,
    transport_cost: float,
) -> list[dict[str, Any]]:
    """Calculate a fixed-transport-cost quantity table from one selected estimate."""
    minimum = read_nonnegative_number(minimum_quantity, "Minimum quantity", allow_zero=False)
    maximum = read_nonnegative_number(maximum_quantity, "Maximum quantity", allow_zero=False)
    step = read_nonnegative_number(quantity_step, "Quantity step", allow_zero=False)
    transport = read_nonnegative_number(transport_cost, "Transportation cost", allow_zero=True)
    if maximum < minimum:
        raise InputError("Maximum quantity must be greater than or equal to minimum quantity.")
    count = int(math.floor((maximum - minimum) / step + 1e-10)) + 1
    if count > 1001:
        raise InputError("Use a larger quantity step so the range contains no more than 1,001 rows.")
    previous_return: float | None = None
    rows: list[dict[str, Any]] = []
    for index in range(count):
        quantity = minimum + index * step
        financials = calculate_financials(source_price, price_unit, quantity, quantity_unit, transport)
        revenue = financials["expected_revenue"]
        net_return = financials["estimated_net_return"]
        rows.append({
            "quantity": float(quantity),
            "estimated_price": float(source_price),
            "price_unit": price_unit,
            "quantity_unit": quantity_unit,
            "expected_revenue": float(revenue),
            "transport_cost": float(financials["transport_cost"]),
            "estimated_net_return": float(net_return),
            "difference_from_previous": None if previous_return is None else float(net_return - previous_return),
        })
        previous_return = net_return
    return rows
