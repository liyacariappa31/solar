const DEFAULTS = {
  sunlight_intensity: 760,
  temperature: 27,
  panel_capacity: 6.5,
  cloud_coverage: 18,
};

const themeToggle = document.querySelector("#theme-toggle");
const savedTheme = localStorage.getItem("solarwise.theme");

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const nextTheme = theme === "dark" ? "light" : "dark";
  themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
  themeToggle.title = `Switch to ${nextTheme} mode`;
  themeToggle.querySelector("use").setAttribute("href", theme === "dark" ? "#i-sun" : "#i-moon");
  updateChartTheme();
}

function updateChartTheme() {
  const textColor = document.documentElement.dataset.theme === "light" ? "#53675e" : "#9bb0b6";
  const gridColor = document.documentElement.dataset.theme === "light"
    ? "rgba(68, 96, 82, .16)"
    : "rgba(152, 184, 185, .14)";
  [productionChart, historyChart].forEach((chart) => {
    if (!chart) return;
    for (const axis of Object.values(chart.options.scales)) {
      axis.ticks.color = textColor;
      if (axis.grid) axis.grid.color = gridColor;
    }
    chart.update("none");
  });
}

const form = document.querySelector("#forecast-form");
const toast = document.querySelector("#toast");
const storedInputs = JSON.parse(sessionStorage.getItem("solarwise.inputs") || "null");
const inputs = Object.fromEntries(
  Object.keys(DEFAULTS).map((key) => [key, form?.elements[key]])
);
const rangeInputs = form ? {
  sunlight_intensity: form.elements.sunlight_range,
  temperature: form.elements.temperature_range,
  panel_capacity: form.elements.capacity_range,
  cloud_coverage: form.elements.cloud_range,
} : {};

let productionChart;
let historyChart;
let currentHourlyProfile;
let currentForecast;
let baselineForecast;
let modelVersion;
let historicalDay;
let historicalPlayback;
let currentHistoricalRecord;
let currentHistoricalTimestamp;
let playbackTimer;
let toastTimer;
let latestSolarNotification = "";
const PLAYBACK_INTERVAL_MS = 30000;

applyTheme(savedTheme === "light" ? "light" : "dark");
themeToggle.addEventListener("click", () => {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("solarwise.theme", nextTheme);
  applyTheme(nextTheme);
});

const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const safeNumber = (value, digits = 1) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
const fixedNumber = (value, digits = 2) =>
  Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
const setText = (selector, value) => document.querySelectorAll(selector).forEach((element) => {
  element.textContent = value;
});
const setHTML = (selector, value) => document.querySelectorAll(selector).forEach((element) => {
  element.innerHTML = value;
});

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3500);
}

function valuesFromForm() {
  if (!form) return currentForecast?.inputs || { ...DEFAULTS, ...storedInputs };
  return Object.fromEntries(
    Object.keys(DEFAULTS).map((key) => [key, Number(inputs[key].value)])
  );
}

if (form) {
  const initialInputs = { ...DEFAULTS, ...storedInputs };
  Object.keys(DEFAULTS).forEach((key) => {
    inputs[key].value = initialInputs[key];
    rangeInputs[key].value = initialInputs[key];
    const range = rangeInputs[key];
    inputs[key].addEventListener("input", () => {
      range.value = inputs[key].value;
      updateRangeFill(range);
      sessionStorage.setItem("solarwise.inputs", JSON.stringify(valuesFromForm()));
    });
    range.addEventListener("input", () => {
      inputs[key].value = range.value;
      updateRangeFill(range);
      sessionStorage.setItem("solarwise.inputs", JSON.stringify(valuesFromForm()));
    });
    updateRangeFill(range);
  });
}

function updateRangeFill(range) {
  const min = Number(range.min);
  const max = Number(range.max);
  const progress = ((Number(range.value) - min) / (max - min)) * 100;
  range.style.background = `linear-gradient(to right, #35d69c ${progress}%, #28404a ${progress}%)`;
}

function restoreForecastLabels() {
  document.querySelector(".app-shell")?.classList.remove("historical-playback");
  setText(".generation-kicker", document.querySelector(".page-dashboard")
    ? "TODAY'S GENERATION"
    : "PREDICTED DAILY GENERATION");
  setText("#generation-subtitle", "Your AI-powered daily estimate");
  setText("#carbon-label", document.querySelector(".page-dashboard") ? "CO₂ avoided today" : "CO₂ avoided");
  setText("#peak-label", "Peak solar window");
  setText(".capacity-kicker", "YOUR SYSTEM");
  setText("#capacity-caption", "Installed solar capacity");
  setText("#capacity-foot-label", "Connected and ready");
  setText(".capacity-card h3", "Panel capacity");
  setText(".weather-kicker", "LOCAL CONDITIONS");
  setText(".weather-today-card > .section-kicker", "TODAY'S CONDITIONS");
  setText(".weather-disclaimer", "Weather summaries use the conditions entered in your solar scenario.");
  setText(".sunlight-caption-label", "sunlight");
  setText(".temperature-caption-label", "Temperature");
  setText(".cloud-caption-label", "Cloud cover");
  setText(".performance-kicker", "ROOF READINESS");
  setText(".performance-title", "Efficiency");
  setText(".performance-score-label", "OUT OF 100");
  setText("#performance-note", "A quick read on how today's conditions suit your panels.");
  document.querySelector("#performance-note")?.removeAttribute("hidden");
  setText("#performance-foot-label", "Live model estimate");
  setText("#production-description", "Estimated energy by hour, based on your current conditions.");
  setText("#production-legend", "Predicted generation");
  document.querySelector(".chart-legend")?.removeAttribute("hidden");
  document.querySelector("#historical-chart-legend")?.setAttribute("hidden", "hidden");
  setText("#production-footnote", "Generation is modeled, not metered");
  setText("#weather-description", "Compare today's conditions with clear skies and cooler panels.");
  setText("#output-generation-description", "Estimated solar electricity for the day.");
  setText("#output-peak-label", "Peak solar window");
  setText("#output-carbon-label", "Estimated carbon avoided");
  setText("#output-confidence-label", "Forecast confidence");
  setText("#advisor-title", "A few thoughtful ways to get more.");
  setText("#advisor-intro", "Practical ideas shaped around your solar conditions — not a one-size-fits-all checklist.");
  setText("#scheduler-description", "Suggested times based on your predicted hourly solar output.");
  setText("#scheduler-note-text", "Planning guidance only. Actual generation and household demand vary.");
  setText("#model-context", `ML model v${modelVersion || "—"}`);
  document.querySelector(".efficiency-card .info-dot")?.setAttribute(
    "title",
    "A simple score based on cloud cover and heat-related performance impact.",
  );
  const formElements = document.querySelectorAll("#forecast-form input, #forecast-form button, #insight-dashboard form input, #insight-dashboard form select, #insight-dashboard form button");
  formElements.forEach((element) => { element.disabled = false; });
  document.querySelector("#refresh-button")?.removeAttribute("disabled");
}

