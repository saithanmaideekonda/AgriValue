document.addEventListener("DOMContentLoaded", () => {
  const ids = { state: "visual-state", district: "visual-district", market: "visual-markets", commodity: "visual-commodity", variety: "visual-variety", grade: "visual-grade" };
  const controls = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, document.getElementById(id)]));
  const filters = window.agriVisualFilters || {};
  const form = document.getElementById("visual-filter-form");
  const quantityUnit = document.getElementById("visual-quantity-unit");
  const quantityHelp = document.getElementById("visual-unit-help");

  const selectedMarkets = () => controls.market ? Array.from(controls.market.selectedOptions).map((item) => item.value).filter(Boolean) : [];
  const params = (values = {}) => {
    const query = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((entry) => query.append(key, entry));
      else if (value) query.set(key, value);
    });
    return query;
  };
  async function get(path, values = {}) {
    const query = params(values);
    const response = await fetch(path + (query.size ? "?" + query.toString() : ""));
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not load matching dataset values.");
    return result;
  }
  function fill(control, values, placeholder, selected = [], multiple = false) {
    if (!control) return;
    control.replaceChildren(new Option(placeholder, ""));
    values.forEach((value) => {
      const option = new Option(value, value);
      option.selected = multiple ? selected.includes(value) : value === selected;
      control.add(option);
    });
    control.disabled = values.length === 0;
  }
  function context() {
    return {
      state: controls.state?.value || "", district: controls.district?.value || "",
      market: selectedMarkets(), commodity: controls.commodity?.value || "",
      variety: controls.variety?.value || "", grade: controls.grade?.value || "",
    };
  }
  function showError(error) {
    if (!form) return;
    let alert = form.querySelector(".visual-filter-error");
    if (!alert) {
      alert = document.createElement("div");
      alert.className = "alert alert-error visual-filter-error";
      form.prepend(alert);
    }
    alert.textContent = error.message || "Could not load matching dataset values.";
  }
  async function loadStates(selected = "") {
    const data = await get("/api/states");
    fill(controls.state, data.states || [], "Choose a state", selected);
    if (controls.state?.value) await loadDistricts(filters.district || "");
  }
  async function loadDistricts(selected = "") {
    for (const key of ["district", "market", "commodity", "variety", "grade"]) {
      fill(controls[key], [], key === "market" ? "Choose markets to compare, or leave blank for all" : "Choose " + key, key === "market" ? [] : "", key === "market");
    }
    if (!controls.state?.value) return;
    const data = await get("/api/districts", { state: controls.state.value });
    fill(controls.district, data.districts || [], "Choose a district", selected);
    if (controls.district?.value) await loadMarkets(filters.markets || []);
  }
  async function loadMarkets(selected = []) {
    for (const key of ["market", "commodity", "variety", "grade"]) {
      fill(controls[key], [], key === "market" ? "Choose markets to compare, or leave blank for all" : "Choose " + key, key === "market" ? [] : "", key === "market");
    }
    if (!controls.district?.value) return;
    const data = await get("/api/markets", { state: controls.state.value, district: controls.district.value });
    fill(controls.market, data.markets || [], "Choose markets to compare, or leave blank for all", selected, true);
    await loadCommodities(filters.commodity || "");
  }
  async function loadCommodities(selected = "") {
    for (const key of ["commodity", "variety", "grade"]) fill(controls[key], [], "Choose " + key);
    if (!controls.state?.value || !controls.district?.value) return;
    const data = await get("/api/commodities", { state: controls.state.value, district: controls.district.value, market: selectedMarkets() });
    fill(controls.commodity, data.commodities || [], "Choose a commodity", selected);
    if (controls.commodity?.value) await refineMarkets(filters.markets || []);
  }
  async function refineMarkets(selected = selectedMarkets()) {
    const data = await get("/api/markets", {
      state: controls.state.value, district: controls.district.value,
      commodity: controls.commodity.value, variety: controls.variety.value, grade: controls.grade.value,
    });
    const options = data.markets || [];
    const compatible = selected.filter((market) => options.includes(market));
    fill(controls.market, options, "Choose markets to compare, or leave blank for all", compatible, true);
    const hint = document.getElementById("visual-market-help");
    if (hint && selected.length !== compatible.length) hint.textContent = "Markets without records for these filters were cleared. Leave blank to include all matching markets.";
    await loadVarieties(filters.variety || "");
  }
  async function loadVarieties(selected = "") {
    for (const key of ["variety", "grade"]) fill(controls[key], [], "Any available " + key);
    if (!controls.commodity?.value) return;
    const data = await get("/api/varieties", context());
    fill(controls.variety, data.varieties || [], "Any available variety", selected);
    await loadGrades(filters.grade || "");
  }
  async function loadGrades(selected = "") {
    fill(controls.grade, [], "Any available grade");
    if (!controls.commodity?.value) return;
    const data = await get("/api/grades", context());
    fill(controls.grade, data.grades || [], "Any available grade", selected);
    await loadQuantityUnits();
  }
  async function loadQuantityUnits() {
    fill(quantityUnit, [], "Choose matching unit");
    if (!controls.commodity?.value) return;
    const data = await get("/api/quantity-units", context());
    const units = data.quantity_units || [];
    fill(quantityUnit, units, "No safe common unit", filters.quantity_unit || (units.includes("kg") ? "kg" : units[0] || ""));
    if (quantityHelp) {
      const source = (data.price_units || []).join(", ") || "not available";
      quantityHelp.textContent = units.length
        ? "Source price unit(s): " + source + ". Supported quantity unit(s): " + units.join(", ") + "."
        : "Source price unit(s): " + source + ". No single safe quantity unit is available for this filter selection.";
    }
  }
  if (form && Object.values(controls).every(Boolean)) {
    controls.state.addEventListener("change", () => { filters.district = ""; filters.markets = []; filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = ""; loadDistricts("").catch(showError); });
    controls.district.addEventListener("change", () => { filters.markets = []; filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = ""; loadMarkets([]).catch(showError); });
    controls.market.addEventListener("change", () => { filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = ""; loadCommodities("").catch(showError); });
    controls.commodity.addEventListener("change", () => { filters.commodity = controls.commodity.value; filters.variety = ""; filters.grade = ""; filters.quantity_unit = ""; refineMarkets([]).catch(showError); });
    controls.variety.addEventListener("change", () => { filters.variety = controls.variety.value; filters.grade = ""; filters.quantity_unit = ""; refineMarkets(selectedMarkets()).catch(showError); });
    controls.grade.addEventListener("change", () => { filters.grade = controls.grade.value; filters.quantity_unit = ""; refineMarkets(selectedMarkets()).catch(showError); });
    loadStates(filters.state || "").catch(showError);
  }

  const data = window.agriVisualData || {};
  const chartsAvailable = typeof Chart !== "undefined";
  if (chartsAvailable) {
    Chart.defaults.color = "#607267";
    Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, sans-serif";
  }
  const green = "#2c7a52";
  const money = (value) => Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  function fallback(id, message) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    canvas.hidden = true;
    const note = document.createElement("p");
    note.className = "chart-fallback";
    note.textContent = message;
    canvas.parentElement.append(note);
  }

  const comparisons = data.market_comparison || [];
  const priceChart = document.getElementById("market-comparison-chart");
  if (chartsAvailable && priceChart && comparisons.length) new Chart(priceChart, {
    type: "bar",
    data: { labels: comparisons.map((row) => row.market), datasets: [{ label: "Estimated Market Price", data: comparisons.map((row) => row.estimated_price_source_units), backgroundColor: "#5a9869", borderRadius: 5 }] },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { title: { display: true, text: "Market" }, ticks: { maxRotation: 55, minRotation: 20 } }, y: { title: { display: true, text: "Estimated price (source units)" }, beginAtZero: false } }, plugins: { tooltip: { callbacks: { label: (ctx) => money(ctx.raw) + " " + (comparisons[ctx.dataIndex]?.price_unit || "") } } } },
  });
  else if (chartsAvailable && priceChart) fallback("market-comparison-chart", "Insufficient matching markets for comparison.");

  const quantities = data.quantity_range || [];
  const quantityChart = document.getElementById("quantity-range-chart");
  if (chartsAvailable && quantityChart && quantities.length) new Chart(quantityChart, {
    type: "line",
    data: { labels: quantities.map((row) => money(row.quantity)), datasets: [{ label: "Estimated Net Return", data: quantities.map((row) => row.estimated_net_return), borderColor: green, backgroundColor: "rgba(44,122,82,.12)", fill: true, tension: .12, pointRadius: 4 }] },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { title: { display: true, text: "Quantity (" + (quantities[0]?.quantity_unit || "") + ")" } }, y: { title: { display: true, text: "Estimated net return (₹)" }, beginAtZero: false } }, plugins: { tooltip: { callbacks: { label: (ctx) => "₹" + money(ctx.raw) } } } },
  });

  const marketSelect = document.getElementById("range-market");
  const unitSelect = document.getElementById("range-quantity-unit");
  function setUnitsForMarket() {
    if (!marketSelect || !unitSelect) return;
    const option = marketSelect.selectedOptions[0];
    const units = (option?.dataset.units || "").split(",").filter(Boolean);
    unitSelect.replaceChildren(new Option(units.length ? "Choose quantity unit" : "No supported unit", ""));
    units.forEach((unit) => unitSelect.add(new Option(unit, unit)));
    unitSelect.disabled = units.length === 0;
    if (units.length) {
      const preferred = filters.range_quantity_unit || filters.quantity_unit || (units.includes("kg") ? "kg" : units[0]);
      unitSelect.value = units.includes(preferred) ? preferred : units[0];
    }
  }
  if (marketSelect) {
    marketSelect.addEventListener("change", setUnitsForMarket);
    if (marketSelect.value) setUnitsForMarket();
  }
});

