document.addEventListener("DOMContentLoaded", () => {
  const ids = { state: "state", district: "district", market: "markets", commodity: "commodity", variety: "variety", grade: "grade" };
  const controls = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, document.getElementById(id)]));
  const filters = window.agriValueFilters || {};
  const form = document.getElementById("analysis-form");
  const quantityUnit = document.getElementById("quantity_unit");
  const quantityHelp = document.getElementById("price-unit-help");
  const selectAll = document.getElementById("select-all-markets");
  const clearMarkets = document.getElementById("clear-markets");
  if (!form || Object.values(controls).some((item) => !item)) return;

  const selectedMarkets = () => Array.from(controls.market.selectedOptions).map((option) => option.value).filter(Boolean);
  const params = (values = {}) => {
    const query = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((entry) => query.append(key, entry));
      else if (value) query.set(key, value);
    });
    return query;
  };
  async function requestOptions(path, values = {}) {
    const query = params(values);
    const response = await fetch(path + (query.size ? "?" + query.toString() : ""));
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load matching dataset values.");
    return data;
  }
  function fill(control, values, placeholder, selected = [], multiple = false) {
    control.replaceChildren(new Option(placeholder, ""));
    values.forEach((value) => {
      const option = new Option(value, value);
      option.selected = multiple ? selected.includes(value) : value === selected;
      control.add(option);
    });
    control.disabled = values.length === 0;
  }
  function currentContext() {
    return {
      state: controls.state.value,
      district: controls.district.value,
      market: selectedMarkets(),
      commodity: controls.commodity.value,
      variety: controls.variety.value,
      grade: controls.grade.value,
    };
  }
  function showError(error) {
    let alert = form.querySelector(".analysis-filter-error");
    if (!alert) {
      alert = document.createElement("div");
      alert.className = "alert alert-error analysis-filter-error";
      form.prepend(alert);
    }
    alert.textContent = error.message || "Could not load matching dataset values.";
  }
  async function loadStates(selected = "") {
    const data = await requestOptions("/api/states");
    fill(controls.state, data.states || [], "Choose a state", selected);
    if (controls.state.value) await loadDistricts(filters.district || "");
  }
  async function loadDistricts(selected = "") {
    for (const key of ["district", "market", "commodity", "variety", "grade"]) {
      fill(controls[key], [], key === "market" ? "Choose one or more markets" : "Choose " + key, key === "market" ? [] : "", key === "market");
    }
    if (!controls.state.value) return;
    const data = await requestOptions("/api/districts", { state: controls.state.value });
    fill(controls.district, data.districts || [], "Choose a district", selected);
    if (controls.district.value) await loadMarkets(filters.markets || []);
  }
  async function loadMarkets(selected = []) {
    for (const key of ["market", "commodity", "variety", "grade"]) {
      fill(controls[key], [], key === "market" ? "Choose one or more markets" : "Choose " + key, key === "market" ? [] : "", key === "market");
    }
    if (!controls.district.value) return;
    const data = await requestOptions("/api/markets", { state: controls.state.value, district: controls.district.value });
    fill(controls.market, data.markets || [], "Choose one or more markets", selected, true);
    if (data.markets?.length) {
      selectAll.disabled = false;
      clearMarkets.disabled = false;
    }
    await loadCommodities(filters.commodity || "");
  }
  async function loadCommodities(selected = "") {
    for (const key of ["commodity", "variety", "grade"]) fill(controls[key], [], "Choose " + key);
    if (!controls.state.value || !controls.district.value) return;
    const data = await requestOptions("/api/commodities", {
      state: controls.state.value, district: controls.district.value, market: selectedMarkets(),
    });
    fill(controls.commodity, data.commodities || [], "Choose a commodity", selected);
    if (controls.commodity.value) await refineMarkets(filters.markets || []);
    else await refreshQuantityUnits();
  }
  async function refineMarkets(selected = selectedMarkets()) {
    const data = await requestOptions("/api/markets", {
      state: controls.state.value, district: controls.district.value, commodity: controls.commodity.value,
      variety: controls.variety.value, grade: controls.grade.value,
    });
    const options = data.markets || [];
    const compatible = selected.filter((market) => options.includes(market));
    fill(controls.market, options, "Choose one or more markets", compatible, true);
    const hint = document.getElementById("market-help");
    if (hint && selected.length !== compatible.length) hint.textContent = "Markets without records for this commodity were cleared. Choose from the matching market list.";
    await loadVarieties(filters.variety || "");
  }
  async function loadVarieties(selected = "") {
    for (const key of ["variety", "grade"]) fill(controls[key], [], "Any available " + key);
    if (!controls.commodity.value) return;
    const data = await requestOptions("/api/varieties", { ...currentContext() });
    fill(controls.variety, data.varieties || [], "Any available variety", selected);
    await loadGrades(filters.grade || "");
  }
  async function loadGrades(selected = "") {
    fill(controls.grade, [], "Any available grade");
    if (!controls.commodity.value) return;
    const data = await requestOptions("/api/grades", { ...currentContext() });
    fill(controls.grade, data.grades || [], "Any available grade", selected);
    await refreshQuantityUnits();
  }
  async function refreshQuantityUnits() {
    fill(quantityUnit, [], "Choose matching quantity unit");
    if (!controls.commodity.value) {
      if (quantityHelp) quantityHelp.textContent = "Choose a commodity to load its recorded source price unit and compatible quantity units.";
      return;
    }
    const data = await requestOptions("/api/quantity-units", currentContext());
    const units = data.quantity_units || [];
    const preferred = filters.quantity_unit || (units.includes("kg") ? "kg" : units[0] || "");
    fill(quantityUnit, units, "No safe unit available", preferred);
    if (quantityHelp) {
      const sourceUnits = (data.price_units || []).join(", ") || "not available";
      quantityHelp.textContent = units.length
        ? "Source price unit(s): " + sourceUnits + ". Supported quantity unit(s): " + units.join(", ") + "."
        : "Source price unit(s): " + sourceUnits + ". No single safe quantity unit is available for this selection.";
    }
  }

  controls.state.addEventListener("change", () => {
    filters.district = ""; filters.markets = []; filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = "";
    loadDistricts("").catch(showError);
  });
  controls.district.addEventListener("change", () => {
    filters.markets = []; filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = "";
    loadMarkets([]).catch(showError);
  });
  controls.market.addEventListener("change", () => {
    filters.commodity = ""; filters.variety = ""; filters.grade = ""; filters.quantity_unit = "";
    loadCommodities("").catch(showError);
  });
  controls.commodity.addEventListener("change", () => {
    filters.commodity = controls.commodity.value; filters.variety = ""; filters.grade = ""; filters.quantity_unit = "";
    refineMarkets(selectedMarkets()).catch(showError);
  });
  controls.variety.addEventListener("change", () => {
    filters.variety = controls.variety.value; filters.grade = ""; filters.quantity_unit = "";
    refineMarkets(selectedMarkets()).catch(showError);
  });
  controls.grade.addEventListener("change", () => {
    filters.grade = controls.grade.value; filters.quantity_unit = "";
    refineMarkets(selectedMarkets()).catch(showError);
  });
  selectAll?.addEventListener("click", () => Array.from(controls.market.options).forEach((option) => { option.selected = option.value !== ""; }));
  selectAll?.addEventListener("click", () => controls.market.dispatchEvent(new Event("change")));
  clearMarkets?.addEventListener("click", () => { Array.from(controls.market.options).forEach((option) => { option.selected = false; }); controls.market.dispatchEvent(new Event("change")); });
  loadStates(filters.state || "").catch(showError);
});