function makeProductionChart(forecast, historicalTimestamp = currentHistoricalTimestamp) {
  currentHourlyProfile = forecast.hourly;
  if (!window.Chart) return;
  const context = document.querySelector("#production-chart");
  if (!context) return;
  const labels = forecast.hourly.map((point) => point.hour);
  const values = forecast.hourly.map((point) => point.generation_kwh);
  const highlightedHour = historicalTimestamp ? `${historicalTimestamp.slice(11, 13)}:00` : null;
  const pointRadius = labels.map((label) => label === highlightedHour ? 5 : 0);
  const pointBackgroundColor = labels.map((label) => label === highlightedHour ? "#e9fff5" : "#42dba0");
  const pointBorderColor = labels.map((label) => label === highlightedHour ? "#42dba0" : "#42dba0");
  const gradient = context.getContext("2d").createLinearGradient(0, 0, 0, 190);
  gradient.addColorStop(0, "rgba(49, 212, 154, .22)");
  gradient.addColorStop(1, "rgba(49, 212, 154, .01)");
  const config = {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: "#42dba0",
        backgroundColor: gradient,
        borderWidth: 2,
        fill: true,
        tension: 0.38,
        pointRadius,
        pointBackgroundColor,
        pointBorderColor,
        pointBorderWidth: 2,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: "#e5fff2",
        pointHoverBorderColor: "#42dba0",
        pointHoverBorderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#102b2b",
          padding: 10,
          displayColors: false,
          titleFont: { family: "DM Sans", size: 13, weight: "500" },
          bodyFont: { family: "DM Sans", size: 14, weight: "700" },
          callbacks: { label: (context) => ` ${context.parsed.y.toFixed(2)} kWh` },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: "#9bb0b6", font: { family: "DM Sans", size: 12 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(152, 184, 185, .14)", drawTicks: false },
          border: { display: false },
          ticks: { color: "#9bb0b6", padding: 8, font: { family: "DM Sans", size: 11 }, maxTicksLimit: 4, callback: (value) => `${value} kWh` },
        },
      },
    },
  };
  if (productionChart) {
    productionChart.data.labels = labels;
    productionChart.data.datasets[0].data = values;
    productionChart.data.datasets[0].pointRadius = pointRadius;
    productionChart.data.datasets[0].pointBackgroundColor = pointBackgroundColor;
    productionChart.data.datasets[0].pointBorderColor = pointBorderColor;
    productionChart.update("active");
  } else {
    productionChart = new Chart(context, config);
  }
}

document.querySelector("#chartjs-loader")?.addEventListener("load", () => {
  if (currentHourlyProfile) makeProductionChart({ hourly: currentHourlyProfile });
  if (document.querySelector("#history-chart")) {
    loadHistory().catch((error) => showToast(error.message));
  }
});

function renderForecast(data, { simulation = false, saved = false } = {}) {
  if (!historicalPlayback?.active) restoreForecastLabels();
  const comparison = baselineForecast || currentForecast;
  currentForecast = data;
  const generation = `${safeNumber(data.generation_kwh, 2)}<small> kWh</small>`;
  const carbon = `${safeNumber(data.carbon_avoided_kg)} kg`;
  const peak = `${data.peak_hour} – ${String(Number(data.peak_hour.slice(0, 2)) + 2).padStart(2, "0")}:00`;
  setHTML("#generation-value, #output-generation", generation);
  setText("#prediction-expected-value", safeNumber(data.generation_kwh, 2));
  setText("#carbon-value, #output-carbon-value", carbon);
  setText("#peak-value, #output-peak-value", peak);
  setText("#score-value", data.solar_fit_score);
  setText("#score-status", data.solar_fit_score >= 75 ? "Conditions look good" : data.solar_fit_score >= 50 ? "A mixed-sky kind of day" : "A little less sun today");
  document.querySelectorAll("#score-ring").forEach((ring) => {
    ring.style.background = `conic-gradient(#31d49a 0deg ${data.solar_fit_score * 3.6}deg, #16363b ${data.solar_fit_score * 3.6}deg 360deg)`;
  });
  setText("#confidence-value", `${data.confidence_percent}% confidence`);
  setHTML("#metric-sun", `${safeNumber(data.inputs.sunlight_intensity, 0)} <small>W/m²</small>`);
  setHTML("#metric-temp", `${safeNumber(data.inputs.temperature, 0)} <small>°C</small>`);
  setHTML("#metric-cloud", `${safeNumber(data.inputs.cloud_coverage, 0)}<small>%</small>`);
  setHTML("#metric-capacity", `${safeNumber(data.inputs.panel_capacity, 1)} <small>kWp</small>`);
  document.querySelectorAll("[data-forecast-input]").forEach((input) => {
    const key = input.dataset.forecastInput;
    if (key in data.inputs) input.value = data.inputs[key];
  });
  setText(
    "#cloud-caption",
    data.inputs.cloud_coverage >= 50 ? "Mostly overcast conditions" : data.inputs.cloud_coverage <= 20 ? "A mostly clear outlook" : "Some cloud in the picture",
  );
  setText("#daily-total-label", `${safeNumber(data.generation_kwh, 2)} kWh forecast`);
  modelVersion = data.model_version;
  setText("#model-context", `ML model v${modelVersion}`);
  makeProductionChart(data);
  renderImpacts(data);
  renderAdvice(data.advice);
  renderSchedule(data.scheduler);
  const result = document.querySelector("#simulation-result");
  if (simulation) {
    const difference = comparison ? data.generation_kwh - comparison.generation_kwh : 0;
    const comparisonText = comparison
      ? ` ${difference >= 0 ? "+" : ""}${safeNumber(difference, 2)} kWh vs your ${safeNumber(comparison.generation_kwh, 2)} kWh baseline.`
      : "";
    if (result) {
      result.textContent = `Scenario: ${safeNumber(data.generation_kwh, 2)} kWh/day.${comparisonText} ${safeNumber(data.carbon_avoided_kg)} kg CO₂ avoided. Not saved to history.`;
      result.classList.add("visible");
    }
  } else {
    baselineForecast = data;
    result?.classList.remove("visible");
  }
}

function renderImpacts(data) {
  const container = document.querySelector("#impact-list");
  if (!container) return;
  container.innerHTML = data.weather_impact.map((impact, index) => {
    const change = impact.change_kwh === 0
      ? "Your current outlook"
      : `${impact.change_kwh > 0 ? "+" : ""}${safeNumber(impact.change_kwh, 2)} kWh vs now`;
    return `<div class="impact-row ${index === 0 ? "current" : ""}">
      <span class="impact-icon">${icon(index === 1 ? "sun" : index === 2 ? "thermo" : "cloud")}</span>
      <span class="impact-copy"><strong>${impact.label}</strong><small>${change}</small></span>
      <strong class="impact-value">${safeNumber(impact.generation_kwh, 2)}<small class="impact-change">kWh / day</small></strong>
    </div>`;
  }).join("");
  const best = data.weather_impact.slice(1).sort((a, b) => b.change_kwh - a.change_kwh)[0];
  const note = best.change_kwh > 0.05
    ? `${best.label} could add about ${safeNumber(best.change_kwh, 2)} kWh to this estimate.`
    : "Weather changes make only a small difference to this estimate.";
  const insight = document.querySelector("#weather-insight-text");
  if (insight) insight.textContent = note;
}

