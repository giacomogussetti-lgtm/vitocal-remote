/**
 * Telemetry Charts for Vitocal Remote Mobile App.
 * Uses Chart.js v4 with continuous TimeScale (date-fns adapter),
 * X-only 2-finger pinch + pan (keeping 1-finger value scrubbing intact),
 * minimal Read/Pan mode toggle, locked/tappable Y-axes, seamless toggleable
 * 3-color PdC / Grundfos activity bands, and WO1C Target LWT curve overlay.
 */

let telemetryChart = null;
let currentSamples = [];
let activeTimeframeHours = 24; // Default 24h

let chartInteractionMode = "read"; // "read" (1-finger tooltip) | "pan" (1-finger X drag)
let xZoomRange = null; // { min, max } when zoomed/panned in X, null when showing full timeframe
let yAutoFrozen = { yTemp: null, yOther: null }; // Snapshot of auto Y bounds during X zoom/pan
let activeModalAxis = null;
let visibleActivityBands = { 1: true, 2: true, 3: true };

const MIN_X_SPAN_MS = 15 * 60 * 1000; // Minimum 15 min X window when zooming in
const Y_SCALE_STORAGE_KEY = "vitocal_y_scales";

let yAxisCustom = loadYAxisCustom();

/**
 * Calculates the Viessmann Vitotronic WO1C target supply temperature (LWT)
 * using PyViCare's heat_curve_formular_variant2 (single-circuit heatpump).
 * Returns null in standby unless allowStandby is true.
 */
function computeVitocalTargetLwt(sample, allowStandby = false) {
  if (!sample) return null;
  const prog = (sample.active_program || "").toLowerCase();
  if (!allowStandby && prog === "standby") return null;

  if (!allowStandby && sample.target_supply_temp_c != null && !isNaN(Number(sample.target_supply_temp_c))) {
    return Math.round(Number(sample.target_supply_temp_c) * 10) / 10;
  }

  if (sample.external_temp_c == null || isNaN(Number(sample.external_temp_c))) return null;
  const oat = Number(sample.external_temp_c);
  const slope = sample.heating_curve_slope != null ? Number(sample.heating_curve_slope) : 0.6;
  const shift = sample.heating_curve_shift != null ? Number(sample.heating_curve_shift) : 0.0;

  let tRef = 12.0;
  if (prog === "reduced" && sample.reduced_setpoint_c != null) {
    tRef = Number(sample.reduced_setpoint_c);
  } else if (sample.normal_setpoint_c != null) {
    tRef = Number(sample.normal_setpoint_c);
  }

  const delta = oat - tRef;
  const raw = tRef + shift - slope * delta * (1.148987 + 0.021 * delta + 247.9e-6 * delta * delta) + 5.0;
  const clamped = Math.max(10.0, Math.min(40.0, raw));
  return Math.round(clamped * 10) / 10;
}

window.computeVitocalTargetLwt = computeVitocalTargetLwt;

const CHANNEL_DEFS = [
  { key: "external_temp_c", label: "T Esterna Sonda PdC", unit: "°C", color: "#38bdf8", yAxis: "yTemp", active: true },
  { key: "buffer_temp_c", label: "T Accumulo Puffer 200L", unit: "°C", color: "#f59e0b", yAxis: "yTemp", active: true },
  { key: "pdc_supply_temp_c", label: "T Mandata PdC", unit: "°C", color: "#ef4444", yAxis: "yTemp", active: true },
  {
    key: "_target_lwt_c",
    label: "Target LWT Curva (PdC)",
    unit: "°C",
    color: "#d946ef",
    yAxis: "yTemp",
    borderDash: [6, 4],
    active: true,
    spanGaps: false,
    computed: (s) => computeVitocalTargetLwt(s, false),
  },
  { key: "pdc_return_temp_c", label: "T Ritorno PdC", unit: "°C", color: "#f43f5e", yAxis: "yTemp", active: false },
  { key: "indoor_temp_bticino_c", label: "T Interna Corridoio", unit: "°C", color: "#10b981", yAxis: "yTemp", active: true },
  { key: "indoor_setpoint_bticino_c", label: "Setpoint BTicino", unit: "°C", color: "#eab308", yAxis: "yTemp", borderDash: [5, 5], active: false },
  { key: "dhw_storage_temp_c", label: "T Bollitore ACS", unit: "°C", color: "#a855f7", yAxis: "yTemp", active: false },
  { key: "compressor_modulation_percent", label: "Modulazione Inverter (%)", unit: "%", color: "#facc15", yAxis: "yOther", active: true },
  { key: "hot_gas_pressure_bar", label: "Pressione Gas Caldo (bar)", unit: "bar", color: "#ec4899", yAxis: "yOther", active: false },
  { key: "cop_heating", label: "COP Riscaldamento", unit: "COP", color: "#34d399", yAxis: "yOther", active: false },
  { key: "humidity_percent", label: "Umidità Ambiente (%)", unit: "%", color: "#60a5fa", yAxis: "yOther", borderDash: [3, 3], active: false },
];

const Y_AXIS_CONFIG = {
  yTemp: {
    title: "🌡️ Scala Asse Sinistro (°C)",
    shortLabel: "°C",
    presets: [
      { label: "-5 .. 35 °C", min: -5, max: 35 },
      { label: "0 .. 30 °C", min: 0, max: 30 },
      { label: "0 .. 45 °C", min: 0, max: 45 },
      { label: "5 .. 25 °C", min: 5, max: 25 },
    ],
  },
  yOther: {
    title: "📊 Scala Asse Destro (% / bar / COP)",
    shortLabel: "%",
    presets: [
      { label: "0 .. 100 %", min: 0, max: 100 },
      { label: "0 .. 50", min: 0, max: 50 },
      { label: "0 .. 25", min: 0, max: 25 },
      { label: "0 .. 10", min: 0, max: 10 },
    ],
  },
};

