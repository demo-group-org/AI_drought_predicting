function fmtZAR(value) {
  if (value === null || value === undefined) return "-";
  return "R" + Math.round(value).toLocaleString();
}

function renderWeatherChip(container, weather) {
  if (!weather || weather.temp_c === null || weather.temp_c === undefined) {
    container.innerHTML = `<span class="muted"><i class="fa-solid fa-cloud"></i> Live weather not available yet -- it refreshes automatically shortly after the server starts (needs <code>OPENWEATHER_API_KEY</code> set in <code>.env</code>).</span>`;
    return;
  }
  const iconUrl = weather.icon ? `https://openweathermap.org/img/wn/${weather.icon}.png` : "";
  container.innerHTML = `
    ${iconUrl ? `<img src="${iconUrl}" alt="${weather.description || ''}" width="32" height="32">` : ""}
    <strong>${Math.round(weather.temp_c)}&deg;C</strong>
    <span class="muted">${weather.description || weather.main || ""}</span>
  `;
}

function weekdayLabel(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short" });
}

async function loadForecastCalendar(farmId) {
  const container = document.querySelector(`[data-calendar-for="${farmId}"]`);
  if (!container) return;
  try {
    const res = await fetch(`/api/farms/${farmId}/forecast`);
    const data = await res.json();
    if (!data.days || !data.days.length) {
      container.innerHTML = `<span class="muted">Short-term forecast not available right now (needs <code>OPENWEATHER_API_KEY</code> set in <code>.env</code>, and a live internet connection from the server).</span>`;
      return;
    }
    container.innerHTML = data.days
      .map((d) => `
        <div class="forecast-day">
          <span class="forecast-day__label">${weekdayLabel(d.date)}</span>
          ${d.icon ? `<img src="https://openweathermap.org/img/wn/${d.icon}.png" width="36" height="36" alt="">` : ""}
          <span class="forecast-day__temp">${Math.round(d.temp_max)}&deg; / ${Math.round(d.temp_min)}&deg;</span>
        </div>
      `)
      .join("");
  } catch (err) {
    container.innerHTML = `<span class="muted">Couldn't load the forecast right now.</span>`;
  }
}

async function loadProjection(farmId, scenario) {
  const target = document.querySelector(`[data-projection-for="${farmId}"]`);
  if (!target) return;
  target.innerHTML = `<span class="muted"><i class="fa-solid fa-spinner fa-spin"></i> Simulating...</span>`;

  try {
    const res = await fetch(`/api/farms/${farmId}/advisor?scenario=${scenario}`);
    const data = await res.json();

    const weatherContainer = document.querySelector(`[data-weather-for="${farmId}"]`);
    if (weatherContainer) renderWeatherChip(weatherContainer, data.weather);

    const p = data.projection;

    if (!p) {
      target.innerHTML = `<span class="muted">No week-by-week forecast is loaded for this zone in the dataset.</span>`;
      return;
    }

    const scenarioLabel = scenario === "worst_case" ? "if the drought continues" : "if good rains return";
    target.innerHTML = `
      <strong>Projected outcome over ${p.weeks} weeks, ${scenarioLabel}:</strong><br>
      Drought stress index would reach <strong>${p.final_drought_stress_index}</strong>/100 ·
      grazing capacity <strong>${p.final_grazing_capacity_pct}%</strong> ·
      feed days remaining <strong>${p.final_feed_days_remaining}</strong> ·
      estimated financial impact <strong>${fmtZAR(p.final_financial_impact_zar)}</strong>
    `;
  } catch (err) {
    target.innerHTML = `<span class="muted">Couldn't load that simulation right now.</span>`;
  }
}

document.querySelectorAll(".advisor-card").forEach((card) => {
  const farmId = card.dataset.farmId;
  const buttons = card.querySelectorAll(".scenario-btn");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      loadProjection(farmId, btn.dataset.scenario);
    });
  });

  // Show the worst-case projection immediately so the card isn't empty on load.
  loadProjection(farmId, "worst_case");
  loadForecastCalendar(farmId);
});

// ---- Chatbot widget ----
const chatbotForm = document.getElementById("chatbot-form");
const chatbotInput = document.getElementById("chatbot-input");
const chatbotLog = document.getElementById("chatbot-log");

function appendChatbotMessage(text, fromBot) {
  const div = document.createElement("div");
  div.className = "chatbot-msg " + (fromBot ? "chatbot-msg--bot" : "chatbot-msg--user");
  div.textContent = text;
  chatbotLog.appendChild(div);
  chatbotLog.scrollTop = chatbotLog.scrollHeight;
}

if (chatbotForm) {
  chatbotForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = chatbotInput.value.trim();
    if (!question) return;
    appendChatbotMessage(question, false);
    chatbotInput.value = "";

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question }),
      });
      const data = await res.json();
      appendChatbotMessage(data.reply, true);
    } catch (err) {
      appendChatbotMessage("Sorry, I couldn't reach the server just now.", true);
    }
  });
}