function renderAdvice(advice) {
  const container = document.querySelector("#advice-list");
  if (!container) return;
  container.innerHTML = advice.map((tip) => `
    <div class="advice-item">
      <span class="advice-check">${icon("check")}</span>
      <div><strong>${tip.title}</strong><p>${tip.detail}</p><span class="advice-tag">${tip.tag}</span></div>
    </div>`).join("");
}

function renderSchedule(schedule) {
  const container = document.querySelector("#schedule-list");
  if (!container) return;
  container.innerHTML = schedule.map((item) => `
    <div class="schedule-item">
      <span class="appliance-icon">${icon(item.icon)}</span>
      <span class="appliance-copy"><strong>${item.name}</strong><small>${item.kw.toFixed(1)} kW · ${item.duration.toFixed(1)} hr · ${item.status}${Number.isFinite(item.available_energy_kwh) ? ` · ${safeNumber(item.available_energy_kwh, 2)} kWh available` : ""}</small></span>
      <span class="schedule-time">${item.start}<small>to ${item.end}</small></span>
    </div>`).join("");
}

function renderHistoricalImpacts(record) {
  const container = document.querySelector("#impact-list");
  if (!container) return;
  const fields = [
    ["sun", "Recorded Plant AC power", `${safeNumber(record.ac_power_kw, 2)} kW`],
    ["thermo", "Ambient temperature", `${fixedNumber(record.ambient_temperature_c, 1)} °C`],
    ["thermo", "Module temperature", `${fixedNumber(record.module_temperature_c, 1)} °C`],
    ["sun", "Recorded irradiation", safeNumber(record.irradiation, 3)],
  ];
  container.replaceChildren(...fields.map(([iconName, label, value], index) => {
    const row = document.createElement("div");
    row.className = `impact-row ${index === 0 ? "current" : ""}`;
    const mark = document.createElement("span");
    mark.className = "impact-icon";
    mark.innerHTML = icon(iconName);
    const copy = document.createElement("span");
    copy.className = "impact-copy";
    const title = document.createElement("strong");
    title.textContent = label;
    const detail = document.createElement("small");
    detail.textContent = "Historical observation";
    copy.append(title, detail);
    const amount = document.createElement("strong");
    amount.className = "impact-value";
    amount.textContent = value;
    row.append(mark, copy, amount);
    return row;
  }));
  setText("#weather-insight-text", "Historical records include temperature and irradiation; cloud coverage is not included.");
  setText(".weather-explainer", "Conditions recorded alongside the selected historical generation sample.");
  setText("#weather-description", "Recorded weather fields from the selected historical sample.");
}

function renderHistoricalAdvice(record, dailyEnergy) {
  const container = document.querySelector("#advice-list");
  if (!container) return;
  setText("#advisor-title", `Historical observation · ${record.timestamp.slice(0, 16)}`);
  setText("#advisor-intro", "Recorded generation and weather context from this historical sample; no live sensors or household system data are connected.");
  const entries = [
    ["Recorded output", `${safeNumber(record.ac_power_kw, 2)} kW at ${record.timestamp.slice(0, 16)}.`],
    ["Energy so far", `${safeNumber(dailyEnergy, 2)} kWh summed from records up to this playback time.`],
    ["Source limitations", "Plant 1 readings are aggregated across inverters, not this household. Cloud coverage and household capacity are not in this dataset."],
  ];
  container.replaceChildren(...entries.map(([titleText, detailText]) => {
    const item = document.createElement("div");
    item.className = "advice-item";
    const check = document.createElement("span");
    check.className = "advice-check";
    check.innerHTML = icon("check");
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = titleText;
    const detail = document.createElement("p");
    detail.textContent = detailText;
    content.append(title, detail);
    item.append(check, content);
    return item;
  }));
}