const ACTIVITY_STYLES = {
  1: { fill: "rgba(245, 158, 11, 0.14)", ribbon: "rgba(245, 158, 11, 0.88)", text: "🔥 Stato: Solo PdC ON" },
  2: { fill: "rgba(56, 189, 248, 0.14)", ribbon: "rgba(56, 189, 248, 0.88)", text: "💧 Stato: Solo Grundfos ON" },
  3: { fill: "rgba(16, 185, 129, 0.19)", ribbon: "rgba(16, 185, 129, 0.94)", text: "⚡ Stato: PdC + Grundfos ON" },
};

function loadYAxisCustom() {
  const defaults = {
    yTemp: { locked: false, min: null, max: null },
    yOther: { locked: false, min: null, max: null },
  };
  try {
    const raw = localStorage.getItem(Y_SCALE_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw);
    for (const key of ["yTemp", "yOther"]) {
      if (parsed[key] && parsed[key].locked && typeof parsed[key].min === "number" && typeof parsed[key].max === "number" && parsed[key].max > parsed[key].min) {
        defaults[key] = { locked: true, min: parsed[key].min, max: parsed[key].max };
      }
    }
  } catch (e) {
    // Ignore malformed localStorage
  }
  return defaults;
}

function saveYAxisCustom() {
  try {
    localStorage.setItem(Y_SCALE_STORAGE_KEY, JSON.stringify(yAxisCustom));
  } catch (e) {
    // Ignore quota errors
  }
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function parseSamplesChrono(samples) {
  if (!samples || !samples.length) return [];
  const list = [];
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    if (!s || !s.timestamp_utc) continue;
    const ts = new Date(s.timestamp_utc).getTime();
    if (!isNaN(ts) && ts > 0) {
      list.push({ sample: s, ts });
    }
  }
  list.sort((a, b) => a.ts - b.ts);
  return list;
}

/**
 * Classifies each sample into 0=Standby, 1=Solo PdC, 2=Solo Grundfos, 3=PdC+Grundfos,
 * smoothing isolated single-sample nulls caused by transient Wi-Fi/cloud drops.
 */
function classifyActivityStates(chronoFiltered) {
  const n = chronoFiltered.length;
  const raw = chronoFiltered.map(({ sample, ts }) => {
    const compKnown = sample.compressor_active != null || sample.compressor_modulation_percent != null;
    const compOn = compKnown ? (sample.compressor_active === 1 || (Number(sample.compressor_modulation_percent) || 0) > 0) : null;
    const gfKnown = sample.grundfos_pump_active != null;
    const gfOn = gfKnown ? (sample.grundfos_pump_active === 1) : null;
    return { ts, compOn, gfOn };
  });

  const maxNeighborSpan = 20 * 60 * 1000;
  return raw.map((item, i) => {
    let comp = item.compOn;
    if (comp === null) {
      comp = (i > 0 && i < n - 1 && (raw[i + 1].ts - raw[i - 1].ts) <= maxNeighborSpan && raw[i - 1].compOn === true && raw[i + 1].compOn === true);
    }
    let gf = item.gfOn;
    if (gf === null) {
      gf = (i > 0 && i < n - 1 && (raw[i + 1].ts - raw[i - 1].ts) <= maxNeighborSpan && raw[i - 1].gfOn === true && raw[i + 1].gfOn === true);
    }
    const state = (comp ? 1 : 0) + (gf ? 2 : 0);
    return { ts: item.ts, state };
  });
}

/**
 * Groups consecutive active states and snaps directly-adjacent state transitions
 * (e.g., Solo GF -> PdC + GF -> Solo PdC) at their midpoint so bands sit flush
 * without visual gaps between transitions, while never bleeding into OFF samples.
 */
function buildActivityRuns(states) {
  const runs = [];
  let cur = null;
  let prevTs = null;
  const maxGapMs = 25 * 60 * 1000;

  for (let i = 0; i < states.length; i++) {
    const { ts, state } = states[i];
    if (state === 0) {
      if (cur) {
        runs.push(cur);
        cur = null;
      }
    } else if (cur && cur.state === state && prevTs !== null && (ts - prevTs) <= maxGapMs) {
      cur.endTs = ts;
      cur.endIdx = i;
    } else {
      if (cur) runs.push(cur);
      cur = { state, startTs: ts, endTs: ts, startIdx: i, endIdx: i, segStart: ts, segEnd: ts };
    }
    prevTs = ts;
  }
  if (cur) runs.push(cur);

  // Join directly-adjacent runs seamlessly at midpoint; pad isolated 1-sample runs
  for (let i = 0; i < runs.length; i++) {
    const r = runs[i];
    const hasAdjacentPrev = i > 0 && r.startIdx === runs[i - 1].endIdx + 1 && (r.startTs - runs[i - 1].endTs) <= maxGapMs;
    const hasAdjacentNext = i < runs.length - 1 && runs[i + 1].startIdx === r.endIdx + 1 && (runs[i + 1].startTs - r.endTs) <= maxGapMs;

    if (hasAdjacentPrev) {
      const mid = (runs[i - 1].endTs + r.startTs) / 2;
      runs[i - 1].segEnd = mid;
      r.segStart = mid;
    } else if (r.startTs === r.endTs && !hasAdjacentNext) {
      r.segStart = r.startTs - 150000;
    } else {
      r.segStart = r.startTs;
    }

    if (!hasAdjacentNext) {
      if (r.startTs === r.endTs && !hasAdjacentPrev) {
        r.segEnd = r.endTs + 150000;
      } else {
        r.segEnd = r.endTs;
      }
    }
  }

  return runs;
}

