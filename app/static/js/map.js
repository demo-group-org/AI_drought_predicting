const RISK_COLORS = {
  Low: "#6E9A5A",
  Moderate: "#D9A441",
  High: "#B5502F",
  Unknown: "#9C9686",
};
const SAFE_COLOR = "#3B6FA0";
let currentScenario = "worst_case";
let selectedZoneId = null;
let zoneMarkers = {}; // zone id -> {marker, data}

const map = L.map("risk-map").setView([-29.5, 27.5], 5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const panel = document.getElementById("zone-panel");

function severityTagHtml(severity) {
  const color = RISK_COLORS[severity] || RISK_COLORS.Unknown;
  return `<span class="severity-tag" style="background:${color}22;color:${color}">${severity} risk</span>`;
}

function fmtZAR(value) {
  if (value === null || value === undefined) return "-";
  return "R" + Math.round(value).toLocaleString();
}

function renderMiniChart(series) {
  if (!series || !series.length) return "";
  const max = Math.max(...series.map((p) => p.drought_stress_index || 0), 1);
  const bars = series
    .map((p) => {
      const height = Math.max(2, Math.round(((p.drought_stress_index || 0) / max) * 60));
      return `<div style="height:${height}px" title="${p.week_start}: DSI ${p.drought_stress_index}"></div>`;
    })
    .join("");
  return `<div class="forecast-mini-chart">${bars}</div>`;
}

function renderWeatherHtml(weather) {
  if (!weather || weather.temp_c === null || weather.temp_c === undefined) return "";
  const iconUrl = weather.icon ? `https://openweathermap.org/img/wn/${weather.icon}.png` : "";
  return `
    <div class="weather-chip">
      ${iconUrl ? `<img src="${iconUrl}" alt="${weather.description || ''}" width="36" height="36">` : ""}
      <div>
        <strong>${Math.round(weather.temp_c)}&deg;C</strong>
        <span class="muted">${weather.description || weather.main || "Live conditions"}</span>
      </div>
    </div>
  `;
}

function renderInteractiveAutomationSection(detail) {
  const audits = detail.automation_audits || [];
  const latest = audits[0];

  const activeDevicesHtml = latest && latest.actions && latest.actions.length
    ? `<div style="margin:0.6rem 0;padding:0.6rem;background:#F7E1D9;border-left:4px solid #B5502F;border-radius:6px">
         <strong style="color:#7A3320"><i class="fa-solid fa-bolt"></i> Active Lambda / IoT State (${latest.severity.toUpperCase()})</strong>
         <div class="muted" style="font-size:0.78rem;margin-bottom:0.3rem">Triggered: ${latest.trigger_name} at ${latest.created_at}</div>
         <ul style="margin:0.2rem 0 0;padding-left:1.2rem;font-size:0.85rem">
           ${latest.actions.map((a) => `<li><strong>${a.device}</strong>: ${a.action} ${a.value !== null && a.value !== undefined ? `(${a.value})` : ""}</li>`).join("")}
         </ul>
       </div>`
    : `<p class="muted" style="font-size:0.85rem">No automated Lambda mitigations triggered for this zone yet.</p>`;

  const auditHistoryHtml = audits.length > 1
    ? `<details style="margin-top:0.5rem;font-size:0.82rem">
         <summary style="cursor:pointer;font-weight:600">View recent automation audit log (${audits.length})</summary>
         <ul style="margin:0.4rem 0 0;padding-left:1.1rem">
           ${audits.map((a) => `<li><code>${a.created_at}</code> — <strong>${a.severity}</strong> (${a.trigger_name})</li>`).join("")}
         </ul>
       </details>`
    : "";

  return `
    <h3 style="margin-top:1.2rem"><i class="fa-solid fa-satellite-dish"></i> Live IoT & Lambda Control</h3>
    ${activeDevicesHtml}
    <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-top:0.6rem">
      <button class="btn btn--primary" style="padding:0.4rem 0.7rem;font-size:0.8rem;background:#B5502F;color:#fff"
              onclick="triggerZoneAutomation(${detail.zone_id}, 'critical')">
        <i class="fa-solid fa-triangle-exclamation"></i> Trigger Critical
      </button>
      <button class="btn" style="padding:0.4rem 0.7rem;font-size:0.8rem;background:#D9A441;color:#16220F"
              onclick="triggerZoneAutomation(${detail.zone_id}, 'warning')">
        <i class="fa-solid fa-gauge-high"></i> Warning
      </button>
      <button class="btn" style="padding:0.4rem 0.7rem;font-size:0.8rem;background:#6E9A5A;color:#fff"
              onclick="triggerZoneAutomation(${detail.zone_id}, 'normal')">
        <i class="fa-solid fa-rotate-left"></i> Reset
      </button>
    </div>
    ${auditHistoryHtml}
  `;
}

async function triggerZoneAutomation(zoneId, severity) {
  const actionsBySeverity = {
    critical: [
      { device: "water_valve", action: "throttle", value: 35 },
      { device: "solar_pump", action: "start", value: "emergency" },
    ],
    warning: [
      { device: "water_valve", action: "throttle", value: 15 },
      { device: "solar_pump", action: "start", value: "standard" },
    ],
    normal: [
      { device: "water_valve", action: "open", value: 100 },
      { device: "solar_pump", action: "stop", value: "standby" },
    ],
  };

  await fetch(`/api/zones/${zoneId}/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      severity: severity,
      trigger_name: `interactive_${severity}_override`,
      actions: actionsBySeverity[severity] || [],
    }),
  });

  await refreshMapMarkers();
  await showZoneDetail(zoneId);
}

function renderRichZonePanel(detail) {
  const cur = detail.current || {};
  const first = detail.series[0];
  const last = detail.series[detail.series.length - 1];
  const alertsHtml = (detail.alerts || [])
    .map((a) => `
      <div class="alert-card ${a.severity === 'warning' ? 'alert-card--warning' : ''}">
        <strong>${a.severity ? a.severity.toUpperCase() : 'ALERT'}</strong> lead time ${a.lead_time_days ?? '-'} days
        <p style="margin:0.3rem 0 0">${a.message}</p>
        ${a.recommended_actions && a.recommended_actions.length ? `<ul>${a.recommended_actions.map((x) => `<li>${x}</li>`).join("")}</ul>` : ""}
      </div>
    `)
    .join("");
  const relocationHtml = (detail.relocation_recommendations || [])
    .map((r) => `
      <div class="suggestion">
        <strong>${r.city}</strong>${r.province ? "   " + r.province : ""}   ${r.distance_km ?? '?'} km away<br>
        Grazing capacity there: ${r.projected_grazing_capacity_pct ?? '?'}%   relocation cost ~${fmtZAR(r.estimated_relocation_cost_zar)}<br>
        <span class="muted">${r.reason || ""}</span>
      </div>
    `)
    .join("");
  const scenarioLabel = detail.scenario === "worst_case" ? "Worst-case (drought continues)" : "Best-case (no drought)";
  
  panel.innerHTML = `
    <h3>${detail.zone}</h3>
    ${detail.province ? `<p class="muted" style="margin-top:-0.6rem">${detail.province}</p>` : ""}
    ${severityTagHtml(detail.severity_level)}
    ${detail.is_relocation_target ? '<p class="muted"><i class="fa-solid fa-flag" style="color:#3B6FA0"></i> Suggested relocation destination</p>' : ""}
    ${renderWeatherHtml(detail.weather)}
    <div class="forecast-row"><span>Current drought stress index</span><strong>${cur.drought_stress_index ?? '-'}</strong></div>
    <div class="forecast-row"><span>Water point level</span><strong>${cur.water_point_level_pct_now ?? '-'}%</strong></div>
    <div class="forecast-row"><span>Feed days remaining</span><strong>${cur.feed_days_remaining_now ?? '-'}</strong></div>
    <div class="forecast-row"><span>Livestock at risk now</span><strong>${cur.estimated_livestock_at_risk_now ?? '-'}</strong></div>
    <div class="forecast-row"><span>Projected financial impact</span><strong>${fmtZAR(cur.projected_financial_impact_zar)}</strong></div>
    <div class="forecast-row"><span>Trend</span><strong>${cur.trend || '-'}</strong></div>
    <h3 style="margin-top:1rem">${scenarioLabel}   ${detail.forecast_horizon_weeks || detail.series.length}-week outlook</h3>
    ${renderMiniChart(detail.series)}
    <div class="forecast-row"><span>Week 1 DSI</span><strong>${first ? first.drought_stress_index : '-'}</strong></div>
    <div class="forecast-row"><span>Final week DSI</span><strong>${last ? last.drought_stress_index : '-'}</strong></div>
    <div class="forecast-row"><span>Final week grazing capacity</span><strong>${last ? last.grazing_capacity_pct + '%' : '-'}</strong></div>
    <div class="forecast-row"><span>Final week feed days left</span><strong>${last ? last.feed_days_remaining : '-'}</strong></div>
    ${alertsHtml ? `<h3 style="margin-top:1rem">Early-warning alerts</h3>${alertsHtml}` : ""}
    ${relocationHtml ? `<h3 style="margin-top:1rem"><i class="fa-solid fa-arrow-right-arrow-left"></i> Consider relocating to</h3>${relocationHtml}` : ""}
    ${renderInteractiveAutomationSection(detail)}
  `;
}

function renderLegacyZonePanel(detail) {
  const forecast = detail.forecast || {};
  let suggestionsHtml = "";
  if (detail.suggestions && detail.suggestions.length) {
    suggestionsHtml = `
      <h3><i class="fa-solid fa-arrow-right-arrow-left"></i> Consider these areas instead</h3>
      ${detail.suggestions.map((s) => `
        <div class="suggestion">
          <strong>${s.zone}</strong>${s.district ? "   " + s.district : ""}   ${s.distance_km ?? '?'} km away<br>
          Risk score: ${s.risk_score} (${s.severity_level})
        </div>
      `).join("")}
    `;
  }
  panel.innerHTML = `
    <h3>${detail.zone}</h3>
    ${severityTagHtml(detail.severity_level)}
    <div class="forecast-row"><span>Current risk score</span><strong>${detail.risk_score}</strong></div>
    <div class="forecast-row"><span>Grazing stress</span><strong>${detail.grazing_stress_score}</strong></div>
    <div class="forecast-row"><span>Water stress</span><strong>${detail.water_stress_score}</strong></div>
    <div class="forecast-row"><span>30-day forecast</span><strong>${forecast["30"] ?? "-"}</strong></div>
    <div class="forecast-row"><span>60-day forecast</span><strong>${forecast["60"] ?? "-"}</strong></div>
    <div class="forecast-row"><span>90-day forecast</span><strong>${forecast["90"] ?? "-"}</strong></div>
    ${detail.severity_level === "High" ? '<p class="muted" style="margin-top:0.8rem"><i class="fa-solid fa-circle-exclamation"></i> Not recommended for new grazing right now.</p>' : ""}
    ${suggestionsHtml}
    ${renderInteractiveAutomationSection(detail)}
  `;
}

async function showZoneDetail(zoneId) {
  selectedZoneId = zoneId;
  const res = await fetch(`/api/zones/${zoneId}?scenario=${currentScenario}`);
  const detail = await res.json();
  if (detail.source === "rich_dataset") {
    renderRichZonePanel(detail);
  } else {
    renderLegacyZonePanel(detail);
  }
}

function markerStyleFor(zone) {
  if (zone.is_relocation_target) {
    return { color: SAFE_COLOR, fillColor: SAFE_COLOR, radius: 9 };
  }
  const color = RISK_COLORS[zone.severity_level] || RISK_COLORS.Unknown;
  return { color, fillColor: color, radius: 10 };
}

async function loadZones() {
  const res = await fetch("/api/zones");
  const zones = await res.json();
  const points = [];
  zones.forEach((zone) => {
    const style = markerStyleFor(zone);
    const marker = L.circleMarker([zone.latitude, zone.longitude], {
      radius: style.radius,
      color: style.color,
      fillColor: style.fillColor,
      fillOpacity: 0.8,
      weight: 2,
    }).addTo(map);
    const label = zone.is_relocation_target
      ? `${zone.name}   relocation option`
      : `${zone.name}   ${zone.severity_level}`;
    marker.bindTooltip(label);
    marker.on("click", () => showZoneDetail(zone.id));
    zoneMarkers[zone.id] = { marker, data: zone };
    points.push([zone.latitude, zone.longitude]);
  });
  if (points.length) {
    map.fitBounds(points, { padding: [40, 40], maxZoom: 9 });
  }
}

async function refreshMapMarkers() {
  const res = await fetch("/api/zones");
  const zones = await res.json();
  zones.forEach((zone) => {
    const existing = zoneMarkers[zone.id];
    if (existing) {
      const style = markerStyleFor(zone);
      existing.marker.setStyle({
        color: style.color,
        fillColor: style.fillColor,
        radius: style.radius,
      });
      const label = zone.is_relocation_target
        ? `${zone.name} - relocation option`
        : `${zone.name} - ${zone.severity_level}`;
      existing.marker.setTooltipContent(label);
      existing.data = zone;
    }
  });
}

document.querySelectorAll(".scenario-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".scenario-btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    currentScenario = btn.dataset.scenario;
    if (selectedZoneId) showZoneDetail(selectedZoneId);
  });
});

loadZones();

// Poll every 10 seconds to keep map markers synced with AWS Lambda / IoT triggers
setInterval(() => {
  refreshMapMarkers();
  if (selectedZoneId) showZoneDetail(selectedZoneId);
}, 10000);