function renderHistoricalRecord(day, index, scheduler) {
  const record = day.records[index];
  if (!record) return;
  document.querySelector(".app-shell")?.classList.add("historical-playback");
  day.scheduler = scheduler;
  currentHistoricalRecord = record;
  currentHistoricalTimestamp = record.timestamp;
  const observed = day.records.slice(0, index + 1);
  const dailyEnergy = observed.reduce((total, sample) => total + sample.energy_kwh_15min, 0);
  const peak = day.records.reduce((best, sample) =>
    sample.ac_power_kw > best.ac_power_kw ? sample : best, day.records[0]);
  const peakPower = day.peak_ac_power_kw ?? peak.ac_power_kw;
  const estimatedPlantCapacityMwp = day.estimated_plant_capacity_kwp / 1000;
  const peakRatio = peakPower > 0
    ? Math.max(0, Math.min(100, Math.round(record.ac_power_kw / peakPower * 100)))
    : 0;
  const generation = `${safeNumber(record.ac_power_kw, 2)}<small> kW</small>`;
  const energy = `${safeNumber(dailyEnergy, 2)}<small> kWh</small>`;
  const timestamp = record.timestamp.slice(0, 16);
  const isNighttime = record.ac_power_kw === 0 && record.irradiation === 0;

  setText(".generation-kicker", "HISTORICAL PLANT OUTPUT");
  setHTML("#generation-value, #output-generation", generation);
  setText("#generation-subtitle", isNighttime
    ? "Nighttime — No solar generation recorded."
    : "");
  setHTML("#carbon-value", energy);
  setText("#carbon-label", "Plant 1 energy recorded so far");
  setText("#peak-label", "Day peak observed at");
  setText("#peak-value, #output-peak-value", (day.peak_timestamp ?? peak.timestamp).slice(0, 16));
  setText("#output-peak-label", "Day peak power observed at");
  setText("#output-generation-description", "Historical AC power at the current replay timestamp.");
  setText("#output-carbon-label", "Module temperature");
  setText("#output-carbon-value", `${fixedNumber(record.module_temperature_c, 1)} °C`);
  setText("#output-confidence-label", "Historical source");
  setText("#confidence-value", "Plant 1 dataset");
  setHTML("#metric-capacity", `~${safeNumber(estimatedPlantCapacityMwp, 1)} <small>MWp</small>`);
  setText(".capacity-kicker", "PLANT-SCALE ESTIMATE");
  setText(".capacity-card h3", "Plant capacity");
  setText("#capacity-caption", "Estimated at 110% of the recorded peak output.");
  setText("#capacity-foot-label", "Plant 1 estimate · not household capacity");
  setText(".weather-kicker", "HISTORICAL WEATHER");
  setText(".weather-today-card > .section-kicker", "HISTORICAL CONDITIONS");
  setText(".weather-disclaimer", "Recorded Plant 1 weather readings; cloud coverage is not included.");
  setText("#metric-sun", safeNumber(record.irradiation, 3));
  setText(".sunlight-caption-label", "recorded irradiation");
  setHTML("#metric-temp", `${fixedNumber(record.ambient_temperature_c, 1)} <small>°C</small>`);
  setText(".temperature-caption-label", "Ambient temperature");
  setText("#metric-cloud", "—");
  setText(".cloud-caption-label", "Cloud cover not recorded");
  setText("#cloud-caption", "Cloud cover unavailable");
  setText(".performance-kicker", "RECORDED PERFORMANCE");
  setText(".performance-title", "Output vs day peak");
  setText(".performance-score-label", "OF DAY PEAK");
  setText("#score-value", peakRatio);
  setText("#score-status", `${peakRatio}% of selected day's peak`);
  document.querySelector("#performance-note")?.setAttribute("hidden", "hidden");
  setText("#performance-foot-label", "Historical record");
  document.querySelectorAll("#score-ring").forEach((ring) => {
    ring.style.background = `conic-gradient(#31d49a 0deg ${peakRatio * 3.6}deg, #16363b ${peakRatio * 3.6}deg 360deg)`;
  });
  setText("#production-description", `Complete selected-day 15-minute energy grouped by hour. Current playback: ${timestamp}; missing samples are not interpolated.`);
  setText("#production-legend", "Historical energy");
  setText("#footer-production-legend", "Historical energy");
  document.querySelector(".chart-legend")?.setAttribute("hidden", "hidden");
  document.querySelector("#historical-chart-legend")?.removeAttribute("hidden");
  setText("#production-footnote", "Historical dataset · no live meter");
  setText("#daily-total-label", `${safeNumber(dailyEnergy, 2)} kWh Plant 1 recorded so far`);
  setText("#weather-description", "Recorded weather fields from the selected historical sample.");
  setText("#scheduler-description", `Best complete recorded windows through ${timestamp}; later output is not assumed.`);
  setText("#scheduler-note-text", "Retrospective Plant 1 aggregate output compared with reference appliance loads; this is not a measured household schedule or a 6.5 kWp home profile.");
  setText("#model-context", `Historical playback · ${timestamp}`);
  setText("#advisor-title", `Historical observation · ${timestamp}`);
  document.querySelectorAll("#production-chart").forEach((canvas) => {
    canvas.setAttribute("aria-label", `Historical hourly solar energy through ${timestamp}`);
  });
  makeProductionChart({ hourly: day.hourly }, record.timestamp);
  renderHistoricalImpacts(record);
  renderHistoricalAdvice(record, dailyEnergy);
  renderSchedule(scheduler);
  document.querySelectorAll("#insight-dashboard form input, #insight-dashboard form select, #insight-dashboard form button").forEach((element) => {
    element.disabled = true;
  });
  document.querySelector("#refresh-button")?.setAttribute("disabled", "disabled");
  document.querySelector(".efficiency-card .info-dot")?.setAttribute(
    "title",
    "Current recorded AC power as a percentage of the highest source-recorded power on the complete selected date.",
  );
}

async function requestForecast(payload, { simulate = false, saveHistory = !simulate } = {}) {
  const response = await fetch("/api/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, save_history: saveHistory }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not calculate the forecast.");
  if (!historicalPlayback?.active) {
    renderForecast(data, { simulation: simulate, saved: saveHistory });
  }
  if (saveHistory) await loadHistory();
}

async function loadHistory() {
  const count = document.querySelector("#history-count");
  if (!count) return;
  const response = await fetch("/api/history?limit=20");
  if (!response.ok) throw new Error("Could not load forecast history.");
  const { forecasts } = await response.json();
  const card = document.querySelector("#history");
  count.textContent = `${forecasts.length} ${forecasts.length === 1 ? "forecast" : "forecasts"}`;
  card.classList.toggle("has-history", forecasts.length > 0);
  if (!window.Chart) return;
  const context = document.querySelector("#history-chart");
  const labels = forecasts.map((item) => {
    const date = new Date(item.created_at);
    return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  });
  const values = forecasts.map((item) => item.generation_kwh);
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: values.map((_, index) => index === values.length - 1 ? "#42dba0" : "#245b51"),
        borderRadius: 4,
        maxBarThickness: 26,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { displayColors: false, callbacks: { label: (context) => ` ${context.parsed.y.toFixed(2)} kWh` } } },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: "#9bb0b6", font: { family: "DM Sans", size: 12 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } },
        y: { beginAtZero: true, grid: { color: "rgba(152, 184, 185, .14)", drawTicks: false }, border: { display: false }, ticks: { color: "#9bb0b6", padding: 7, font: { family: "DM Sans", size: 11 }, maxTicksLimit: 3, callback: (value) => `${value} kWh` } },
      },
    },
  };
  if (historyChart) {
    historyChart.data.labels = labels;
    historyChart.data.datasets[0].data = values;
    historyChart.data.datasets[0].backgroundColor = config.data.datasets[0].backgroundColor;
    historyChart.update("active");
  } else {
    historyChart = new Chart(context, config);
  }
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (historicalPlayback?.active && !(await stopHistoricalPlayback())) return;
    if (!form.reportValidity()) return;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      await requestForecast(valuesFromForm());
      sessionStorage.setItem("solarwise.inputs", JSON.stringify(valuesFromForm()));
      showToast("Forecast saved to your history.");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("#simulate-button").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (historicalPlayback?.active && !(await stopHistoricalPlayback())) return;
    if (!form.reportValidity()) return;
    button.disabled = true;
    try {
      await requestForecast(valuesFromForm(), { simulate: true });
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

document.querySelector("#refresh-button").addEventListener("click", async (event) => {
  if (historicalPlayback?.active) {
    showToast("Stop historical playback before refreshing the model forecast.");
    return;
  }
  const button = event.currentTarget;
  button.classList.add("is-loading");
  button.disabled = true;
  try {
    await requestForecast(valuesFromForm());
    showToast("Fresh estimate saved.");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.classList.remove("is-loading");
    button.disabled = false;
  }
});

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    document.querySelector(".nav-link.active")?.classList.remove("active");
    link.classList.add("active");
  });
});

document.querySelector("#dashboard-search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const query = event.currentTarget.value.trim().toLowerCase();
  if (!query) return;
  const target = [
    ["prediction", "/prediction"],
    ["simulator", "/simulator"],
    ["weather", "/weather"],
    ["insights", "/insights"],
    ["advisor", "/advisor"],
    ["advice", "/advisor"],
    ["schedule", "/scheduler"],
    ["appliance", "/scheduler"],
    ["history", "/history"],
    ["dashboard", "/"],
  ].find(([term]) => term.includes(query) || query.includes(term));
  if (target) {
    window.location.assign(target[1]);
  } else {
    showToast("No dashboard section matches that search.");
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    document.querySelector("#dashboard-search").focus();
  }
});