const activityBandsPlugin = {
  id: "activityBands",
  beforeDatasetsDraw(chart) {
    const runs = chart._activityRuns;
    const area = chart.chartArea;
    const xScale = chart.scales && chart.scales.x;
    if (!runs || !runs.length || !area || !xScale) return;

    const ctx = chart.ctx;
    const viewMin = xScale.min;
    const viewMax = xScale.max;

    ctx.save();
    ctx.beginPath();
    ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
    ctx.clip();

    for (let i = 0; i < runs.length; i++) {
      const r = runs[i];
      if (!visibleActivityBands[r.state]) continue;
      const style = ACTIVITY_STYLES[r.state];
      if (!style) continue;

      const t1 = r.segStart;
      const t2 = r.segEnd;
      if (t2 < viewMin || t1 > viewMax) continue;

      let x1 = xScale.getPixelForValue(t1);
      let x2 = xScale.getPixelForValue(t2);
      if (x2 - x1 < 4) {
        const mid = (x1 + x2) / 2;
        x1 = mid - 2;
        x2 = mid + 2;
      }
      const w = x2 - x1;

      ctx.fillStyle = style.fill;
      ctx.fillRect(x1, area.top, w, area.bottom - area.top);

      // Top 6px status ribbon for unmistakable visibility even when many traces overlap
      ctx.fillStyle = style.ribbon;
      ctx.fillRect(x1, area.top, w, 6);
    }

    ctx.restore();
  },
};

function initCharts(samples) {
  currentSamples = samples || [];
  renderChannelPills();
  initChartControls();
  buildChart();
}

function initChartControls() {
  const modeBtn = document.getElementById("btnChartModeToggle");
  if (modeBtn && modeBtn.dataset.bound !== "1") {
    modeBtn.dataset.bound = "1";
    modeBtn.addEventListener("click", () => {
      chartInteractionMode = (chartInteractionMode === "read") ? "pan" : "read";
      updateModeButtonUI();
      if (telemetryChart) {
        telemetryChart.options.plugins.tooltip.enabled = (chartInteractionMode === "read");
        if (chartInteractionMode === "pan") {
          telemetryChart.setActiveElements([]);
          if (telemetryChart.tooltip) telemetryChart.tooltip.setActiveElements([], { x: 0, y: 0 });
        }
        telemetryChart.update("none");
      }
      if (typeof showToast === "function") {
        showToast(chartInteractionMode === "pan" ? "✋ 1 dito sposta in X • 2 dita pinch zoom" : "👆 1 dito legge i valori • 2 dita zoom/sposta X");
      }
    });
  }

  const resetBtn = document.getElementById("btnResetChartZoom");
  if (resetBtn && resetBtn.dataset.bound !== "1") {
    resetBtn.dataset.bound = "1";
    resetBtn.addEventListener("click", resetChartXZoom);
  }

  const pillTemp = document.getElementById("btnScaleYTemp");
  if (pillTemp && pillTemp.dataset.bound !== "1") {
    pillTemp.dataset.bound = "1";
    pillTemp.addEventListener("click", () => openYAxisModal("yTemp"));
  }

  const pillOther = document.getElementById("btnScaleYOther");
  if (pillOther && pillOther.dataset.bound !== "1") {
    pillOther.dataset.bound = "1";
    pillOther.addEventListener("click", () => openYAxisModal("yOther"));
  }

  document.querySelectorAll(".activity-legend-btn").forEach(btn => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const band = parseInt(btn.dataset.band, 10);
      if (![1, 2, 3].includes(band)) return;
      visibleActivityBands[band] = !visibleActivityBands[band];
      btn.classList.toggle("active", visibleActivityBands[band]);
      if (telemetryChart) telemetryChart.update("none");
    });
  });

  bindYAxisModalEvents();
  updateModeButtonUI();
  updateAxisPillsUI();
}

function updateModeButtonUI() {
  const modeBtn = document.getElementById("btnChartModeToggle");
  if (!modeBtn) return;
  const isPan = chartInteractionMode === "pan";
  modeBtn.textContent = isPan ? "✋ Sposta" : "👆 Leggi";
  modeBtn.classList.toggle("active", isPan);
}

function updateResetButtonUI() {
  const resetBtn = document.getElementById("btnResetChartZoom");
  if (!resetBtn) return;
  resetBtn.style.display = xZoomRange ? "inline-flex" : "none";
}

function updateAxisPillsUI() {
  for (const axisId of ["yTemp", "yOther"]) {
    const btn = document.getElementById(axisId === "yTemp" ? "btnScaleYTemp" : "btnScaleYOther");
    if (!btn) continue;
    const cfg = yAxisCustom[axisId];
    const short = Y_AXIS_CONFIG[axisId].shortLabel;
    if (cfg.locked) {
      btn.textContent = `${short}: ${formatCompactNum(cfg.min)}..${formatCompactNum(cfg.max)} 🔒`;
      btn.classList.add("locked");
    } else {
      btn.textContent = `${short}: Auto`;
      btn.classList.remove("locked");
    }
  }
}

