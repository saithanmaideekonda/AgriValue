document.addEventListener("DOMContentLoaded", () => {
  const summary = window.agriValueSummary;
  if (!summary || typeof Chart === "undefined") return;
  Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif";
  Chart.defaults.color = "#607267";
  Chart.defaults.plugins.legend.display = false;
  const colors = ["#2c7a52", "#a3c850", "#77a6c9", "#e2ad53", "#6eb5a5", "#db846c", "#729078"];
  const topRows = (source, limit = 12) => Object.entries(source || {}).slice(0, limit).map(([label, value]) => ({ label, value }));
  function draw(id, rows) {
    const canvas = document.getElementById(id);
    if (!canvas || !rows.length) return;
    new Chart(canvas, {
      type: "bar",
      data: { labels: rows.map((row) => row.label), datasets: [{
        data: rows.map((row) => row.value),
        backgroundColor: rows.map((_, index) => colors[index % colors.length]),
        borderRadius: 5, maxBarThickness: 24,
      }] },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: "y",
        scales: { x: { beginAtZero: true, grid: { color: "#edf1ed" } }, y: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: { label: (context) => `${new Intl.NumberFormat("en-IN").format(context.raw)} records` } } },
      },
    });
  }
  const distributions = summary.distributions || {};
  draw("commodity-summary-chart", topRows(distributions.Commodity));
  draw("market-summary-chart", topRows(distributions.Market));
  draw("state-summary-chart", topRows(distributions.State));
});