const insightDashboard = document.querySelector("#insight-dashboard");
const insightHistoryList = document.querySelector("#insight-history-list");

function renderInsightResult(selector, heading, facts, notes = []) {
  const container = document.querySelector(selector);
  if (!container) return;
  container.replaceChildren();
  const title = document.createElement("h4");
  title.textContent = heading;
  container.append(title);
  if (facts.length) {
    const list = document.createElement("dl");
    list.className = "insight-result-facts";
    facts.forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "insight-result-row";
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      row.append(term, description);
      list.append(row);
    });
    container.append(list);
  }
  if (notes.length) {
    const noteList = document.createElement("ul");
    noteList.className = "insight-result-notes";
    notes.forEach((note) => {
      const item = document.createElement("li");
      item.textContent = note;
      noteList.append(item);
    });
    container.append(noteList);
  }
  container.classList.add("visible");
}

function forecastInputs() {
  return currentForecast?.inputs || { ...DEFAULTS, ...storedInputs };
}

async function submitInsight(formElement, endpoint, payload, renderResult) {
  if (!formElement.reportValidity()) return;
  const button = formElement.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not calculate this estimate.");
    renderResult(data);
    await loadInsightHistory();
    showToast("Insight saved to your local history.");
  } catch (error) {
    renderInsightResult(`#${formElement.id.replace("-form", "-result")}`, "Could not complete this estimate", [], [error.message]);
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

function notifySolarUnderperformance(data) {
  if (!data.notification_required) return;
  latestSolarNotification = data.notification_message;
  showToast(data.notification_message);
  document.querySelector("#notification-button")?.classList.add("has-alert");
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(data.notification_title, {
      body: data.notification_message,
      icon: "/static/solarwise.svg",
    });
  }
}

function renderHealthResult(data, resultSelector = "#health-result") {
  const direction = data.deviation_direction === "matches"
    ? "matches"
    : `${safeNumber(data.deviation_percent, 1)}% ${data.deviation_direction} the estimate`;
  const demoReading = data.reading_mode === "demo";
  const facts = [
    ["Health score", `${data.health_score} / 100`],
    ["Predicted generation", demoReading ? safeNumber(data.expected_generation_kwh, 2) : `${safeNumber(data.expected_generation_kwh, 2)} kWh`],
    ["Actual generation", demoReading ? safeNumber(data.actual_generation_kwh, 2) : `${safeNumber(data.actual_generation_kwh, 2)} kWh`],
    ["Deviation", direction],
  ];
  if (data.demo_week) {
    facts.push(
      ["Seven-day period", `${data.demo_week.week_start} to ${data.demo_week.week_end}`],
      ["Seven-day actual average", `${safeNumber(data.demo_week.average_actual_kwh, 2)} kWh/day`],
      ["One-week difference", "Huge difference detected"],
    );
  }
  const notes = [];
  if (!demoReading) {
    if (data.possible_causes.length) {
      notes.push("Possible causes (not fault diagnoses):", ...data.possible_causes);
    } else {
      notes.push("No specific possible cause is suggested by these inputs.");
    }
  }
  if (!demoReading || data.recommended_actions.length) {
    notes.push("Recommended maintenance:", ...data.recommended_actions);
  }
  if (!demoReading && data.disclaimer) notes.push(data.disclaimer);
  renderInsightResult(resultSelector, data.status, facts, notes);
  if (data.demo_week && resultSelector === "#prediction-health-result") {
    const result = document.querySelector(resultSelector);
    if (result) {
      const week = document.createElement("div");
      week.className = "prediction-week-list";
      week.setAttribute("aria-label", "Seven-day generation values");
      data.demo_week.daily_totals.forEach((item) => {
        const day = document.createElement("article");
        const date = document.createElement("span");
        date.textContent = item.date.slice(5);
        const value = document.createElement("strong");
        value.textContent = fixedNumber(item.generation_kwh, 0);
        day.append(date, value);
        week.append(day);
      });
      result.append(week);
    }
  }
  notifySolarUnderperformance(data);
}

const predictionHealthForm = document.querySelector("#prediction-health-form");
if (predictionHealthForm) {
  document.querySelector("#prediction-historical-demo")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch("/api/insights/health", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...forecastInputs(),
          reading_mode: "demo",
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load the historical demonstration.");
      setText("#prediction-expected-value", safeNumber(data.predicted_generation_kwh, 2));
      setText("#prediction-actual-value", safeNumber(data.actual_generation_kwh, 2));
      renderHealthResult(data, "#prediction-health-result");
    } catch (error) {
      renderInsightResult(
        "#prediction-health-result",
        "Could not load the historical example",
        [],
        [error.message],
      );
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });

}

if (insightDashboard) {
  const healthForm = document.querySelector("#health-form");
  healthForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const reading = Number(new FormData(healthForm).get("reported_generation_kwh"));
    submitInsight(
      healthForm,
      "/api/insights/health",
      { ...forecastInputs(), reported_generation_kwh: reading, reading_mode: "manual" },
      renderHealthResult,
    );
  });

  document.querySelector("#health-demo-button").addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    fetch("/api/insights/health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...forecastInputs(), reading_mode: "demo" }),
    }).then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not run the demonstration.");
      renderHealthResult(data);
      await loadInsightHistory();
      showToast("Seven-day sample loaded.");
    }).catch((error) => {
      renderInsightResult("#health-result", "Could not complete this demonstration", [], [error.message]);
      showToast(error.message);
    }).finally(() => {
      button.disabled = false;
    });
  });

  const cleaningForm = document.querySelector("#cleaning-form");
  cleaningForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(cleaningForm);
    submitInsight(cleaningForm, "/api/insights/cleaning", {
      ...forecastInputs(),
      soiling_percent: Number(values.get("soiling_percent")),
      days_since_cleaning: Number(values.get("days_since_cleaning")),
    }, (data) => renderInsightResult("#cleaning-result", "Cleaning estimate", [
      ["Estimated energy loss", `${safeNumber(data.estimated_loss_kwh, 2)} kWh/day`],
      ["Potential recovery", `${safeNumber(data.estimated_recovery_kwh, 2)} kWh/day`],
      ["Recommendation", data.recommendation],
    ], [data.assumption, data.safety_note]));
  });

  const savingsForm = document.querySelector("#savings-form");
  savingsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(savingsForm);
    const currencySymbol = values.get("currency");
    submitInsight(savingsForm, "/api/insights/savings", {
      ...forecastInputs(),
      electricity_rate: Number(values.get("electricity_rate")),
      currency: currencySymbol,
    }, (data) => renderInsightResult("#savings-result", "Potential gross bill offset", [
      ["Daily", `${data.currency_symbol}${safeNumber(data.daily_savings, 2)}`],
      ["Weekly", `${data.currency_symbol}${safeNumber(data.weekly_savings, 2)}`],
      ["Monthly", `${data.currency_symbol}${safeNumber(data.monthly_savings, 2)}`],
      ["Yearly", `${data.currency_symbol}${safeNumber(data.yearly_savings, 2)}`],
      ["Annual generation", `${safeNumber(data.yearly_generation_kwh, 1)} kWh`],
    ], [data.assumption]));
  });

  const riskForm = document.querySelector("#weather-risk-form");
  riskForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(riskForm);
    const scenarioInputs = { ...forecastInputs() };
    scenarioInputs.cloud_coverage = Number(values.get("cloud_coverage"));
    scenarioInputs.temperature = Number(values.get("temperature"));
    submitInsight(riskForm, "/api/insights/weather-risk", {
      ...scenarioInputs,
      rain_scenario: values.get("rain_scenario"),
    }, (data) => renderInsightResult("#weather-risk-result", `${data.risk_level[0].toUpperCase()}${data.risk_level.slice(1)} scenario risk`, [
      ["Scenario generation", `${safeNumber(data.generation_kwh, 2)} kWh/day`],
      ["Estimated total loss", `${safeNumber(data.estimated_total_loss_kwh, 2)} kWh/day (${safeNumber(data.estimated_loss_percent, 1)}%)`],
      ["Cloud difference", `${safeNumber(data.estimated_cloud_loss_kwh, 2)} kWh/day`],
      ["Heat difference", `${safeNumber(data.estimated_heat_loss_kwh, 2)} kWh/day`],
      ["Rain assumption", `${safeNumber(data.estimated_rain_loss_kwh, 2)} kWh/day`],
    ], [...data.alerts, data.disclaimer]));
  });

  document.querySelector("#refresh-insight-history").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await loadInsightHistory();
      showToast("Insight history refreshed.");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function saveHistoricalPlayback() {
  sessionStorage.setItem("solarwise.historical-playback", JSON.stringify(historicalPlayback));
}