function formatCompactNum(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function resetChartXZoom() {
  xZoomRange = null;
  yAutoFrozen = { yTemp: null, yOther: null };
  updateResetButtonUI();
  if (!telemetryChart) return;
  const chrono = parseSamplesChrono(currentSamples);
  const bounds = getFullXBounds(chrono, activeTimeframeHours);
  if (bounds.min !== undefined && bounds.max !== undefined) {
    telemetryChart.options.scales.x.min = bounds.min;
    telemetryChart.options.scales.x.max = bounds.max;
  } else {
    delete telemetryChart.options.scales.x.min;
    delete telemetryChart.options.scales.x.max;
  }
  applyYScaleOptions(telemetryChart);
  telemetryChart.update("none");
}

function applyYScaleOptions(chart) {
  if (!chart || !chart.options || !chart.options.scales) return;
  for (const axisId of ["yTemp", "yOther"]) {
    const scaleOpt = chart.options.scales[axisId];
    if (!scaleOpt) continue;
    const custom = yAxisCustom[axisId];
    if (custom && custom.locked) {
      scaleOpt.min = custom.min;
      scaleOpt.max = custom.max;
    } else if (xZoomRange !== null && yAutoFrozen[axisId]) {
      scaleOpt.min = yAutoFrozen[axisId].min;
      scaleOpt.max = yAutoFrozen[axisId].max;
    } else {
      delete scaleOpt.min;
      delete scaleOpt.max;
    }
  }
  updateAxisPillsUI();
}

function freezeAutoYIfNeeded() {
  if (!telemetryChart || !telemetryChart.scales) return;
  for (const axisId of ["yTemp", "yOther"]) {
    if (!yAxisCustom[axisId].locked && !yAutoFrozen[axisId]) {
      const sc = telemetryChart.scales[axisId];
      if (sc && typeof sc.min === "number" && typeof sc.max === "number" && sc.max > sc.min) {
        yAutoFrozen[axisId] = { min: sc.min, max: sc.max };
      }
    }
  }
}

function updateChartData(samples) {
  currentSamples = samples || [];
  if (!telemetryChart) {
    renderChannelPills();
    initChartControls();
    buildChart();
    return;
  }

  const chronoAll = parseSamplesChrono(currentSamples);
  const fullBounds = getFullXBounds(chronoAll, activeTimeframeHours);
  const chronoFiltered = filterChronoByBounds(chronoAll, fullBounds);

  const states = classifyActivityStates(chronoFiltered);
  telemetryChart._activityChrono = chronoFiltered;
  telemetryChart._activityStates = states;
  telemetryChart._activityRuns = buildActivityRuns(states);
  telemetryChart.data.datasets = getDatasets(chronoFiltered);

  if (xZoomRange && fullBounds.min !== undefined && fullBounds.max !== undefined) {
    const fullSpan = Math.max(MIN_X_SPAN_MS, fullBounds.max - fullBounds.min);
    const curSpan = clamp(xZoomRange.max - xZoomRange.min, Math.min(MIN_X_SPAN_MS, fullSpan), fullSpan);
    const minVal = clamp(xZoomRange.min, fullBounds.min, fullBounds.max - curSpan);
    xZoomRange = { min: minVal, max: minVal + curSpan };
    telemetryChart.options.scales.x.min = xZoomRange.min;
    telemetryChart.options.scales.x.max = xZoomRange.max;
  } else if (fullBounds.min !== undefined && fullBounds.max !== undefined) {
    telemetryChart.options.scales.x.min = fullBounds.min;
    telemetryChart.options.scales.x.max = fullBounds.max;
  } else {
    delete telemetryChart.options.scales.x.min;
    delete telemetryChart.options.scales.x.max;
  }

  applyYScaleOptions(telemetryChart);
  updateResetButtonUI();
  telemetryChart.update();
}

function setChartTimeframe(hours) {
  activeTimeframeHours = hours;
  xZoomRange = null;
  yAutoFrozen = { yTemp: null, yOther: null };
  updateResetButtonUI();

  const container = document.getElementById("chartTimeframeButtons");
  if (container) {
    container.querySelectorAll(".btn-filter").forEach(btn => {
      btn.classList.toggle("active", parseInt(btn.dataset.hours, 10) === hours);
    });
  }
  updateChartData(currentSamples);
}

function getFullXBounds(chronoAll, hours) {
  if (!chronoAll || chronoAll.length === 0) {
    return { min: undefined, max: undefined };
  }
  const firstTs = chronoAll[0].ts;
  const lastTs = chronoAll[chronoAll.length - 1].ts;
  if (hours <= 0) {
    const pad = firstTs === lastTs ? 15 * 60 * 1000 : 0;
    return { min: firstTs - pad, max: lastTs + pad };
  }
  const latestMs = Math.max(Date.now(), lastTs);
  const cutoff = latestMs - hours * 60 * 60 * 1000;
  return { min: cutoff, max: latestMs };
}

function filterChronoByBounds(chronoAll, bounds) {
  if (!chronoAll || chronoAll.length === 0) return [];
  if (bounds.min === undefined) return chronoAll;
  const filtered = chronoAll.filter(item => item.ts >= bounds.min && item.ts <= bounds.max);
  return filtered.length > 0 ? filtered : chronoAll.slice(-Math.min(50, chronoAll.length));
}

function getDatasets(chronoFiltered) {
  return CHANNEL_DEFS.filter(ch => ch.active).map(ch => {
    const points = chronoFiltered.map(({ sample, ts }) => {
      const val = ch.computed ? ch.computed(sample) : sample[ch.key];
      const num = (val !== null && val !== undefined && val !== "") ? Number(val) : null;
      return {
        x: ts,
        y: (num !== null && !isNaN(num)) ? num : null,
      };
    });

    return {
      label: ch.label,
      data: points,
      borderColor: ch.color,
      backgroundColor: ch.color + "22",
      borderWidth: 2,
      pointRadius: points.length > 60 ? 0 : 2.5,
      pointHoverRadius: 6,
      tension: ch.spanGaps === false ? 0 : 0.2,
      borderDash: ch.borderDash || [],
      yAxisID: ch.yAxis,
      spanGaps: ch.spanGaps !== undefined ? ch.spanGaps : true,
    };
  });
}

function findClosestByTs(list, targetTs) {
  if (!list || !list.length) return null;
  let lo = 0;
  let hi = list.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid].ts < targetTs) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(list[lo - 1].ts - targetTs) < Math.abs(list[lo].ts - targetTs)) {
    return list[lo - 1];
  }
  return list[lo];
}

