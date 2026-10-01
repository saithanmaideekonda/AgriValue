"""Exports for the current AgriValue analysis only."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


def _market_export_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = payload.get("inputs", {})
    rows = []
    for item in payload.get("markets", []):
        rows.append({
            "Commodity": inputs.get("commodity"), "State": item.get("state"),
            "District": item.get("district"), "Market": item.get("market"),
            "Variety": item.get("variety"), "Grade": item.get("grade"),
            "Quantity": inputs.get("quantity", inputs.get("minimum_quantity")),
            "Quantity Unit": inputs.get("quantity_unit"),
            "Estimated Price": item.get("estimated_price_source_units"),
            "Price Unit": item.get("price_unit"),
            "Expected Revenue (₹)": item.get("expected_revenue"),
            "User-Entered Transport Cost (₹)": item.get("transport_cost"),
            "Estimated Net Return (₹)": item.get("estimated_net_return"),
            "Source Price Stability Label": item.get("source_stability_label"),
            "Market Activity": item.get("activity"), "Market Size": item.get("market_size"),
            "Historical Average Modal Price": item.get("observed_average"),
            "Historical Minimum Price": item.get("observed_minimum"),
            "Historical Maximum Price": item.get("observed_maximum"),
            "Historical Records": item.get("record_count"),
            "Latest Observation Date": item.get("latest_observation_date"),
        })
    return rows


def build_csv_report(payload: dict[str, Any]) -> BytesIO:
    stream = BytesIO()
    rows = _market_export_rows(payload)
    inputs = payload.get("inputs", {})
    if not rows:
        rows.append({
            "Analysis Type": "Filtered historical summary",
            "Commodity": inputs.get("commodity"), "State": inputs.get("state"),
            "District": inputs.get("district"), "Market": inputs.get("market"),
            "Variety": inputs.get("variety"), "Grade": inputs.get("grade"),
            "Quantity": inputs.get("quantity", inputs.get("minimum_quantity")),
            "Quantity Unit": inputs.get("quantity_unit"),
            "Price Unit": payload.get("price_unit_label"),
            "User-Entered Transport Cost (₹)": inputs.get("transport_cost"),
            "Historical Records": payload.get("historical_record_count", 0),
            "Disclaimer": "Estimated net return is based on selected inputs and estimated market price and is not a guarantee of actual profit.",
        })
    for item in payload.get("quantity_range", []):
        rows.append({
            "Analysis Type": "Quantity range",
            "Commodity": inputs.get("commodity"), "State": inputs.get("state"),
            "District": inputs.get("district"), "Market": item.get("market", inputs.get("market")),
            "Variety": inputs.get("variety"), "Grade": inputs.get("grade"),
            "Quantity": item.get("quantity"),
            "Quantity Unit": item.get("quantity_unit", inputs.get("quantity_unit")),
            "Estimated Price": item.get("estimated_price"),
            "Price Unit": item.get("price_unit"),
            "Expected Revenue (₹)": item.get("expected_revenue"),
            "User-Entered Transport Cost (₹)": item.get("transport_cost"),
            "Estimated Net Return (₹)": item.get("estimated_net_return"),
            "Difference from Previous Quantity (₹)": item.get("difference_from_previous"),
        })
    for row in rows:
        row.setdefault("Analysis Type", "Market result")
    pd.DataFrame(rows).to_csv(stream, index=False, encoding="utf-8-sig")
    stream.seek(0)
    return stream


def build_workbook_report(payload: dict[str, Any]) -> BytesIO:
    stream = BytesIO()
    inputs = payload.get("inputs", {})
    input_rows = [{
        "Field": key.replace("_", " ").title(), "Value": ", ".join(value) if isinstance(value, list) else value
    } for key, value in inputs.items()]
    sheets = {
        "Input Details": pd.DataFrame(input_rows),
        "Market Results": pd.DataFrame(_market_export_rows(payload)),
        "Stability Data": pd.DataFrame(payload.get("stability", [])),
        "Quantity Range Data": pd.DataFrame(payload.get("quantity_range", [])),
    }
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        for title, frame in sheets.items():
            if frame.empty:
                frame = pd.DataFrame([{"Information": payload.get("analysis_note", "No records available for this section.")}])
            frame.to_excel(writer, sheet_name=title, index=False)
            worksheet = writer.sheets[title]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cells in worksheet.columns:
                width = min(42, max(12, max(len(str(cell.value or "")) for cell in cells) + 2))
                worksheet.column_dimensions[cells[0].column_letter].width = width
    stream.seek(0)
    return stream


def _pdf_graph(
    labels: list[str], values: list[float], title: str, *, line: bool = False,
    x_label: str = "Category", y_label: str = "Value",
):
    """Draw a small vector chart using only the real values passed by the app."""
    from reportlab.lib import colors
    from reportlab.platypus import Flowable

    class DataChart(Flowable):
        def __init__(self):
            super().__init__()
            self.width = 490
            self.height = 155

        def draw(self):
            canvas = self.canv
            left, bottom, width, height = 76, 54, 387, 75
            canvas.setFont("Helvetica-Bold", 10)
            canvas.setFillColor(colors.HexColor("#244d35"))
            canvas.drawString(0, 142, title[:80])
            canvas.setStrokeColor(colors.HexColor("#9cab9d"))
            canvas.line(left, bottom, left, bottom + height)
            canvas.line(left, bottom, left + width, bottom)
            if not values:
                canvas.setFont("Helvetica", 9)
                canvas.setFillColor(colors.grey)
                canvas.drawString(left, bottom + 55, "Insufficient data for this chart.")
                return
            low, high = min(0.0, min(values)), max(0.0, max(values))
            span = high - low
            if span == 0:
                span = abs(high) or 1
                low = max(0, low - span * .1)
                span = max(values) - low or 1
            count = len(values)
            x_step = width / max(count, 1)
            zero_y = bottom + 7 + ((0 - low) / span) * (height - 14)
            points = []
            for i, value in enumerate(values):
                x = left + (i + .5) * x_step
                y = bottom + 7 + ((value - low) / span) * (height - 14)
                points.append((x, y))
                if not line:
                    bar_w = min(22, x_step * .55)
                    canvas.setFillColor(colors.HexColor("#5a9869"))
                    canvas.rect(x - bar_w / 2, min(zero_y, y), bar_w, max(1, abs(y - zero_y)), fill=1, stroke=0)
                canvas.setFillColor(colors.HexColor("#557462"))
                canvas.setFont("Helvetica", 6.5)
                label = (labels[i] if i < len(labels) else str(i + 1))[:18]
                canvas.saveState()
                canvas.translate(x - 2, bottom - 4)
                canvas.rotate(45)
                canvas.drawString(0, 0, label)
                canvas.restoreState()
            if line and points:
                canvas.setFillColor(colors.HexColor("#2c7a52"))
                if len(points) > 1:
                    canvas.setStrokeColor(colors.HexColor("#2c7a52"))
                    canvas.setLineWidth(2)
                    path = canvas.beginPath()
                    path.moveTo(*points[0])
                    for point in points[1:]:
                        path.lineTo(*point)
                    canvas.drawPath(path)
                for x, y in points:
                    canvas.circle(x, y, 2.5, fill=1, stroke=0)
            canvas.setStrokeColor(colors.HexColor("#9cab9d"))
            canvas.line(left, zero_y, left + width, zero_y)
            canvas.saveState()
            canvas.translate(9, bottom + height / 2)
            canvas.rotate(90)
            canvas.setFont("Helvetica", 7)
            canvas.drawCentredString(0, 0, y_label[:48])
            canvas.restoreState()
            canvas.setFont("Helvetica", 7)
            canvas.drawCentredString(left + width / 2, 3, x_label[:50])
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.grey)
            canvas.drawRightString(left - 5, bottom + height - 8, f"{high:.2f}")
            canvas.drawRightString(left - 5, bottom, f"{low:.2f}")

    return DataChart()


def build_pdf_report(payload: dict[str, Any]) -> BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AgriTitle", parent=styles["Title"], textColor=colors.HexColor("#174f36"), alignment=TA_LEFT, spaceAfter=5))
    styles.add(ParagraphStyle(name="SmallNote", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#56645a")))
    styles.add(ParagraphStyle(name="AgriSection", parent=styles["Heading2"], fontSize=11, leading=13, spaceBefore=5, spaceAfter=4, textColor=colors.HexColor("#244d35")))
    story = [Paragraph("AgriValue", styles["AgriTitle"]), Paragraph("Market price and net return analysis report", styles["Heading2"]), Spacer(1, 6)]
    inputs = payload.get("inputs", {})
    input_rows = [["Selected input", "Value"]]
    for key, value in inputs.items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            display = ", ".join(map(str, value[:6]))
            if len(value) > 6:
                display += f" and {len(value) - 6} more"
        else:
            display = str(value)
        input_rows.append([key.replace("_", " ").title(), display])
    input_table = Table(input_rows, colWidths=[55 * mm, 115 * mm], repeatRows=1)
    input_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2e8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#234d34")), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d5dfd4")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [Paragraph("Input Details", styles["AgriSection"]), input_table, Spacer(1, 5), Paragraph("Market Comparison", styles["AgriSection"])]
    result_rows = [["Market", "District / State", "Estimated Price", "Price Unit", "Revenue (INR)", "Transport (INR)", "Net Return (INR)"]]
    for item in payload.get("markets", []):
        result_rows.append([
            str(item.get("market", ""))[:24], f"{item.get('district', '')}, {item.get('state', '')}"[:32],
            _fmt(item.get("estimated_price_source_units")), str(item.get("price_unit", "" )).replace("₹", "INR "), _fmt(item.get("expected_revenue")),
            _fmt(item.get("transport_cost")), _fmt(item.get("estimated_net_return")),
        ])
    results_table = Table(result_rows, colWidths=[28 * mm, 35 * mm, 22 * mm, 23 * mm, 25 * mm, 25 * mm, 28 * mm], repeatRows=1)
    results_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#174f36")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d5dfd4")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f9f5")])]))
    story += [results_table, Paragraph("Prices are shown in the Price Unit recorded for each market.", styles["SmallNote"]), Spacer(1, 5)]
    story.append(Paragraph("Price Stability Analysis", styles["AgriSection"]))
    stable = sorted(
        (row for row in payload.get("stability", []) if row.get("coefficient_of_variation") is not None),
        key=lambda row: row["coefficient_of_variation"], reverse=True,
    )
    if stable:
        shown = stable[:12]
        story.append(_pdf_graph([row["label"] + " " + row.get("price_unit", "") for row in shown], [float(row["coefficient_of_variation"]) for row in shown], "Observed Coefficient of Variation by Market", x_label="Market · source unit", y_label="CV (%)"))
        if len(stable) > len(shown):
            story.append(Paragraph("Graph shows the 12 highest observed CV values; the Excel stability sheet includes all matched categories.", styles["SmallNote"]))
        story.append(Paragraph("CV = sample standard deviation divided by mean, times 100. Higher CV means greater observed row-to-row variability; it is not a forecast of future risk.", styles["SmallNote"]))
    else:
        story.append(Paragraph("Insufficient data for stability analysis.", styles["SmallNote"]))
    story.append(Paragraph("Quantity Range Analysis", styles["AgriSection"]))
    quantity_rows = payload.get("quantity_range", [])
    if quantity_rows:
        quantity_unit = quantity_rows[0].get("quantity_unit", "")
        story.append(_pdf_graph([str(row["quantity"]) for row in quantity_rows], [float(row["estimated_net_return"]) for row in quantity_rows], "Quantity vs Estimated Net Return", line=True, x_label="Quantity (" + quantity_unit + ")", y_label="Estimated Net Return (INR)"))
        rows = [["Quantity", "Qty Unit", "Est. Price", "Price Unit", "Revenue (INR)", "Transport (INR)", "Net Return (INR)", "Difference (INR)"]]
        rows += [[_fmt(row.get("quantity")), row.get("quantity_unit", ""), _fmt(row.get("estimated_price")), str(row.get("price_unit", "")).replace("₹", "INR "), _fmt(row.get("expected_revenue")), _fmt(row.get("transport_cost")), _fmt(row.get("estimated_net_return")), _fmt(row.get("difference_from_previous"))] for row in quantity_rows]
        table = Table(rows, colWidths=[18 * mm, 17 * mm, 20 * mm, 24 * mm, 25 * mm, 24 * mm, 28 * mm, 27 * mm], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2e8")), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#d5dfd4")), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
        story.append(table)
    else:
        story.append(Paragraph(payload.get("quantity_note", "Insufficient data for quantity-range analysis."), styles["SmallNote"]))
    metadata = payload.get("model", {})
    story += [Spacer(1, 5), Paragraph("Model Information", styles["AgriSection"]), Paragraph(
        f"Model: {metadata.get('model_name', 'Unavailable')}; Target: {metadata.get('target_variable', 'Modal_Price')}; MAE: {_fmt(metadata.get('mae'))}; RMSE: {_fmt(metadata.get('rmse'))}; R-squared: {_fmt(metadata.get('r2'))}", styles["SmallNote"]),
        Spacer(1, 4), Paragraph("Disclaimer", styles["AgriSection"]), Paragraph(
            "Estimated net return is based on selected inputs and estimated market price and is not a guarantee of actual profit. Estimated prices are based on historical market data and model inputs; they are not guaranteed future prices. Transportation costs are user-entered estimates. Historical price variability describes available observations only.", styles["SmallNote"])]
    document.build(story)
    stream.seek(0)
    return stream


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)