function setPlaybackStatus(message, state = "") {
  const status = document.querySelector("#playback-status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("is-error", state === "error");
  status.classList.toggle("is-complete", state === "complete");
}

function updatePlaybackControls() {
  const toggle = document.querySelector("#playback-toggle");
  const restart = document.querySelector("#playback-restart");
  const stop = document.querySelector("#playback-stop");
  const dateSelect = document.querySelector("#historical-date");
  if (!toggle || !historicalPlayback) return;
  toggle.textContent = historicalPlayback.playing
    ? "Pause playback"
    : historicalPlayback.completed
      ? "Replay selected date"
      : historicalPlayback.active
        ? "Resume playback"
        : "Start playback";
  toggle.disabled = !historicalDay;
  restart.disabled = !historicalDay;
  stop.disabled = !historicalPlayback.active;
  dateSelect.disabled = false;
  if (!historicalPlayback.active) {
    setPlaybackStatus("Model forecast mode. Choose a historical date and start playback.");
  } else if (!historicalDay) {
    setPlaybackStatus("Loading the selected historical date…");
  } else if (historicalPlayback.completed) {
    const last = historicalDay.records[historicalPlayback.index];
    setPlaybackStatus(
      `Replay ended at ${last.timestamp}. No later records are available for this date.`,
      "complete",
    );
  } else if (historicalPlayback.playing) {
    const current = historicalDay.records[historicalPlayback.index];
    setPlaybackStatus(
      `Playing record ${historicalPlayback.index + 1} of ${historicalDay.records.length} · ${current.timestamp} · next record in 30 seconds.`,
    );
  } else {
    const current = historicalDay.records[historicalPlayback.index];
    setPlaybackStatus(current
      ? `Paused at historical observation ${current.timestamp}.`
      : "Historical date selected. Start playback to show its first observation.");
  }
}

async function loadHistoricalDay(date) {
  const query = new URLSearchParams({ date });
  if (document.querySelector("#schedule-list")) query.set("include_scheduler", "1");
  const response = await fetch(`/api/simulation/day?${query}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not load this historical date.");
  return data;
}

function schedulerSnapshotForRecord(day, index) {
  if (!document.querySelector("#schedule-list")) return [];
  const snapshot = day.scheduler_snapshots?.[index];
  if (
    !snapshot
    || snapshot.timestamp !== day.records[index]?.timestamp
    || !Array.isArray(snapshot.scheduler)
  ) {
    throw new Error("Appliance windows are unavailable for this historical observation.");
  }
  return snapshot.scheduler;
}

function clearPlaybackTimer() {
  if (playbackTimer) {
    clearTimeout(playbackTimer);
    playbackTimer = undefined;
  }
}

function defaultPlaybackIndex(day) {
  const index = day.records.findIndex((record) => record.timestamp.slice(11, 13) >= "08");
  return index >= 0 ? index : 0;
}

async function advanceHistoricalPlayback() {
  if (!historicalPlayback?.playing || !historicalDay) return;
  const lastIndex = historicalDay.records.length - 1;
  if (historicalPlayback.index >= lastIndex) {
    historicalPlayback.playing = false;
    historicalPlayback.completed = true;
    clearPlaybackTimer();
    saveHistoricalPlayback();
    updatePlaybackControls();
    return;
  }
  const playbackDate = historicalPlayback.date;
  const previousIndex = historicalPlayback.index;
  const nextIndex = previousIndex + 1;
  try {
    const scheduler = schedulerSnapshotForRecord(historicalDay, nextIndex);
    if (
      !historicalPlayback.playing
      || historicalPlayback.date !== playbackDate
      || historicalPlayback.index !== previousIndex
    ) return;
    historicalPlayback.index = nextIndex;
    renderHistoricalRecord(historicalDay, nextIndex, scheduler);
    if (nextIndex === lastIndex) {
      historicalPlayback.playing = false;
      historicalPlayback.completed = true;
    } else {
      startPlaybackTimer();
    }
    saveHistoricalPlayback();
    updatePlaybackControls();
  } catch (error) {
    historicalPlayback.playing = false;
    clearPlaybackTimer();
    saveHistoricalPlayback();
    updatePlaybackControls();
    setPlaybackStatus(error.message, "error");
  }
}

function startPlaybackTimer() {
  clearPlaybackTimer();
  playbackTimer = setTimeout(advanceHistoricalPlayback, PLAYBACK_INTERVAL_MS);
}

async function initializeHistoricalPlayback() {
  const dateSelect = document.querySelector("#historical-date");
  if (!dateSelect) return;
  const response = await fetch("/api/simulation/dates");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Historical observations are unavailable.");
  if (!data.dates.length) throw new Error("The historical dataset contains no available dates.");
  dateSelect.replaceChildren(...data.dates.map((item) => {
    const option = document.createElement("option");
    option.value = item.date;
    option.textContent = `${item.date} · ${item.observation_count} records`;
    return option;
  }));
  const latestDate = data.dates[data.dates.length - 1].date;
  let savedState;
  let initializationWarning = "";
  try {
    savedState = JSON.parse(sessionStorage.getItem("solarwise.historical-playback") || "null");
  } catch {
    savedState = null;
  }
  historicalPlayback = savedState && typeof savedState === "object" && typeof savedState.date === "string"
    ? { active: false, playing: false, completed: false, index: -1, ...savedState }
    : { active: true, playing: true, completed: false, date: latestDate, index: 0 };
  if (!Number.isInteger(historicalPlayback.index)) historicalPlayback.index = 0;
  if (!data.dates.some((item) => item.date === historicalPlayback.date)) {
    historicalPlayback = {
      active: false,
      playing: false,
      completed: false,
      date: latestDate,
      index: -1,
    };
    initializationWarning = "The previously selected date is no longer in the dataset. Choose an available date.";
  }
  dateSelect.value = historicalPlayback.date || latestDate;
  historicalDay = await loadHistoricalDay(historicalPlayback.date || latestDate);
  if (historicalPlayback.active) {
    if (!savedState || historicalPlayback.index === 0) {
      historicalPlayback.index = defaultPlaybackIndex(historicalDay);
    } else {
      historicalPlayback.index = Math.max(
      0,
      Math.min(historicalPlayback.index, historicalDay.records.length - 1),
      );
    }
    const scheduler = schedulerSnapshotForRecord(historicalDay, historicalPlayback.index);
    renderHistoricalRecord(historicalDay, historicalPlayback.index, scheduler);
    if (historicalPlayback.playing && !historicalPlayback.completed) startPlaybackTimer();
  }
  saveHistoricalPlayback();
  updatePlaybackControls();
  if (initializationWarning) setPlaybackStatus(initializationWarning, "error");
}

document.querySelector("#historical-date")?.addEventListener("change", async (event) => {
  clearPlaybackTimer();
  const date = event.currentTarget.value;
  historicalDay = undefined;
  historicalPlayback = {
    active: true,
    playing: false,
    completed: false,
    date,
    index: -1,
  };
  saveHistoricalPlayback();
  setPlaybackStatus(`Loading observations for ${date}…`);
  updatePlaybackControls();
  try {
    const day = await loadHistoricalDay(date);
    if (document.querySelector("#historical-date").value !== date) return;
    historicalDay = day;
    historicalPlayback.index = defaultPlaybackIndex(historicalDay);
    const scheduler = schedulerSnapshotForRecord(historicalDay, historicalPlayback.index);
    renderHistoricalRecord(historicalDay, historicalPlayback.index, scheduler);
    saveHistoricalPlayback();
    updatePlaybackControls();
  } catch (error) {
    if (document.querySelector("#historical-date").value !== date) return;
    historicalPlayback.active = false;
    historicalPlayback.playing = false;
    saveHistoricalPlayback();
    updatePlaybackControls();
    setPlaybackStatus(error.message, "error");
  }
});

document.querySelector("#playback-toggle")?.addEventListener("click", async () => {
  if (historicalPlayback?.playing) {
    historicalPlayback.playing = false;
    clearPlaybackTimer();
    saveHistoricalPlayback();
    updatePlaybackControls();
    return;
  }
  try {
    const date = document.querySelector("#historical-date").value;
    if (!historicalDay || historicalDay.date !== date) {
      const day = await loadHistoricalDay(date);
      if (document.querySelector("#historical-date").value !== date) return;
      historicalDay = day;
    }
    if (historicalPlayback.date !== date) return;
    if (!historicalPlayback.active || historicalPlayback.completed) {
      historicalPlayback.index = defaultPlaybackIndex(historicalDay);
      historicalPlayback.completed = false;
    }
    const scheduler = schedulerSnapshotForRecord(historicalDay, historicalPlayback.index);
    historicalPlayback.active = true;
    historicalPlayback.playing = true;
    renderHistoricalRecord(historicalDay, historicalPlayback.index, scheduler);
    saveHistoricalPlayback();
    updatePlaybackControls();
    startPlaybackTimer();
  } catch (error) {
    setPlaybackStatus(error.message, "error");
  }
});

document.querySelector("#playback-restart")?.addEventListener("click", async () => {
  clearPlaybackTimer();
  const date = document.querySelector("#historical-date").value;
  try {
    const day = await loadHistoricalDay(date);
    if (document.querySelector("#historical-date").value !== date) return;
    historicalDay = day;
    const startIndex = defaultPlaybackIndex(historicalDay);
    const scheduler = schedulerSnapshotForRecord(historicalDay, startIndex);
    historicalPlayback = {
      active: true,
      playing: true,
      completed: false,
      date: historicalDay.date,
      index: startIndex,
    };
    renderHistoricalRecord(historicalDay, startIndex, scheduler);
    saveHistoricalPlayback();
    updatePlaybackControls();
    startPlaybackTimer();
  } catch (error) {
    historicalPlayback.playing = false;
    saveHistoricalPlayback();
    updatePlaybackControls();
    setPlaybackStatus(error.message, "error");
  }
});

async function stopHistoricalPlayback() {
  if (!historicalPlayback?.active) return true;
  clearPlaybackTimer();
  const previousState = historicalPlayback;
  historicalPlayback = { ...historicalPlayback, active: false, playing: false, completed: false, index: -1 };
  try {
    await requestForecast(currentForecast?.inputs || { ...DEFAULTS, ...storedInputs }, { saveHistory: false });
    currentHistoricalRecord = undefined;
    saveHistoricalPlayback();
    updatePlaybackControls();
    return true;
  } catch (error) {
    historicalPlayback = { ...previousState, playing: false };
    if (historicalDay && historicalPlayback.index >= 0) {
      renderHistoricalRecord(
        historicalDay,
        historicalPlayback.index,
        historicalDay.scheduler,
      );
    }
    saveHistoricalPlayback();
    updatePlaybackControls();
    setPlaybackStatus(`Could not restore the model forecast: ${error.message}`, "error");
    return false;
  }
}

document.querySelector("#playback-stop")?.addEventListener("click", stopHistoricalPlayback);

async function loadInsightHistory() {
  if (!insightHistoryList) return;
  const response = await fetch("/api/insights/history?limit=20");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not load insight history.");
  insightHistoryList.replaceChildren();
  if (!data.records.length) {
    const empty = document.createElement("p");
    empty.textContent = "Your saved comparisons and estimates will appear here.";
    insightHistoryList.append(empty);
    return;
  }
  const labels = {
    health: "Solar health comparison",
    cleaning: "Cleaning estimate",
    savings: "Bill savings estimate",
    weather_risk: "Weather scenario",
  };
  data.records.forEach((record) => {
    const row = document.createElement("article");
    row.className = "insight-history-row";
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = labels[record.type] || "Solar insight";
    const summary = document.createElement("p");
    const result = record.result;
    if (record.type === "health") {
      summary.textContent = `${result.reading_label}: ${safeNumber(result.comparison_generation_kwh, 2)} kWh · score ${result.health_score}/100`;
    } else if (record.type === "cleaning") {
      summary.textContent = `Potential recovery ${safeNumber(result.estimated_recovery_kwh, 2)} kWh/day · ${result.soiling_percent}% reported soiling`;
    } else if (record.type === "savings") {
      summary.textContent = `Yearly gross offset ${result.currency_symbol}${safeNumber(result.yearly_savings, 2)} · ${result.currency} estimate`;
    } else {
      summary.textContent = `${result.risk_level} risk · possible loss ${safeNumber(result.estimated_total_loss_kwh, 2)} kWh/day`;
    }
    content.append(title, summary);
    const timestamp = document.createElement("time");
    timestamp.dateTime = record.created_at;
    const date = new Date(record.created_at);
    timestamp.textContent = Number.isNaN(date.getTime())
      ? "Saved locally"
      : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    row.append(content, timestamp);
    insightHistoryList.append(row);
  });
}

function renderDatasetInformation(data) {
  const container = document.querySelector("#dataset-information-content");
  if (!container) return;
  const history = data.historical_dataset;
  const model = data.model;
  const features = Array.isArray(model.features)
    ? model.features.map((feature) => feature.replaceAll("_", " ")).join(", ")
    : "Unavailable";
  const facts = [
    ["Historical source", `${history.source_file} · ${history.source_description}`],
    ["Date range", `${history.start_timestamp.slice(0, 10)} to ${history.end_timestamp.slice(0, 10)}`],
    ["Historical records", Number(history.record_count).toLocaleString()],
    [
      "Sampling interval",
      `${history.nominal_sampling_interval_minutes}-minute nominal interval; ${history.non_nominal_gap_count} gaps are left unfilled`,
    ],
    ["Energy calculation", history.energy_basis],
    ["Model", `${model.algorithm} · version ${model.version}`],
    [
      "Model training data",
      `${Number(model.training_record_count).toLocaleString()} ${model.training_source}`,
    ],
    ["Model inputs", features],
    ["Historical data scope", history.scope_note],
  ];
  container.replaceChildren(...facts.map(([label, value]) => {
    const item = document.createElement("div");
    item.className = "dataset-information-item";
    const term = document.createElement("strong");
    term.textContent = label;
    const description = document.createElement("span");
    description.textContent = value;
    item.append(term, description);
    return item;
  }));
}

async function loadDatasetInformation() {
  const container = document.querySelector("#dataset-information-content");
  if (!container) return;
  try {
    const response = await fetch("/api/simulation/dataset-info");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load dataset information.");
    renderDatasetInformation(data);
  } catch (error) {
    container.textContent = `Dataset information unavailable: ${error.message}`;
  }
}

function renderMonthlyReport(data) {
  const container = document.querySelector("#monthly-report-list");
  if (!container) return;
  setText("#monthly-report-note", data.disclaimer);
  container.replaceChildren(...data.months.map((month) => {
    const article = document.createElement("article");
    article.className = "monthly-report-month";
    const heading = document.createElement("h4");
    heading.textContent = month.label;
    const coverage = document.createElement("p");
    coverage.className = "monthly-report-coverage";
    coverage.textContent = `${month.partial_month ? "Partial period" : "Full-month"} · ${month.days_with_records}/${month.days_in_month} days with records · ${month.first_date} to ${month.last_date} · ${Number(month.record_count).toLocaleString()} samples`;
    const facts = document.createElement("dl");
    [
      ["Recorded aggregate energy", `${fixedNumber(month.generation_kwh)} kWh`],
      ["Estimated gross tariff value", `${data.currency_symbol}${fixedNumber(month.estimated_savings)} ${data.currency}`],
      ["Estimated CO₂ avoided", `${fixedNumber(month.estimated_co2_avoided_kg)} kg`],
    ].forEach(([label, value]) => {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      row.append(term, description);
      facts.append(row);
    });
    article.append(heading, coverage, facts);
    return article;
  }));
  if (!data.months.length) {
    const empty = document.createElement("p");
    empty.textContent = "No monthly records are available.";
    container.append(empty);
  }
}

async function loadMonthlyReport() {
  const formElement = document.querySelector("#monthly-report-form");
  const container = document.querySelector("#monthly-report-list");
  if (!formElement || !container) return;
  const values = new FormData(formElement);
  const query = new URLSearchParams({
    rate: values.get("rate"),
    currency: values.get("currency"),
  });
  const button = formElement.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const response = await fetch(`/api/simulation/monthly-report?${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load the monthly report.");
    renderMonthlyReport(data);
  } catch (error) {
    container.textContent = `Monthly report unavailable: ${error.message}`;
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

document.querySelector("#monthly-report-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.currentTarget.reportValidity()) loadMonthlyReport();
});

document.querySelector("#notification-button").addEventListener("click", () => {
  const notificationButton = document.querySelector("#notification-button");
  notificationButton.classList.remove("has-alert");
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
  if (latestSolarNotification) {
    showToast(latestSolarNotification);
    return;
  }
  if (historicalPlayback?.active && currentHistoricalRecord) {
    showToast(
      `Historical observation ${currentHistoricalRecord.timestamp}: ${safeNumber(currentHistoricalRecord.ac_power_kw, 2)} kW recorded AC power.`,
    );
    return;
  }
  if (!currentForecast) {
    showToast("Your first solar forecast is loading.");
    return;
  }
  showToast(`Today's forecast is ${safeNumber(currentForecast.generation_kwh, 2)} kWh. Peak solar is around ${currentForecast.peak_hour}.`);
});

async function initialize() {
  try {
    let savedPlaybackState;
    try {
      savedPlaybackState = JSON.parse(sessionStorage.getItem("solarwise.historical-playback") || "null");
    } catch {
      savedPlaybackState = null;
    }
    const shouldLoadModelForecast = Boolean(
      savedPlaybackState
      && typeof savedPlaybackState === "object"
      && savedPlaybackState.active !== true,
    );
    const startupTasks = [
      loadHistory(),
      loadInsightHistory(),
      initializeHistoricalPlayback(),
    ];
    if (document.querySelector("#dataset-information-content")) {
      startupTasks.push(loadDatasetInformation());
      startupTasks.push(loadMonthlyReport());
    }
    if (shouldLoadModelForecast) {
      startupTasks.push(
        requestForecast(form ? valuesFromForm() : { ...DEFAULTS, ...storedInputs }, { saveHistory: false }),
      );
    }
    await Promise.all(startupTasks);
    if (!historicalPlayback?.active && !currentForecast) {
      await requestForecast(form ? valuesFromForm() : { ...DEFAULTS, ...storedInputs }, { saveHistory: false });
    }
  } catch (error) {
    setPlaybackStatus(error.message, "error");
    showToast(error.message);
  }
}

initialize();