function buildChart() {
  const canvas = document.getElementById("telemetryChartCanvas");
  if (!canvas) return;

  const chronoAll = parseSamplesChrono(currentSamples);
  const bounds = getFullXBounds(chronoAll, activeTimeframeHours);
  const chronoFiltered = filterChronoByBounds(chronoAll, bounds);
  const states = classifyActivityStates(chronoFiltered);
  const runs = buildActivityRuns(states);

  if (telemetryChart) {
    telemetryChart.destroy();
  }

  const ctx = canvas.getContext("2d");
  telemetryChart = new Chart(ctx, {
    type: "line",
    plugins: [activityBandsPlugin],
    data: {
      datasets: getDatasets(chronoFiltered),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        mode: "nearest",
        axis: "x",
        intersect: false,
      },
      plugins: {
        legend: {
          display: false, // Custom pills legend below
        },
        tooltip: {
          enabled: chartInteractionMode === "read",
          backgroundColor: "rgba(15, 23, 42, 0.95)",
          titleColor: "#38bdf8",
          bodyColor: "#f8fafc",
          borderColor: "#334155",
          borderWidth: 1,
          padding: 10,
          cornerRadius: 8,
          callbacks: {
            title: function(items) {
              if (!items || !items.length) return "";
              const ts = items[0].parsed.x;
              const d = new Date(ts);
              const day = String(d.getDate()).padStart(2, "0");
              const mon = String(d.getMonth() + 1).padStart(2, "0");
              const h = String(d.getHours()).padStart(2, "0");
              const m = String(d.getMinutes()).padStart(2, "0");
              const s = String(d.getSeconds()).padStart(2, "0");
              return `${day}/${mon} ${h}:${m}:${s}`;
            },
            label: function(context) {
              const chDef = CHANNEL_DEFS.find(ch => ch.label === context.dataset.label);
              const unit = chDef ? chDef.unit : "";
              const val = context.parsed.y;
              const formattedVal = (val !== null && val !== undefined)
                ? (typeof val === "number" ? val.toLocaleString("it-IT", { maximumFractionDigits: 1 }) : val)
                : "--";
              return ` ${context.dataset.label}: ${formattedVal} ${unit}`.trim();
            },
            afterBody: function(items) {
              if (!items || !items.length || !telemetryChart) return [];
              const targetTs = items[0].parsed.x;
              const lines = [];
              const st = findClosestByTs(telemetryChart._activityStates, targetTs);
              if (st) {
                const info = ACTIVITY_STYLES[st.state];
                lines.push(info ? info.text : "⏸ Stato: Standby");
              }
              const rawEntry = findClosestByTs(telemetryChart._activityChrono, targetTs);
              if (rawEntry && rawEntry.sample) {
                const s = rawEntry.sample;
                const tin = s.indoor_temp_bticino_c != null ? `${Number(s.indoor_temp_bticino_c).toFixed(1)}°C` : "--";
                const sp = s.indoor_setpoint_bticino_c != null ? `${Number(s.indoor_setpoint_bticino_c).toFixed(1)}°C` : "--";
                const gfTxt = s.grundfos_pump_active === 1 ? "GF ON" : (s.grundfos_pump_active === 0 ? "GF OFF" : "GF --");
                lines.push(`🏠 Casa: ${tin} / SP ${sp} → ${gfTxt}`);
                if ((s.active_program || "").toLowerCase() === "standby") {
                  const potentialLwt = computeVitocalTargetLwt(s, true);
                  if (potentialLwt !== null) {
                    lines.push(`🎯 Curva PdC (in Standby): ${potentialLwt.toFixed(1)} °C`);
                  }
                }
                const phase = String(s.compressor_phase || "").toLowerCase();
                if (phase.includes("defrost")) {
                  lines.push(`❄️ SBRINAMENTO ATTIVO (${s.compressor_phase})`);
                }
                if (String(s.frost_protection_status || "").toLowerCase() === "on") {
                  lines.push("🛡️ Antigelo Hardware PdC ON");
                }
              }
              return lines;
            },
          },
        },
      },
      scales: {
        x: {
          type: "time",
          distribution: "linear",
          bounds: "ticks",
          min: xZoomRange ? xZoomRange.min : bounds.min,
          max: xZoomRange ? xZoomRange.max : bounds.max,
          time: {
            displayFormats: {
              millisecond: "HH:mm:ss",
              second: "HH:mm:ss",
              minute: "HH:mm",
              hour: "HH:mm",
              day: "dd/MM",
              month: "MM/yyyy",
              year: "yyyy",
            },
            tooltipFormat: "dd/MM/yyyy HH:mm:ss",
          },
          grid: { color: "rgba(51, 65, 85, 0.3)" },
          ticks: {
            color: "#94a3b8",
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 7,
            source: "auto",
            font: { size: 10 },
          },
        },
        yTemp: {
          type: "linear",
          position: "left",
          title: { display: true, text: "°C", color: "#94a3b8", font: { size: 10 } },
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#cbd5e1", font: { size: 10 } },
        },
        yOther: {
          type: "linear",
          position: "right",
          title: { display: true, text: "% / bar", color: "#94a3b8", font: { size: 10 } },
          grid: { drawOnChartArea: false },
          ticks: { color: "#cbd5e1", font: { size: 10 } },
        },
      },
    },
  });

  telemetryChart._activityChrono = chronoFiltered;
  telemetryChart._activityStates = states;
  telemetryChart._activityRuns = runs;
  applyYScaleOptions(telemetryChart);
  telemetryChart.update("none");

  attachChartInteractions(canvas);
}

