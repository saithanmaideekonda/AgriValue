document.addEventListener("DOMContentLoaded", () => {
  const marketRows = window.agriValueResults || [];
  const chartData = window.agriValueCharts || {};
  let quantityRangeRows = window.agriValueQuantityRange || [];
  const reportId = window.agriValueReportId || "";
  const currency = (value) => value === null || value === undefined || !Number.isFinite(Number(value))
    ? "Unavailable"
    : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(value));
  const number = (value) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(Number(value));
  const sourcePrice = (value, unit) => value === null || value === undefined ? "Unavailable" : number(value) + " " + (unit || "");
  function emptyChart(id, message) {
    const canvas = document.getElementById(id);
    const holder = canvas?.closest(".chart-canvas");
    if (!canvas || !holder) return;
    canvas.hidden = true;
    holder.classList.add("chart-canvas-empty");
    const note = document.createElement("p");
    note.className = "chart-empty chart-fallback";
    note.textContent = message;
    if (!holder.querySelector(".chart-empty")) holder.append(note);
  }
  if (typeof Chart === "undefined") {
    document.querySelectorAll(".chart-canvas canvas").forEach((canvas) => emptyChart(canvas.id, "The chart library could not load."));
    return;
  }
  Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, sans-serif";
  Chart.defaults.color = "#607267";
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = "#173d2b";
  Chart.defaults.plugins.tooltip.padding = 10;
  const green = "#2c7a52";
  const palette = [green, "#a3c850", "#77a6c9", "#e2ad53", "#6eb5a5", "#db846c", "#729078"];

  function drawBar(id, rows, title, unitLabel, valueForTooltip, limit = 30) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const usable = (rows || []).slice(0, limit);
    if (!usable.length) {
      emptyChart(id, "Insufficient matching observations for this chart.");
      return;
    }
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: usable.map((item) => item.label),
        datasets: [{ label: title, data: usable.map((item) => item.value), backgroundColor: usable.map((_, i) => palette[i % palette.length]), borderRadius: 5 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: "x",
        scales: { x: { title: { display: true, text: "Category" }, ticks: { maxRotation: 45, autoSkip: true } }, y: { title: { display: true, text: unitLabel }, beginAtZero: false } },
        plugins: { tooltip: { callbacks: { label: (ctx) => valueForTooltip(usable[ctx.dataIndex], ctx.raw) } } },
      },
    });
  }

  const priceCanvas = document.getElementById("price-chart");
  const priceRows = marketRows.filter((item) => item.estimated_price_source_units !== null
    && item.estimated_price_source_units !== undefined
    && Number.isFinite(Number(item.estimated_price_source_units)));
  if (priceCanvas && priceRows.length) new Chart(priceCanvas, {
    type: "bar",
    data: { labels: priceRows.map((item) => item.market), datasets: [{ label: "Estimated Modal Price", data: priceRows.map((item) => item.estimated_price_source_units), backgroundColor: green, borderRadius: 5 }] },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { title: { display: true, text: "Market" }, ticks: { maxRotation: 45, autoSkip: true } }, y: { title: { display: true, text: "Estimated Modal Price (source units)" }, beginAtZero: false } }, plugins: { tooltip: { callbacks: { label: (ctx) => sourcePrice(ctx.raw, priceRows[ctx.dataIndex]?.price_unit) } } } },
  });
  const returnValues = marketRows.map((item) => item.estimated_net_return);
  const returnCanvas = document.getElementById("return-chart");
  let returnChart = null;
  function updateReturnChart(values = returnValues) {
    if (!returnCanvas) return;
    const valid = values.some((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
    if (!valid) {
      if (!returnCanvas.hidden) emptyChart("return-chart", "Estimated net return is unavailable for the selected price units.");
      return;
    }
    if (returnCanvas.hidden) {
      returnCanvas.hidden = false;
      returnCanvas.closest(".chart-canvas")?.querySelector(".chart-empty")?.remove();
    }
    const dataset = { label: "Estimated Net Return", data: values, backgroundColor: "#78a45b", borderRadius: 5 };
    if (returnChart) {
      returnChart.data.datasets[0].data = values;
      returnChart.update();
    } else {
      returnChart = new Chart(returnCanvas, {
        type: "bar", data: { labels: marketRows.map((item) => item.market), datasets: [dataset] },
        options: { responsive: true, maintainAspectRatio: false, scales: { x: { title: { display: true, text: "Market" }, ticks: { maxRotation: 45 } }, y: { title: { display: true, text: "Estimated Net Return (₹)" }, beginAtZero: false } }, plugins: { tooltip: { callbacks: { label: (ctx) => currency(ctx.raw) } } } },
      });
    }
  }
  updateReturnChart();
  window.updateNetReturnChart = updateReturnChart;

  const recommendationList = document.getElementById("recommendation-market-list");
  const recommendationUnavailable = document.getElementById("recommendation-unavailable");
  const recommendationExplanation = document.getElementById("recommendation-explanation");
  function updateRecommendation(rows) {
    if (!recommendationList) return;
    const valid = (rows || []).filter((item) => {
      const revenue = item.expected_revenue;
      const netReturn = item.estimated_net_return;
      return String(item.market || "").trim() !== ""
        && revenue !== null && revenue !== undefined && netReturn !== null && netReturn !== undefined
        && Number.isFinite(Number(revenue)) && Number.isFinite(Number(netReturn))
        && item.estimated_price_source_units !== null && item.estimated_price_source_units !== undefined
        && Number.isFinite(Number(item.estimated_price_source_units));
    });
    if (!valid.length) {
      recommendationList.hidden = true;
      if (recommendationUnavailable) recommendationUnavailable.hidden = false;
      if (recommendationExplanation) recommendationExplanation.hidden = true;
      return;
    }
    const highest = Math.max(...valid.map((item) => Number(item.estimated_net_return)));
    const winners = valid.filter((item) => Number(item.estimated_net_return) === highest);
    recommendationList.replaceChildren();
    winners.forEach((item) => {
      const card = document.createElement("article");
      card.className = "recommendation-market";
      card.dataset.recommendationMarket = "";
      const heading = document.createElement("div");
      heading.className = "recommendation-market-heading";
      const name = document.createElement("h3");
      name.className = "recommendation-market-name";
      name.textContent = item.market || "Market name unavailable";
      heading.append(name);
      if (winners.length > 1) {
        const tie = document.createElement("span");
        tie.className = "recommendation-tie";
        tie.textContent = "Joint highest estimated net return";
        heading.append(tie);
      }
      card.append(heading);
      const metrics = document.createElement("dl");
      metrics.className = "recommendation-metrics";
      [
        ["Estimated Price", sourcePrice(item.estimated_price_source_units, item.price_unit), "price"],
        ["Quantity", number(item.quantity) + " " + (item.quantity_unit || ""), "quantity"],
        ["Expected Revenue", currency(item.expected_revenue), "revenue"],
        ["Transport Cost", currency(item.transport_cost), "transport"],
        ["Estimated Net Return", currency(item.estimated_net_return), "net-return"],
      ].forEach(([label, value, key]) => {
        const entry = document.createElement("div");
        if (key === "net-return") entry.classList.add("recommendation-net");
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.dataset.recommendationField = key;
        description.textContent = value;
        entry.append(term, description);
        metrics.append(entry);
      });
      card.append(metrics);
      recommendationList.append(card);
    });
    recommendationList.hidden = false;
    if (recommendationUnavailable) recommendationUnavailable.hidden = true;
    if (recommendationExplanation) recommendationExplanation.hidden = false;
  }

  const stabilityLabels = chartData.source_stability_labels || [];
  if (stabilityLabels.length > 1) {
    drawBar(
      "stability-chart",
      stabilityLabels.map((item) => ({ label: item.label, value: item.records, records: item.records })),
      "Source Price Stability Classification", "Matching records", (item, value) => number(value) + " records · source label",
    );
  }

  const quantityInput = document.getElementById("whatif-quantity");
  const unitInput = document.getElementById("whatif-unit");
  const transportInput = document.getElementById("whatif-transport");
  const rangeMarketInput = document.getElementById("range-market");
  const rangeMinimumInput = document.getElementById("range-minimum");
  const rangeMaximumInput = document.getElementById("range-maximum");
  const rangeStepInput = document.getElementById("range-step");
  const rangeCanvas = document.getElementById("quantity-range-chart");
  const rangeBody = document.getElementById("quantity-range-body");
  const recalculateButton = document.getElementById("recalculate-returns");
  const message = document.getElementById("whatif-message");
  let rangeChart = null;
  function updateQuantityRange(rows) {
    quantityRangeRows = rows || [];
    if (rangeBody) {
      rangeBody.replaceChildren();
      quantityRangeRows.forEach((item) => {
        const row = document.createElement("tr");
        const cells = [
          number(item.quantity) + " " + (item.quantity_unit || ""),
          sourcePrice(item.estimated_price, item.price_unit),
          currency(item.expected_revenue), currency(item.transport_cost), currency(item.estimated_net_return),
          item.difference_from_previous === null || item.difference_from_previous === undefined
            ? "—" : currency(item.difference_from_previous),
        ];
        cells.forEach((value) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        });
        rangeBody.append(row);
      });
    }
    if (!rangeCanvas) return;
    if (!quantityRangeRows.length) {
      emptyChart("quantity-range-chart", "Insufficient data for this quantity range.");
      if (rangeChart) { rangeChart.destroy(); rangeChart = null; }
      return;
    }
    const labels = quantityRangeRows.map((item) => number(item.quantity));
    const values = quantityRangeRows.map((item) => item.estimated_net_return);
    if (rangeCanvas.hidden) {
      rangeCanvas.hidden = false;
      rangeCanvas.closest(".chart-canvas")?.classList.remove("chart-canvas-empty");
      rangeCanvas.closest(".chart-canvas")?.querySelector(".chart-empty")?.remove();
    }
    if (!rangeChart) {
      rangeChart = new Chart(rangeCanvas, {
        type: "line",
        data: { labels, datasets: [{ label: "Estimated Net Return", data: values, borderColor: green, backgroundColor: "rgba(44,122,82,.14)", fill: true, tension: .18, pointRadius: 3 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: { title: { display: true, text: "Quantity (" + (quantityRangeRows[0].quantity_unit || "") + ")" } }, y: { title: { display: true, text: "Estimated Net Return (₹)" } } },
          plugins: { tooltip: { callbacks: { label: (ctx) => {
            const row = quantityRangeRows[ctx.dataIndex];
            return ["Estimated Net Return: " + currency(row.estimated_net_return), "Estimated Price: " + sourcePrice(row.estimated_price, row.price_unit), "Expected Revenue: " + currency(row.expected_revenue), "Transport Cost: " + currency(row.transport_cost)];
          } } } },
        },
      });
    } else {
      rangeChart.data.labels = labels;
      rangeChart.data.datasets[0].data = values;
      rangeChart.options.scales.x.title.text = "Quantity (" + (quantityRangeRows[0].quantity_unit || "") + ")";
      rangeChart.update();
    }
  }
  updateQuantityRange(quantityRangeRows);

  let requestNumber = 0;
  async function recalculate() {
    if (!quantityInput || !unitInput || !transportInput || !rangeMarketInput || !rangeMinimumInput || !rangeMaximumInput || !rangeStepInput) return;
    const requestId = ++requestNumber;
    const quantity = Number(quantityInput.value);
    const quantityUnit = unitInput.value;
    const transport = Number(transportInput.value);
    const minimum = Number(rangeMinimumInput.value);
    const maximum = Number(rangeMaximumInput.value);
    const step = Number(rangeStepInput.value);
    const rangeMarketIndex = Number(rangeMarketInput.value);
    if (!Number.isFinite(quantity) || quantity <= 0 || !quantityUnit || !Number.isFinite(transport) || transport < 0
      || !Number.isFinite(minimum) || minimum <= 0 || !Number.isFinite(maximum) || maximum < minimum
      || !Number.isFinite(step) || step <= 0 || !Number.isInteger(rangeMarketIndex)) {
      if (message) message.textContent = "Enter valid positive quantity-range values, a supported unit, and a transport cost of zero or more.";
      return;
    }
    if (message) message.textContent = "Recalculating values…";
    if (recalculateButton) recalculateButton.disabled = true;
    try {
      const response = await fetch("/calculate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quantity, quantity_unit: quantityUnit, transport_cost: transport,
          report_id: reportId,
          markets: marketRows.map((item) => ({
            market: item.market, estimated_price_source_units: item.estimated_price_source_units,
            price_unit: item.price_unit,
          })),
          quantity_range: {
            market_index: rangeMarketIndex, minimum_quantity: minimum,
            maximum_quantity: maximum, quantity_step: step,
          },
        }),
      });
      const result = await response.json();
      if (requestId !== requestNumber) return;
      if (!response.ok) throw new Error(result.error || "Could not recalculate the selected values.");
      result.markets.forEach((value, index) => {
        const item = marketRows[index];
        if (!item) return;
        item.expected_revenue = value.expected_revenue;
        item.transport_cost = value.transport_cost;
        item.estimated_net_return = value.estimated_net_return;
        const row = document.querySelector('[data-market-row="' + index + '"]');
        if (row) {
          row.querySelector(".quantity-cell").textContent = number(quantity) + " " + quantityUnit;
          row.querySelector(".revenue-cell").textContent = currency(value.expected_revenue);
          row.querySelector(".transport-cell").textContent = currency(value.transport_cost);
          row.querySelector(".return-cell").textContent = currency(value.estimated_net_return);
        }
      });
      updateRecommendation(result.markets.map((value, index) => ({ ...marketRows[index], ...value })));
      document.getElementById("kpi-quantity").textContent = number(quantity) + " " + quantityUnit;
      document.getElementById("kpi-transport").textContent = currency(transport);
      updateReturnChart(marketRows.map((item) => item.estimated_net_return));
      updateQuantityRange(result.quantity_range);
      if (message) message.textContent = "Market totals and quantity scenarios were recalculated with the same estimated prices. The model price estimates did not change.";
    } catch (error) {
      if (requestId === requestNumber && message) message.textContent = error.message;
    } finally {
      if (recalculateButton) recalculateButton.disabled = false;
    }
  }
  recalculateButton?.addEventListener("click", recalculate);
});

