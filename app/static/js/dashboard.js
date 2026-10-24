let allZones = [];
let dsiChart = null;
let weatherChart = null;
const SEVERITY_COLORS = { Low: "#6E9A5A", Moderate: "#D9A441", High: "#B5502F", Unknown: "#9C9686" };
const RELOCATION_COLOR = "#3B6FA0";

function riskClass(zone) {
  if (zone.is_relocation_target) return "is-relocation";
  const level = (zone.severity_level || "").toLowerCase();
  if (level === "high") return "risk-high";
  if (level === "moderate") return "risk-moderate";
  return "risk-low";
}

function colorFor(zone) {
  return zone.is_relocation_target ? RELOCATION_COLOR : (SEVERITY_COLORS[zone.severity_level] || SEVERITY_COLORS.Unknown);
}

function renderZoneCards(zones) {
  const grid = document.getElementById("zone-overview-grid");
  if (!zones.length) {
    grid.innerHTML = `<p class="muted">No zones loaded yet.</p>`;
    return;
  }
  grid.innerHTML = zones
    .map((z) => {
      const cls = riskClass(z);
      const badge = z.is_relocation_target ? "Relocation option" : (z.severity_level || "Unknown");
      const w = z.weather;
      const weatherHtml = w && w.temp_c !== null && w.temp_c !== undefined
        ? `<div class="zone-card__weather">
             ${w.icon ? `<img src="https://openweathermap.org/img/wn/${w.icon}.png" width="28" height="28" alt="">` : ""}
             <span>${Math.round(w.temp_c)}&deg;C</span>
           </div>`
        : "";

      const auto = z.latest_automation;
      const autoHtml = auto
        ? `<div style="margin-top:0.55rem;padding:0.4rem 0.5rem;background:var(--paper);border-radius:6px;font-size:0.75rem">
             <strong><i class="fa-solid fa-bolt" style="color:#B5502F"></i> IoT: ${auto.severity.toUpperCase()}</strong><br>
             ${(auto.actions || []).map((a) => `${a.device}: ${a.action} (${a.value ?? ""})`).join(" | ")}
           </div>`
        : `<div class="muted" style="margin-top:0.5rem;font-size:0.75rem">No active IoT override</div>`;

      return `
        <div class="zone-card ${cls}">
          <div class="zone-card__name">${z.name}</div>
          <div class="zone-card__meta">${z.province || z.district || ""}</div>
          <div class="zone-card__dsi">${z.risk_score ?? "-"}</div>
          <div class="zone-card__dsi-label">Drought stress index</div>
          <span class="zone-card__badge">${badge}</span>
          ${weatherHtml}
          ${autoHtml}
        </div>
      `;
    })
    .join("");
}

function sortZones(zones, mode) {
  const copy = [...zones];
  if (mode === "risk-desc") copy.sort((a, b) => (b.risk_score ?? -1) - (a.risk_score ?? -1));
  if (mode === "risk-asc") copy.sort((a, b) => (a.risk_score ?? 999) - (b.risk_score ?? 999));
  if (mode === "name") copy.sort((a, b) => a.name.localeCompare(b.name));
  return copy;
}

function renderDsiChart(zones) {
  const ctx = document.getElementById("dsi-chart");
  if (!ctx) return;
  const labels = zones.map((z) => z.name);
  const data = zones.map((z) => z.risk_score ?? 0);
  const colors = zones.map(colorFor);
  if (!dsiChart) {
    dsiChart = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: "Drought stress index", data, backgroundColor: colors }] },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, max: 100 }, x: { ticks: { autoSkip: false, maxRotation: 60, minRotation: 30 } } },
      },
    });
  } else {
    dsiChart.data.labels = labels;
    dsiChart.data.datasets[0].data = data;
    dsiChart.data.datasets[0].backgroundColor = colors;
    dsiChart.update();
  }
}

function renderWeatherChart(zones) {
  const ctx = document.getElementById("weather-chart");
  if (!ctx) return;
  const withWeather = zones.filter((z) => z.weather && z.weather.temp_c !== null && z.weather.temp_c !== undefined);
  const labels = withWeather.map((z) => z.name);
  const temps = withWeather.map((z) => z.weather.temp_c);
  const dsis = withWeather.map((z) => z.risk_score ?? 0);
  if (!labels.length) return;
  if (!weatherChart) {
    weatherChart = new Chart(ctx, {
      data: {
        labels,
        datasets: [
          { type: "bar", label: "Temperature (°C)", data: temps, backgroundColor: "#D9A441", yAxisID: "y" },
          { type: "line", label: "Drought stress index", data: dsis, borderColor: "#B5502F", backgroundColor: "#B5502F", yAxisID: "y1", tension: 0.3 },
        ],
      },
      options: {
        responsive: true,
        scales: {
          y: { position: "left", title: { display: true, text: "°C" } },
          y1: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false }, title: { display: true, text: "DSI" } },
        },
      },
    });
  } else {
    weatherChart.data.labels = labels;
    weatherChart.data.datasets[0].data = temps;
    weatherChart.data.datasets[1].data = dsis;
    weatherChart.update();
  }
}

async function loadZoneOverview() {
  const res = await fetch("/api/zones");
  allZones = await res.json();
  renderZoneCards(sortZones(allZones, document.getElementById("sort-select").value));
  if (typeof Chart !== "undefined") {
    renderDsiChart(sortZones(allZones, "risk-desc"));
    renderWeatherChart(allZones);
  }
}

document.getElementById("sort-select").addEventListener("change", (e) => {
  renderZoneCards(sortZones(allZones, e.target.value));
});

loadZoneOverview();

// Keep dashboard updated every 10 seconds with AWS Lambda/IoT webhook triggers
setInterval(loadZoneOverview, 10000);