function attachChartInteractions(canvas) {
  if (!canvas || canvas.dataset.interactionsBound === "1") return;
  canvas.dataset.interactionsBound = "1";

  let isPinching = false;
  let pinchState = null;
  let isPanning1F = false;
  let pan1State = null;
  let tapCandidate = null;
  let suppressSingleTouchUntilRelease = false;
  let isMouseDragging = false;
  let mouseDragState = null;
  let lastTouchTapAt = 0;

  function getRelativePoint(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function getActiveBounds() {
    const chrono = parseSamplesChrono(currentSamples);
    const full = getFullXBounds(chrono, activeTimeframeHours);
    const xScale = telemetryChart && telemetryChart.scales && telemetryChart.scales.x;
    const curMin = (xScale && typeof xScale.min === "number") ? xScale.min : full.min;
    const curMax = (xScale && typeof xScale.max === "number") ? xScale.max : full.max;
    return { full, curMin, curMax };
  }

  function applyXRange(reqMin, reqMax) {
    if (!telemetryChart) return;
    const chrono = parseSamplesChrono(currentSamples);
    const full = getFullXBounds(chrono, activeTimeframeHours);
    if (full.min === undefined || full.max === undefined || full.max <= full.min) return;

    const fullSpan = full.max - full.min;
    const minSpan = Math.min(MIN_X_SPAN_MS, fullSpan);
    const targetSpan = clamp(reqMax - reqMin, minSpan, fullSpan);

    // If essentially full width, snap cleanly back to unzoomed state
    if (targetSpan >= fullSpan * 0.995) {
      xZoomRange = null;
      yAutoFrozen = { yTemp: null, yOther: null };
      telemetryChart.options.scales.x.min = full.min;
      telemetryChart.options.scales.x.max = full.max;
    } else {
      const clampedMin = clamp(reqMin, full.min, full.max - targetSpan);
      xZoomRange = { min: clampedMin, max: clampedMin + targetSpan };
      telemetryChart.options.scales.x.min = xZoomRange.min;
      telemetryChart.options.scales.x.max = xZoomRange.max;
    }

    applyYScaleOptions(telemetryChart);
    updateResetButtonUI();
    telemetryChart.update("none");
  }

  function setTooltipTempEnabled(enabled) {
    if (!telemetryChart) return;
    telemetryChart.options.plugins.tooltip.enabled = enabled && (chartInteractionMode === "read");
    if (!enabled) {
      telemetryChart.setActiveElements([]);
      if (telemetryChart.tooltip) telemetryChart.tooltip.setActiveElements([], { x: 0, y: 0 });
    }
  }

  canvas.addEventListener("touchstart", (e) => {
    if (!telemetryChart || !telemetryChart.chartArea) return;
    const area = telemetryChart.chartArea;

    if (e.touches.length === 2) {
      e.preventDefault();
      isPinching = true;
      isPanning1F = false;
      tapCandidate = null;
      setTooltipTempEnabled(false);
      freezeAutoYIfNeeded();

      const p1 = getRelativePoint(e.touches[0].clientX, e.touches[0].clientY);
      const p2 = getRelativePoint(e.touches[1].clientX, e.touches[1].clientY);
      const dist = Math.max(20, Math.hypot(p2.x - p1.x, p2.y - p1.y));
      const midX = (p1.x + p2.x) / 2;
      const { curMin, curMax } = getActiveBounds();
      if (curMin === undefined || curMax === undefined) return;

      pinchState = {
        startDist: dist,
        startMin: curMin,
        startMax: curMax,
        startFrac: clamp((midX - area.left) / Math.max(1, area.right - area.left), 0, 1),
      };
      return;
    }

    if (e.touches.length === 1) {
      if (suppressSingleTouchUntilRelease) return;
      const pt = getRelativePoint(e.touches[0].clientX, e.touches[0].clientY);
      tapCandidate = { x: pt.x, y: pt.y, time: Date.now(), moved: false };

      if (chartInteractionMode === "pan" && pt.x >= area.left - 8 && pt.x <= area.right + 8) {
        const { curMin, curMax } = getActiveBounds();
        if (curMin !== undefined && curMax !== undefined) {
          isPanning1F = true;
          freezeAutoYIfNeeded();
          pan1State = { startX: pt.x, startMin: curMin, startMax: curMax };
        }
      }
    }
  }, { passive: false });

  canvas.addEventListener("touchmove", (e) => {
    if (!telemetryChart || !telemetryChart.chartArea) return;
    const area = telemetryChart.chartArea;
    const plotW = Math.max(1, area.right - area.left);

    if (e.touches.length === 2 && isPinching && pinchState) {
      e.preventDefault();
      const p1 = getRelativePoint(e.touches[0].clientX, e.touches[0].clientY);
      const p2 = getRelativePoint(e.touches[1].clientX, e.touches[1].clientY);
      const curDist = Math.max(20, Math.hypot(p2.x - p1.x, p2.y - p1.y));
      const curMidX = (p1.x + p2.x) / 2;

      const startSpan = pinchState.startMax - pinchState.startMin;
      const { full } = getActiveBounds();
      const fullSpan = (full.max !== undefined && full.min !== undefined) ? (full.max - full.min) : startSpan;
      const newSpan = clamp(startSpan * (pinchState.startDist / curDist), Math.min(MIN_X_SPAN_MS, fullSpan), fullSpan);
      const anchorTs = pinchState.startMin + pinchState.startFrac * startSpan;
      const curFrac = clamp((curMidX - area.left) / plotW, 0, 1);
      const newMin = anchorTs - curFrac * newSpan;
      applyXRange(newMin, newMin + newSpan);
      return;
    }

    if (e.touches.length === 1 && !suppressSingleTouchUntilRelease) {
      const pt = getRelativePoint(e.touches[0].clientX, e.touches[0].clientY);
      if (tapCandidate && Math.hypot(pt.x - tapCandidate.x, pt.y - tapCandidate.y) > 10) {
        tapCandidate.moved = true;
      }

      if (chartInteractionMode === "pan" && isPanning1F && pan1State) {
        e.preventDefault();
        const dx = pt.x - pan1State.startX;
        const span = pan1State.startMax - pan1State.startMin;
        const shiftMs = -(dx / plotW) * span;
        applyXRange(pan1State.startMin + shiftMs, pan1State.startMax + shiftMs);
      } else if (chartInteractionMode === "read" && tapCandidate && tapCandidate.x >= area.left && tapCandidate.x <= area.right) {
        // Keep 1-finger horizontal value scrubbing locked to canvas without page scroll
        e.preventDefault();
      }
    }
  }, { passive: false });

  function handleTouchEnd(e) {
    if (isPinching && e.touches.length < 2) {
      isPinching = false;
      pinchState = null;
      if (e.touches.length === 1) {
        suppressSingleTouchUntilRelease = true;
      }
    }

    if (e.touches.length === 0) {
      setTooltipTempEnabled(true);
      if (telemetryChart && chartInteractionMode === "read") {
        telemetryChart.update("none");
      }

      if (!suppressSingleTouchUntilRelease && tapCandidate && !tapCandidate.moved && (Date.now() - tapCandidate.time) < 350 && telemetryChart && telemetryChart.chartArea) {
        const area = telemetryChart.chartArea;
        if (tapCandidate.y >= area.top - 12 && tapCandidate.y <= area.bottom + 18) {
          if (tapCandidate.x <= area.left + 14) {
            lastTouchTapAt = Date.now();
            openYAxisModal("yTemp");
          } else if (tapCandidate.x >= area.right - 14) {
            lastTouchTapAt = Date.now();
            openYAxisModal("yOther");
          }
        }
      }

      isPanning1F = false;
      pan1State = null;
      tapCandidate = null;
      suppressSingleTouchUntilRelease = false;
    }
  }

  canvas.addEventListener("touchend", handleTouchEnd);
  canvas.addEventListener("touchcancel", handleTouchEnd);

  // Desktop mouse wheel X-only zoom
  canvas.addEventListener("wheel", (e) => {
    if (!telemetryChart || !telemetryChart.chartArea) return;
    const area = telemetryChart.chartArea;
    const pt = getRelativePoint(e.clientX, e.clientY);
    if (pt.x < area.left || pt.x > area.right) return;
    e.preventDefault();

    freezeAutoYIfNeeded();
    const { full, curMin, curMax } = getActiveBounds();
    if (curMin === undefined || curMax === undefined || full.min === undefined) return;

    const fullSpan = full.max - full.min;
    const curSpan = curMax - curMin;
    const factor = e.deltaY > 0 ? 1.2 : 0.83;
    const newSpan = clamp(curSpan * factor, Math.min(MIN_X_SPAN_MS, fullSpan), fullSpan);
    const frac = clamp((pt.x - area.left) / Math.max(1, area.right - area.left), 0, 1);
    const anchorTs = curMin + frac * curSpan;
    const newMin = anchorTs - frac * newSpan;
    applyXRange(newMin, newMin + newSpan);
  }, { passive: false });

  // Desktop mouse drag X-pan (when in Pan mode or holding Shift)
  canvas.addEventListener("mousedown", (e) => {
    if (!telemetryChart || !telemetryChart.chartArea) return;
    if (chartInteractionMode !== "pan" && !e.shiftKey) return;
    const pt = getRelativePoint(e.clientX, e.clientY);
    const area = telemetryChart.chartArea;
    if (pt.x < area.left || pt.x > area.right) return;
    const { curMin, curMax } = getActiveBounds();
    if (curMin === undefined || curMax === undefined) return;
    isMouseDragging = true;
    freezeAutoYIfNeeded();
    mouseDragState = { startX: pt.x, startMin: curMin, startMax: curMax };
  });

  window.addEventListener("mousemove", (e) => {
    if (!isMouseDragging || !mouseDragState || !telemetryChart || !telemetryChart.chartArea) return;
    const area = telemetryChart.chartArea;
    const pt = getRelativePoint(e.clientX, e.clientY);
    const dx = pt.x - mouseDragState.startX;
    const span = mouseDragState.startMax - mouseDragState.startMin;
    const shiftMs = -(dx / Math.max(1, area.right - area.left)) * span;
    applyXRange(mouseDragState.startMin + shiftMs, mouseDragState.startMax + shiftMs);
  });

  window.addEventListener("mouseup", () => {
    isMouseDragging = false;
    mouseDragState = null;
  });

  // Desktop click on left/right Y-axis zones
  canvas.addEventListener("click", (e) => {
    if (Date.now() - lastTouchTapAt < 600) return;
    if (!telemetryChart || !telemetryChart.chartArea) return;
    const pt = getRelativePoint(e.clientX, e.clientY);
    const area = telemetryChart.chartArea;
    if (pt.y < area.top - 12 || pt.y > area.bottom + 18) return;
    if (pt.x <= area.left + 14) {
      openYAxisModal("yTemp");
    } else if (pt.x >= area.right - 14) {
      openYAxisModal("yOther");
    }
  });
}

// -------------------------------------------------------------
// Y-AXIS RANGE MODAL
// -------------------------------------------------------------
function openYAxisModal(axisId) {
  const modal = document.getElementById("yAxisModal");
  const titleEl = document.getElementById("yAxisModalTitle");
  const hintEl = document.getElementById("yAxisModalHint");
  const presetsEl = document.getElementById("yAxisPresets");
  const minInput = document.getElementById("inputYMin");
  const maxInput = document.getElementById("inputYMax");
  if (!modal || !Y_AXIS_CONFIG[axisId]) return;

  activeModalAxis = axisId;
  const cfg = Y_AXIS_CONFIG[axisId];
  const custom = yAxisCustom[axisId];
  const liveScale = telemetryChart && telemetryChart.scales ? telemetryChart.scales[axisId] : null;
  const curMin = custom.locked ? custom.min : (liveScale && typeof liveScale.min === "number" ? Number(liveScale.min.toFixed(1)) : 0);
  const curMax = custom.locked ? custom.max : (liveScale && typeof liveScale.max === "number" ? Number(liveScale.max.toFixed(1)) : 40);

  if (titleEl) titleEl.textContent = cfg.title;
  if (hintEl) {
    hintEl.textContent = custom.locked
      ? `Bloccato manualmente (${curMin} .. ${curMax}). Resta fisso durante lo zoom in X.`
      : `Attualmente automatico (${curMin} .. ${curMax}). Fissa un range per mantenere Y bloccato.`;
  }
  if (minInput) minInput.value = curMin;
  if (maxInput) maxInput.value = curMax;

  if (presetsEl) {
    presetsEl.innerHTML = cfg.presets.map(p =>
      `<button type="button" class="modal-preset-btn" data-min="${p.min}" data-max="${p.max}">${p.label}</button>`
    ).join("");
    presetsEl.querySelectorAll(".modal-preset-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        if (minInput) minInput.value = btn.dataset.min;
        if (maxInput) maxInput.value = btn.dataset.max;
      });
    });
  }

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeYAxisModal() {
  const modal = document.getElementById("yAxisModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  activeModalAxis = null;
}

function bindYAxisModalEvents() {
  const modal = document.getElementById("yAxisModal");
  if (!modal || modal.dataset.bound === "1") return;
  modal.dataset.bound = "1";

  const closeBtn = document.getElementById("btnCloseYAxisModal");
  const cancelBtn = document.getElementById("btnCancelYScale");
  const applyBtn = document.getElementById("btnApplyYScale");
  const resetBtn = document.getElementById("btnResetYScale");

  if (closeBtn) closeBtn.addEventListener("click", closeYAxisModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeYAxisModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeYAxisModal();
  });

  if (applyBtn) {
    applyBtn.addEventListener("click", () => {
      if (!activeModalAxis) return;
      const minVal = parseFloat(document.getElementById("inputYMin").value);
      const maxVal = parseFloat(document.getElementById("inputYMax").value);
      if (isNaN(minVal) || isNaN(maxVal) || maxVal <= minVal) {
        if (typeof showToast === "function") {
          showToast("⚠️ Inserisci valori validi (Y Max deve essere maggiore di Y Min).");
        }
        return;
      }
      yAxisCustom[activeModalAxis] = { locked: true, min: minVal, max: maxVal };
      saveYAxisCustom();
      applyYScaleOptions(telemetryChart);
      if (telemetryChart) telemetryChart.update("none");
      if (typeof showToast === "function") {
        showToast(`🔒 Asse ${Y_AXIS_CONFIG[activeModalAxis].shortLabel} bloccato: ${minVal} .. ${maxVal}`);
      }
      closeYAxisModal();
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (!activeModalAxis) return;
      yAxisCustom[activeModalAxis] = { locked: false, min: null, max: null };
      yAutoFrozen[activeModalAxis] = null;
      saveYAxisCustom();
      applyYScaleOptions(telemetryChart);
      if (telemetryChart) {
        telemetryChart.update("none");
        if (xZoomRange !== null) {
          freezeAutoYIfNeeded();
          applyYScaleOptions(telemetryChart);
          telemetryChart.update("none");
        }
      }
      if (typeof showToast === "function") {
        showToast(`✨ Asse ${Y_AXIS_CONFIG[activeModalAxis].shortLabel} ripristinato in Auto`);
      }
      closeYAxisModal();
    });
  }
}

function renderChannelPills() {
  const container = document.getElementById("channelPillsContainer");
  if (!container) return;

  container.innerHTML = CHANNEL_DEFS.map((ch, idx) => `
    <button type="button" class="channel-pill ${ch.active ? "active" : ""}" data-idx="${idx}" style="color: ${ch.color}">
      <span class="channel-dot" style="background-color: ${ch.color}"></span>
      ${ch.label}
    </button>
  `).join("");

  container.querySelectorAll(".channel-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      CHANNEL_DEFS[idx].active = !CHANNEL_DEFS[idx].active;
      btn.classList.toggle("active", CHANNEL_DEFS[idx].active);
      yAutoFrozen = { yTemp: null, yOther: null };
      updateChartData(currentSamples);
    });
  });
}
