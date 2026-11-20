/**
 * Pro-Grade Telemetry Charts for Vitocal Remote Mobile App.
 * Features:
 * - Chart.js v4 continuous TimeScale (date-fns adapter)
 * - High-contrast colorblind-safe palette & distinct stroke patterns
 * - 1-tap View Presets + structured Grafana-style legend with live/scrubbed readouts & Solo isolate
 * - Setpoint-saturation cutoff detector (`🎯 Stop SP`) with anti-overlap diamond pointers & tooltips
 * - Defrost markers & vertical crosshair
 * - Seamless 3-color PdC / Grundfos activity bands with zoom-aware ON-duration pills
 * - X-only 2-finger pinch + drag, 1-finger Read/Pan toggle, `⏭️ Ciclo` jump, locked/tappable Y-axes
 * - Dynamic visible-window KPI summary strip (`#chartWindowStats`)
 */

let telemetryChart = null;
let currentSamples = [];
let activeTimeframeHours = 24;
let activePresetKey = "thermo";

let chartInteractionMode = "read"; // "read" (1-finger tooltip) | "pan" (1-finger X drag)
let xZoomRange = null; // { min, max } when zoomed/panned in X
let yAutoFrozen = { yTemp: null, yOther: null };
let activeModalAxis = null;
let visibleActivityBands = { 1: true, 2: true, 3: true };
let showSetpointMarkers = true;
let soloBackupActive = null;

const MIN_X_SPAN_MS = 15 * 60 * 1000;
const Y_SCALE_STORAGE_KEY = "vitocal_y_scales";
const EXTRA_CHANNELS_STORAGE_KEY = "vitocal_extra_channels";

let yAxisCustom = loadYAxisCustom();

function estimateSamplePower(sample) {
  if (!sample) return { pElecKw: 0, pThermalKw: 0, cop: null };
  const isComp = sample.compressor_active === 1 || (Number(sample.compressor_modulation_percent) || 0) > 0;
  if (!isComp) return { pElecKw: 0.025, pThermalKw: 0, cop: null };
  const mod = Number(sample.compressor_modulation_percent) || 0;
  const pElecKw = 0.70 + (mod / 100.0) * 2.80;
  const cop = (sample.cop_heating != null && Number(sample.cop_heating) > 0) ? Number(sample.cop_heating) : 3.1;
  return { pElecKw, pThermalKw: pElecKw * cop, cop };
}

function loadExtraChannelsSet() {
  try {
    const raw = localStorage.getItem(EXTRA_CHANNELS_STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) return new Set(arr);
    }
  } catch (e) {}
  return new Set();
}

function saveExtraChannelsSet() {
  try {
    const extras = CHANNEL_DEFS.filter(c => !c.defaultInLegend && c.inLegend).map(c => c.key);
    localStorage.setItem(EXTRA_CHANNELS_STORAGE_KEY, JSON.stringify(extras));
  } catch (e) {}
}

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
  // --- Default Core Channels ---
  { key: "pdc_supply_temp_c", label: "Mandata PdC", unit: "°C", color: "#ff3b30", yAxis: "yTemp", group: "temp", borderWidth: 2.4, active: true, defaultInLegend: true, keywords: "lwt mandata primaria pdc" },
  {
    key: "_target_lwt_c",
    label: "Target LWT Curva",
    unit: "°C",
    color: "#e879f9",
    yAxis: "yTemp",
    group: "temp",
    borderDash: [7, 4],
    borderWidth: 2.0,
    active: true,
    defaultInLegend: true,
    spanGaps: false,
    keywords: "target lwt curva climatica setpoint mandata",
    computed: (s) => computeVitocalTargetLwt(s, false),
  },
  { key: "buffer_temp_c", label: "Puffer 200L", unit: "°C", color: "#ff9f0a", yAxis: "yTemp", group: "temp", borderWidth: 2.2, active: true, defaultInLegend: true, keywords: "puffer accumulo inerziale 200l" },
  { key: "indoor_temp_bticino_c", label: "T Casa Corridoio", unit: "°C", color: "#22c55e", yAxis: "yTemp", group: "temp", borderWidth: 2.4, active: true, defaultInLegend: true, keywords: "interna casa corridoio bticino smarther" },
  { key: "external_temp_c", label: "T Esterna OAT", unit: "°C", color: "#00d4ff", yAxis: "yTemp", group: "temp", borderWidth: 2.0, active: true, defaultInLegend: true, keywords: "esterna oat fuori sonda climatica" },
  { key: "pdc_return_temp_c", label: "Ritorno PdC", unit: "°C", color: "#818cf8", yAxis: "yTemp", group: "temp", borderDash: [4, 3], borderWidth: 2.0, active: false, defaultInLegend: true, keywords: "ewt ritorno scambiatore primaria" },
  {
    key: "_delta_lwt_ewt",
    label: "ΔT Primario (LWT−EWT)",
    unit: "K",
    color: "#38bdf8",
    yAxis: "yTemp",
    group: "temp",
    borderDash: [5, 2],
    borderWidth: 2.1,
    active: false,
    defaultInLegend: true,
    keywords: "delta lwt ewt mandata ritorno primario salto termico",
    computed: (s) => (s && s.pdc_supply_temp_c != null && s.pdc_return_temp_c != null)
      ? Math.round((Number(s.pdc_supply_temp_c) - Number(s.pdc_return_temp_c)) * 10) / 10
      : null,
  },
  { key: "dhw_storage_temp_c", label: "Bollitore ACS", unit: "°C", color: "#c084fc", yAxis: "yTemp", group: "temp", borderDash: [2, 3], borderWidth: 2.0, active: false, defaultInLegend: true, keywords: "acs sanitario bollitore acqua calda" },
  { key: "indoor_setpoint_bticino_c", label: "Setpoint BTicino", unit: "°C", color: "#a3e635", yAxis: "yTemp", group: "temp", stepped: true, borderDash: [5, 4], borderWidth: 1.8, active: false, defaultInLegend: true, keywords: "setpoint bticino termostato" },
  {
    key: "_delta_sup_buf",
    label: "ΔT Mandata−Puffer",
    unit: "K",
    color: "#fb7185",
    yAxis: "yTemp",
    group: "temp",
    borderDash: [2, 2],
    borderWidth: 1.8,
    active: false,
    defaultInLegend: true,
    keywords: "delta mandata puffer stratificazione scambio",
    computed: (s) => (s && s.pdc_supply_temp_c != null && s.buffer_temp_c != null)
      ? Math.round((Number(s.pdc_supply_temp_c) - Number(s.buffer_temp_c)) * 10) / 10
      : null,
  },
  {
    key: "compressor_modulation_percent",
    label: "Modulazione Inverter",
    unit: "%",
    color: "#fde047",
    yAxis: "yOther",
    group: "system",
    borderWidth: 1.8,
    fill: true,
    backgroundColor: "rgba(253, 224, 71, 0.08)",
    active: true,
    defaultInLegend: true,
    keywords: "modulazione inverter compressore percentuale carico",
  },
  { key: "primary_pump_rotation_percent", label: "Circolatore Primario P1", unit: "%", color: "#34d399", yAxis: "yOther", group: "system", borderWidth: 2.0, active: false, defaultInLegend: true, keywords: "circolatore primario p1 velocità rotazione pompa" },
  { key: "hot_gas_pressure_bar", label: "Gas Caldo", unit: "bar", color: "#f472b6", yAxis: "yOther", group: "system", borderDash: [6, 3], borderWidth: 1.8, active: false, defaultInLegend: true, keywords: "pressione gas caldo bar refrigerante" },
  { key: "cop_heating", label: "COP Riscald.", unit: "COP", color: "#2dd4bf", yAxis: "yOther", group: "system", borderWidth: 2.0, active: false, defaultInLegend: true, keywords: "cop rendimento efficienza riscaldamento" },
  { key: "humidity_percent", label: "Umidità Casa", unit: "%", color: "#94a3b8", yAxis: "yOther", group: "system", borderDash: [3, 4], borderWidth: 1.8, active: false, defaultInLegend: true, keywords: "umidità relativa casa" },

  // --- Extra Searchable Channels (Added on demand via 🔍 + Canali) ---
  { key: "hot_gas_temp_c", label: "T Gas Caldo Frigo", unit: "°C", color: "#f97316", yAxis: "yTemp", group: "temp", borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "temperatura gas caldo scarico compressore frigo" },
  { key: "liquid_gas_temp_c", label: "T Gas Liquido Frigo", unit: "°C", color: "#06b6d4", yAxis: "yTemp", group: "temp", borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "temperatura gas liquido condensatore frigo" },
  { key: "suction_gas_temp_c", label: "T Gas Aspirazione", unit: "°C", color: "#60a5fa", yAxis: "yTemp", group: "temp", borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "temperatura gas aspirazione evaporatore frigo" },
  {
    key: "_delta_buf_ewt",
    label: "ΔT Puffer−Ritorno",
    unit: "K",
    color: "#fbbf24",
    yAxis: "yTemp",
    group: "temp",
    borderDash: [4, 2],
    borderWidth: 1.8,
    active: false,
    defaultInLegend: false,
    keywords: "delta puffer ritorno ewt stratificazione secondario",
    computed: (s) => (s && s.buffer_temp_c != null && s.pdc_return_temp_c != null)
      ? Math.round((Number(s.buffer_temp_c) - Number(s.pdc_return_temp_c)) * 10) / 10
      : null,
  },
  {
    key: "_delta_in_oat",
    label: "ΔT Casa−Esterno",
    unit: "K",
    color: "#4ade80",
    yAxis: "yTemp",
    group: "temp",
    borderDash: [3, 3],
    borderWidth: 1.8,
    active: false,
    defaultInLegend: false,
    keywords: "salto termico casa esterna dispersione involucro",
    computed: (s) => (s && s.indoor_temp_bticino_c != null && s.external_temp_c != null)
      ? Math.round((Number(s.indoor_temp_bticino_c) - Number(s.external_temp_c)) * 10) / 10
      : null,
  },
  { key: "normal_setpoint_c", label: "Setpoint Normale PdC", unit: "°C", color: "#f43f5e", yAxis: "yTemp", group: "temp", stepped: true, borderDash: [6, 3], borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "setpoint normale pdc curva" },
  { key: "reduced_setpoint_c", label: "Setpoint Ridotta PdC", unit: "°C", color: "#ec4899", yAxis: "yTemp", group: "temp", stepped: true, borderDash: [3, 3], borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "setpoint ridotta pdc curva" },
  { key: "dhw_setpoint_c", label: "Setpoint Bollitore ACS", unit: "°C", color: "#a855f7", yAxis: "yTemp", group: "temp", stepped: true, borderDash: [2, 3], borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "setpoint bollitore acs sanitario" },
  { key: "heating_curve_shift", label: "Curva Livello (Shift)", unit: "K", color: "#c084fc", yAxis: "yTemp", group: "temp", stepped: true, borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "curva shift livello parallelo" },
  {
    key: "_thermal_power_kw",
    label: "Potenza Termica Stimata",
    unit: "kWₜ",
    color: "#fb923c",
    yAxis: "yOther",
    group: "system",
    borderWidth: 2.0,
    active: false,
    defaultInLegend: false,
    keywords: "potenza resa termica kw calore",
    computed: (s) => s ? Number(estimateSamplePower(s).pThermalKw.toFixed(2)) : null,
  },
  {
    key: "_elec_power_kw",
    label: "Potenza Elettrica Stimata",
    unit: "kWₑ",
    color: "#eab308",
    yAxis: "yOther",
    group: "system",
    borderWidth: 1.8,
    active: false,
    defaultInLegend: false,
    keywords: "potenza elettrica assorbita kw consumo",
    computed: (s) => s ? Number(estimateSamplePower(s).pElecKw.toFixed(2)) : null,
  },
  { key: "cop_total", label: "COP Totale Macchina", unit: "COP", color: "#14b8a6", yAxis: "yOther", group: "system", borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "cop totale rendimento" },
  { key: "cop_dhw", label: "COP Sanitario ACS", unit: "COP", color: "#a78bfa", yAxis: "yOther", group: "system", borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "cop acs sanitario" },
  { key: "heating_curve_slope", label: "Curva Inclinazione (Slope)", unit: "", color: "#38bdf8", yAxis: "yOther", group: "system", stepped: true, borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "curva slope inclinazione" },
  {
    key: "_heating_rod_total_h",
    label: "Resistenza Backup (S1+S2)",
    unit: "h",
    color: "#ef4444",
    yAxis: "yOther",
    group: "system",
    stepped: true,
    borderWidth: 1.9,
    active: false,
    defaultInLegend: false,
    keywords: "resistenza elettrica backup s1 s2 runtime",
    computed: (s) => (s && (s.heating_rod_level1_s != null || s.heating_rod_level2_s != null))
      ? Number(((Number(s.heating_rod_level1_s || 0) + Number(s.heating_rod_level2_s || 0)) / 3600.0).toFixed(2))
      : null,
  },
  { key: "compressor_hours", label: "Ore Compressore", unit: "h", color: "#cbd5e1", yAxis: "yOther", group: "system", borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "ore compressore totali runtime" },
  { key: "compressor_starts", label: "Avvii Compressore", unit: "avvii", color: "#94a3b8", yAxis: "yOther", group: "system", stepped: true, borderWidth: 1.7, active: false, defaultInLegend: false, keywords: "avvii starts compressore accensioni" },
  { key: "grundfos_pump_active", label: "Stato Grundfos (0/1)", unit: "", color: "#10b981", yAxis: "yOther", group: "system", stepped: true, borderWidth: 1.8, active: false, defaultInLegend: false, keywords: "grundfos pompa rilancio consenso stato" },
];

(function hydrateChannelLegendFlags() {
  const savedExtras = loadExtraChannelsSet();
  for (let i = 0; i < CHANNEL_DEFS.length; i++) {
    const ch = CHANNEL_DEFS[i];
    ch.inLegend = Boolean(ch.defaultInLegend || savedExtras.has(ch.key));
  }
})();

const CHART_PRESETS = {
  thermo: ["pdc_supply_temp_c", "_target_lwt_c", "buffer_temp_c", "indoor_temp_bticino_c", "external_temp_c", "compressor_modulation_percent"],
  inverter: ["pdc_supply_temp_c", "pdc_return_temp_c", "_target_lwt_c", "_delta_lwt_ewt", "primary_pump_rotation_percent", "compressor_modulation_percent", "hot_gas_pressure_bar", "cop_heating"],
  home: ["indoor_temp_bticino_c", "indoor_setpoint_bticino_c", "external_temp_c", "buffer_temp_c", "humidity_percent"],
  all: null,
};

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
  1: { fill: "rgba(245, 158, 11, 0.14)", ribbon: "rgba(245, 158, 11, 0.90)", pillBorder: "#f59e0b", pillLabel: "PdC", text: "🔥 Stato: Solo PdC ON" },
  2: { fill: "rgba(56, 189, 248, 0.14)", ribbon: "rgba(56, 189, 248, 0.90)", pillBorder: "#38bdf8", pillLabel: "GF", text: "💧 Stato: Solo Grundfos ON" },
  3: { fill: "rgba(16, 185, 129, 0.19)", ribbon: "rgba(16, 185, 129, 0.94)", pillBorder: "#10b981", pillLabel: "PdC+GF", text: "⚡ Stato: PdC + Grundfos ON" },
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
  } catch (e) {}
  return defaults;
}

function saveYAxisCustom() {
  try {
    localStorage.setItem(Y_SCALE_STORAGE_KEY, JSON.stringify(yAxisCustom));
  } catch (e) {}
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function formatDurationCompact(minutes) {
  const m = Math.max(0, Math.round(minutes || 0));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${h}h` : `${h}h${String(rem).padStart(2, "0")}m`;
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
    return { ts: item.ts, state, comp: Boolean(comp), gf: Boolean(gf) };
  });
}

function computeRunEnergyMetrics(startIdx, endIdx, durationMin, chronoFiltered) {
  let thermalKwSum = 0;
  let elecKwSum = 0;
  let cnt = 0;
  if (chronoFiltered && chronoFiltered.length) {
    for (let k = startIdx; k <= endIdx && k < chronoFiltered.length; k++) {
      const pwr = estimateSamplePower(chronoFiltered[k].sample);
      if (pwr.pThermalKw > 0) {
        thermalKwSum += pwr.pThermalKw;
        elecKwSum += pwr.pElecKw;
        cnt++;
      }
    }
  }
  const avgThermalKw = cnt > 0 ? (thermalKwSum / cnt) : 0;
  const avgElecKw = cnt > 0 ? (elecKwSum / cnt) : 0;
  const durH = Math.max(1, durationMin) / 60.0;
  return {
    avgThermalKw,
    avgElecKw,
    thermalKwh: avgThermalKw * durH,
    elecKwh: avgElecKw * durH,
  };
}

function buildActivityRuns(states, chronoFiltered) {
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
      cur = { state, startTs: ts, endTs: ts, startIdx: i, endIdx: i, segStart: ts, segEnd: ts, durationMin: 0 };
    }
    prevTs = ts;
  }
  if (cur) runs.push(cur);

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

  for (let i = 0; i < runs.length; i++) {
    const r = runs[i];
    r.durationMin = Math.max(1, Math.round((r.segEnd - r.segStart) / 60000));
    if (r.state === 1 || r.state === 3) {
      const metrics = computeRunEnergyMetrics(r.startIdx, r.endIdx, r.durationMin, chronoFiltered);
      r.avgThermalKw = metrics.avgThermalKw;
      r.avgElecKw = metrics.avgElecKw;
      r.thermalKwh = metrics.thermalKwh;
      r.elecKwh = metrics.elecKwh;
    } else {
      r.avgThermalKw = 0;
      r.avgElecKw = 0;
      r.thermalKwh = 0;
      r.elecKwh = 0;
    }
  }

  return runs;
}

function buildCompressorOnRuns(states, chronoFiltered) {
  const runs = [];
  let cur = null;
  let prevTs = null;
  const maxGapMs = 25 * 60 * 1000;

  for (let i = 0; i < states.length; i++) {
    const s = states[i];
    if (!s.comp) {
      if (cur) {
        runs.push(cur);
        cur = null;
      }
    } else if (cur && prevTs !== null && (s.ts - prevTs) <= maxGapMs) {
      cur.endTs = s.ts;
      cur.endIdx = i;
    } else {
      if (cur) runs.push(cur);
      cur = { startTs: s.ts, endTs: s.ts, startIdx: i, endIdx: i };
    }
    prevTs = s.ts;
  }
  if (cur) runs.push(cur);

  for (let i = 0; i < runs.length; i++) {
    const r = runs[i];
    const startEdge = (r.startIdx > 0 && (r.startTs - states[r.startIdx - 1].ts) <= maxGapMs)
      ? (states[r.startIdx - 1].ts + r.startTs) / 2
      : r.startTs;
    const endEdge = (r.endIdx + 1 < states.length && (states[r.endIdx + 1].ts - r.endTs) <= maxGapMs)
      ? (r.endTs + states[r.endIdx + 1].ts) / 2
      : r.endTs;
    r.durationMin = Math.max(2, Math.round((endEdge - startEdge) / 60000));
    const metrics = computeRunEnergyMetrics(r.startIdx, r.endIdx, r.durationMin, chronoFiltered);
    r.avgThermalKw = metrics.avgThermalKw;
    r.avgElecKw = metrics.avgElecKw;
    r.thermalKwh = metrics.thermalKwh;
    r.elecKwh = metrics.elecKwh;
  }
  return runs;
}

/**
 * Detects events where the heat pump compressor shut off immediately after reaching
 * or exceeding its calculated Target LWT (saturation / inability to modulate lower).
 */
function detectSetpointCutoffEvents(chronoFiltered, states) {
  const events = [];
  if (!chronoFiltered || !chronoFiltered.length || !states || states.length !== chronoFiltered.length) {
    return events;
  }

  const maxGapMs = 25 * 60 * 1000;
  let runStart = null;

  for (let i = 0; i < states.length; i++) {
    if (states[i].comp) {
      if (runStart === null) runStart = i;
      continue;
    }
    if (runStart === null) continue;

    const endIdx = i - 1;
    const offIdx = i;
    if ((chronoFiltered[offIdx].ts - chronoFiltered[endIdx].ts) <= maxGapMs) {
      const endSample = chronoFiltered[endIdx].sample;
      const offSample = chronoFiltered[offIdx].sample;
      const progEnd = (endSample.active_program || "").toLowerCase();
      const progOff = (offSample.active_program || "").toLowerCase();
      const phaseEnd = String(endSample.compressor_phase || "").toLowerCase();

      if (progEnd !== "standby" && progOff !== "standby" && !phaseEnd.includes("defrost")) {
        const targetLwt = computeVitocalTargetLwt(endSample, false);
        if (targetLwt !== null) {
          const checkStart = Math.max(runStart, endIdx - 1);
          let peakSup = -Infinity;
          let peakBuf = -Infinity;
          for (let k = checkStart; k <= offIdx; k++) {
            const sk = chronoFiltered[k].sample;
            if (sk.pdc_supply_temp_c != null && !isNaN(Number(sk.pdc_supply_temp_c))) {
              peakSup = Math.max(peakSup, Number(sk.pdc_supply_temp_c));
            }
            if (sk.buffer_temp_c != null && !isNaN(Number(sk.buffer_temp_c))) {
              peakBuf = Math.max(peakBuf, Number(sk.buffer_temp_c));
            }
          }
          if (peakSup >= targetLwt - 0.5 || peakBuf >= targetLwt - 0.5) {
            const lastOnSup = endSample.pdc_supply_temp_c != null ? Number(endSample.pdc_supply_temp_c) : null;
            const yVal = (lastOnSup !== null && !isNaN(lastOnSup)) ? lastOnSup : (peakSup > -Infinity ? peakSup : targetLwt);
            const durMin = Math.max(2, Math.round((chronoFiltered[offIdx].ts - chronoFiltered[runStart].ts) / 60000));
            events.push({
              ts: chronoFiltered[endIdx].ts,
              offTs: chronoFiltered[offIdx].ts,
              yVal,
              peakSup: peakSup > -Infinity ? Math.round(peakSup * 10) / 10 : yVal,
              peakBuf: peakBuf > -Infinity ? Math.round(peakBuf * 10) / 10 : null,
              targetLwt,
              lastMod: endSample.compressor_modulation_percent != null ? Math.round(Number(endSample.compressor_modulation_percent)) : null,
              durationMin: durMin,
              gfOn: Boolean(states[endIdx].gf),
            });
          }
        }
      }
    }
    runStart = null;
  }

  return events;
}

function detectDefrostEvents(chronoFiltered) {
  const out = [];
  if (!chronoFiltered) return out;
  for (let i = 0; i < chronoFiltered.length; i++) {
    const phase = String(chronoFiltered[i].sample.compressor_phase || "").toLowerCase();
    if (phase.includes("defrost")) {
      out.push({ ts: chronoFiltered[i].ts, phase: chronoFiltered[i].sample.compressor_phase });
    }
  }
  return out;
}

window.detectSetpointCutoffEvents = detectSetpointCutoffEvents;
window.classifyActivityStates = classifyActivityStates;

function drawRoundedRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
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

    ctx.font = "700 10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";

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

      // Top 6px ribbon
      ctx.fillStyle = style.ribbon;
      ctx.fillRect(x1, area.top, w, 6);

      // Zoom-aware duration + thermal yield pill inside visible segment width (anti-overlap guarantee)
      const visLeft = Math.max(area.left + 2, x1);
      const visRight = Math.min(area.right - 2, x2);
      const visW = visRight - visLeft;
      const basePill = `${style.pillLabel} ${formatDurationCompact(r.durationMin)}`;
      let pillText = basePill;
      if ((r.state === 1 || r.state === 3) && r.thermalKwh > 0) {
        const fullPill = `${basePill} · ~${r.thermalKwh.toFixed(1)} kWhₜ (${r.avgThermalKw.toFixed(1)} kWₜ)`;
        const medPill = `${basePill} · ~${r.thermalKwh.toFixed(1)} kWhₜ`;
        if (visW >= ctx.measureText(fullPill).width + 20) {
          pillText = fullPill;
        } else if (visW >= ctx.measureText(medPill).width + 20) {
          pillText = medPill;
        }
      }
      const tw = ctx.measureText(pillText).width;
      const pillW = tw + 12;

      if (visW >= Math.max(46, pillW + 8)) {
        const cx = (visLeft + visRight) / 2;
        const px = cx - pillW / 2;
        const py = area.top + 8;
        const ph = 16;

        drawRoundedRect(ctx, px, py, pillW, ph, 5);
        ctx.fillStyle = "rgba(12, 19, 34, 0.88)";
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = style.pillBorder;
        ctx.stroke();

        ctx.fillStyle = "#f8fafc";
        ctx.fillText(pillText, cx, py + ph / 2 + 0.5);
      }
    }

    ctx.restore();
  },
};

const telemetryAnnotationsPlugin = {
  id: "telemetryAnnotations",
  afterDatasetsDraw(chart) {
    const area = chart.chartArea;
    const xScale = chart.scales && chart.scales.x;
    const yTempScale = chart.scales && chart.scales.yTemp;
    if (!area || !xScale || !yTempScale) return;

    const ctx = chart.ctx;
    const viewMin = xScale.min;
    const viewMax = xScale.max;

    ctx.save();
    ctx.beginPath();
    ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
    ctx.clip();

    // 1. Active vertical crosshair while scrubbing / reading
    if (typeof chart._activeHoverX === "number" && chart._activeHoverX >= area.left && chart._activeHoverX <= area.right) {
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(56, 189, 248, 0.55)";
      ctx.beginPath();
      ctx.moveTo(chart._activeHoverX, area.top);
      ctx.lineTo(chart._activeHoverX, area.bottom);
      ctx.stroke();
      ctx.restore();
    }

    // 2. Defrost event markers
    const defrosts = chart._defrostEvents || [];
    let lastDefrostX = -999;
    ctx.font = "700 10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    for (let i = 0; i < defrosts.length; i++) {
      const df = defrosts[i];
      if (df.ts < viewMin || df.ts > viewMax) continue;
      const px = xScale.getPixelForValue(df.ts);
      if (px - lastDefrostX < 48) continue;
      lastDefrostX = px;
      ctx.fillStyle = "rgba(56, 189, 248, 0.92)";
      ctx.fillText("❄️", px, area.top + 31);
    }

    // 3. Setpoint-saturation stop markers
    const cutoffs = showSetpointMarkers ? (chart._setpointCutoffs || []) : [];
    let lastLabelRightPx = -999;

    for (let i = 0; i < cutoffs.length; i++) {
      const ev = cutoffs[i];
      if (ev.ts < viewMin || ev.ts > viewMax) continue;

      const px = xScale.getPixelForValue(ev.ts);
      const rawPy = yTempScale.getPixelForValue(ev.yVal);
      const py = clamp(rawPy, area.top + 12, area.bottom - 12);

      // Vertical dashed drop line
      ctx.save();
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = "rgba(255, 69, 58, 0.72)";
      ctx.beginPath();
      ctx.moveTo(px, Math.max(area.top + 26, py - 20));
      ctx.lineTo(px, py);
      ctx.stroke();
      ctx.restore();

      // High-contrast downward pointer diamond centered at cutoff point
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(px, py + 6);
      ctx.lineTo(px - 6, py);
      ctx.lineTo(px, py - 6);
      ctx.lineTo(px + 6, py);
      ctx.closePath();
      ctx.fillStyle = "#ff453a";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fef08a";
      ctx.stroke();
      ctx.restore();

      // Zoom-aware badge above marker (suppressed when adjacent labels would collide)
      const labelTxt = `⊘ SP ${ev.peakSup.toFixed(1)}°`;
      const tw = ctx.measureText(labelTxt).width;
      const badgeW = tw + 10;
      const badgeH = 16;
      const badgeX = clamp(px - badgeW / 2, area.left + 2, area.right - badgeW - 2);
      const badgeY = Math.max(area.top + 27, py - 24);

      if (badgeX >= lastLabelRightPx + 6) {
        drawRoundedRect(ctx, badgeX, badgeY, badgeW, badgeH, 5);
        ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
        ctx.fill();
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = "#ff453a";
        ctx.stroke();

        ctx.fillStyle = "#fecaca";
        ctx.fillText(labelTxt, badgeX + badgeW / 2, badgeY + badgeH / 2 + 0.5);
        lastLabelRightPx = badgeX + badgeW;
      }
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
          telemetryChart._activeHoverX = null;
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

  const jumpBtn = document.getElementById("btnJumpLastCycle");
  if (jumpBtn && jumpBtn.dataset.bound !== "1") {
    jumpBtn.dataset.bound = "1";
    jumpBtn.addEventListener("click", jumpToLastCycle);
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

  document.querySelectorAll(".activity-legend-btn[data-band]").forEach(btn => {
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

  const spBtn = document.getElementById("btnToggleSetpointMarkers");
  if (spBtn && spBtn.dataset.bound !== "1") {
    spBtn.dataset.bound = "1";
    spBtn.addEventListener("click", () => {
      showSetpointMarkers = !showSetpointMarkers;
      spBtn.classList.toggle("active", showSetpointMarkers);
      if (telemetryChart) telemetryChart.update("none");
    });
  }

  const presetWrap = document.getElementById("chartPresetButtons");
  if (presetWrap && presetWrap.dataset.bound !== "1") {
    presetWrap.dataset.bound = "1";
    presetWrap.querySelectorAll(".btn-preset-chip").forEach(btn => {
      btn.addEventListener("click", () => {
        applyChartPreset(btn.dataset.preset);
      });
    });
  }

  initChannelSearchDrawer();
  bindYAxisModalEvents();
  updateModeButtonUI();
  updateAxisPillsUI();
  updatePresetButtonsUI();
}

function getAllPresetKeys() {
  return CHANNEL_DEFS.filter(ch => ch.inLegend || ch.defaultInLegend).map(ch => ch.key);
}

function applyChartPreset(presetKey) {
  const keys = presetKey === "all" ? getAllPresetKeys() : CHART_PRESETS[presetKey];
  if (!keys) return;
  soloBackupActive = null;
  activePresetKey = presetKey;
  const allowSet = new Set(keys);
  for (let i = 0; i < CHANNEL_DEFS.length; i++) {
    CHANNEL_DEFS[i].active = allowSet.has(CHANNEL_DEFS[i].key);
  }
  yAutoFrozen = { yTemp: null, yOther: null };
  updatePresetButtonsUI();
  renderChannelPills();
  renderChannelSearchResults();
  updateChartData(currentSamples);
}

function syncPresetFromActiveChannels() {
  const curKeys = CHANNEL_DEFS.filter(c => c.active).map(c => c.key).sort().join(",");
  let matched = null;
  for (const [k, list] of Object.entries(CHART_PRESETS)) {
    const targetList = k === "all" ? getAllPresetKeys() : list;
    if (targetList && [...targetList].sort().join(",") === curKeys) {
      matched = k;
      break;
    }
  }
  activePresetKey = matched;
  updatePresetButtonsUI();
}

function updatePresetButtonsUI() {
  const presetWrap = document.getElementById("chartPresetButtons");
  if (!presetWrap) return;
  presetWrap.querySelectorAll(".btn-preset-chip").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.preset === activePresetKey);
  });
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

function jumpToLastCycle() {
  const chronoAll = parseSamplesChrono(currentSamples);
  if (!chronoAll.length) return;
  const allStates = classifyActivityStates(chronoAll);
  const compRuns = buildCompressorOnRuns(allStates, chronoAll);
  if (!compRuns.length) {
    if (typeof showToast === "function") showToast("ℹ️ Nessun ciclo compressore trovato nei dati disponibili.");
    return;
  }

  const lastRun = compRuns[compRuns.length - 1];
  const reqMin = lastRun.startTs - 20 * 60 * 1000;
  const reqMax = lastRun.endTs + 45 * 60 * 1000;

  let fullBounds = getFullXBounds(chronoAll, activeTimeframeHours);
  if (fullBounds.min !== undefined && reqMin < fullBounds.min) {
    setChartTimeframe(0);
    fullBounds = getFullXBounds(chronoAll, 0);
  }
  if (!telemetryChart) buildChart();
  freezeAutoYIfNeeded();
  const minClamp = clamp(reqMin, fullBounds.min, fullBounds.max - MIN_X_SPAN_MS);
  const maxClamp = clamp(reqMax, minClamp + MIN_X_SPAN_MS, fullBounds.max);
  xZoomRange = { min: minClamp, max: maxClamp };
  telemetryChart.options.scales.x.min = xZoomRange.min;
  telemetryChart.options.scales.x.max = xZoomRange.max;
  applyYScaleOptions(telemetryChart);
  updateResetButtonUI();
  telemetryChart.update("none");
  updateVisibleWindowStats();
  if (typeof showToast === "function") {
    showToast(`⏭️ Centrato sull'ultimo ciclo (${formatDurationCompact(lastRun.durationMin)})`);
  }
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
  updateVisibleWindowStats();
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
      delete scaleOpt.grace;
    } else if (xZoomRange !== null && yAutoFrozen[axisId]) {
      scaleOpt.min = yAutoFrozen[axisId].min;
      scaleOpt.max = yAutoFrozen[axisId].max;
      delete scaleOpt.grace;
    } else {
      delete scaleOpt.min;
      delete scaleOpt.max;
      if (axisId === "yTemp") {
        scaleOpt.grace = "14%";
      } else {
        delete scaleOpt.grace;
      }
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
  telemetryChart._activityRuns = buildActivityRuns(states, chronoFiltered);
  telemetryChart._compRuns = buildCompressorOnRuns(states, chronoFiltered);
  telemetryChart._setpointCutoffs = detectSetpointCutoffEvents(chronoFiltered, states);
  telemetryChart._defrostEvents = detectDefrostEvents(chronoFiltered);
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
  updateLegendValues(chronoAll.length ? chronoAll[chronoAll.length - 1].sample : null);
  renderChannelSearchResults();
  updateVisibleWindowStats();
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
      backgroundColor: ch.backgroundColor || (ch.color + "22"),
      fill: ch.fill ? "origin" : false,
      stepped: ch.stepped ? "before" : false,
      borderWidth: ch.borderWidth || 2,
      pointRadius: points.length > 70 ? 0 : 2.5,
      pointHoverRadius: 6,
      tension: (ch.stepped || ch.spanGaps === false) ? 0 : 0.18,
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

function updateVisibleWindowStats() {
  const box = document.getElementById("chartWindowStats");
  if (!box) return;
  const chrono = (telemetryChart && telemetryChart._activityChrono) ? telemetryChart._activityChrono : parseSamplesChrono(currentSamples);
  if (!chrono || !chrono.length) {
    box.innerHTML = '<span class="chart-stat-item">Nessun dato nella finestra.</span>';
    return;
  }

  const xScale = telemetryChart && telemetryChart.scales ? telemetryChart.scales.x : null;
  const vMin = (xZoomRange && xZoomRange.min != null) ? xZoomRange.min : ((xScale && typeof xScale.min === "number") ? xScale.min : chrono[0].ts);
  const vMax = (xZoomRange && xZoomRange.max != null) ? xZoomRange.max : ((xScale && typeof xScale.max === "number") ? xScale.max : chrono[chrono.length - 1].ts);

  const visibleChrono = chrono.filter(it => it.ts >= vMin && it.ts <= vMax);
  const sub = visibleChrono.length ? visibleChrono : chrono;
  const subStates = classifyActivityStates(sub);
  const subCompRuns = buildCompressorOnRuns(subStates, sub);
  const subCutoffs = detectSetpointCutoffEvents(sub, subStates);

  let totalOnMin = 0;
  let totalThermalKwh = 0;
  let totalElecKwh = 0;
  for (const r of subCompRuns) {
    totalOnMin += r.durationMin;
    totalThermalKwh += r.thermalKwh || 0;
    totalElecKwh += r.elecKwh || 0;
  }
  const avgMin = subCompRuns.length ? Math.round(totalOnMin / subCompRuns.length) : 0;

  let tinMin = Infinity, tinMax = -Infinity;
  let oatMin = Infinity, oatMax = -Infinity;
  let copSum = 0, copCnt = 0;
  for (const { sample } of sub) {
    if (sample.indoor_temp_bticino_c != null) {
      const v = Number(sample.indoor_temp_bticino_c);
      tinMin = Math.min(tinMin, v);
      tinMax = Math.max(tinMax, v);
    }
    if (sample.external_temp_c != null) {
      const v = Number(sample.external_temp_c);
      oatMin = Math.min(oatMin, v);
      oatMax = Math.max(oatMax, v);
    }
    if (sample.cop_heating != null && Number(sample.cop_heating) > 0) {
      copSum += Number(sample.cop_heating);
      copCnt++;
    }
  }

  const parts = [];
  if (subCompRuns.length > 0) {
    parts.push(`<span class="chart-stat-item">🔥 PdC ON: <strong>${formatDurationCompact(totalOnMin)}</strong> (${subCompRuns.length} cicli · media ${avgMin}m)</span>`);
    if (totalThermalKwh > 0) {
      parts.push(`<span class="chart-stat-item" style="color:#fde047;">🔆 Resa: <strong>~${totalThermalKwh.toFixed(1)} kWhₜ</strong> (El ${totalElecKwh.toFixed(1)} kWhₑ)</span>`);
    }
  } else {
    parts.push('<span class="chart-stat-item">⏸ PdC ON: <strong>0m</strong></span>');
  }
  if (subCutoffs.length > 0) {
    parts.push(`<span class="chart-stat-item" style="color:#fca5a5;">🎯 Stop SP: <strong>${subCutoffs.length}</strong></span>`);
  }
  if (tinMin < Infinity) {
    parts.push(`<span class="chart-stat-item">🏠 Casa: <strong>${tinMin.toFixed(1)}–${tinMax.toFixed(1)}°</strong></span>`);
  }
  if (oatMin < Infinity) {
    parts.push(`<span class="chart-stat-item">❄️ OAT: <strong>${oatMin.toFixed(1)}–${oatMax.toFixed(1)}°</strong></span>`);
  }
  if (copCnt > 0) {
    parts.push(`<span class="chart-stat-item">⚡ COP: <strong>${(copSum / copCnt).toFixed(2)}</strong></span>`);
  }
  box.innerHTML = parts.join("");
}

function updateLegendValues(sample) {
  document.querySelectorAll(".legend-val[data-legend-key]").forEach(el => {
    const key = el.getAttribute("data-legend-key");
    const ch = CHANNEL_DEFS.find(c => c.key === key);
    if (!ch || !sample) {
      el.textContent = "--";
      return;
    }
    const raw = ch.computed ? ch.computed(sample) : sample[ch.key];
    if (raw === null || raw === undefined || raw === "" || isNaN(Number(raw))) {
      el.textContent = "--";
      return;
    }
    const num = Number(raw);
    const valStr = Number.isInteger(num) ? String(num) : num.toFixed(1);
    el.textContent = `${valStr}${ch.unit === "COP" ? "" : ch.unit}`;
  });
}

function buildChart() {
  const canvas = document.getElementById("telemetryChartCanvas");
  if (!canvas) return;

  const chronoAll = parseSamplesChrono(currentSamples);
  const bounds = getFullXBounds(chronoAll, activeTimeframeHours);
  const chronoFiltered = filterChronoByBounds(chronoAll, bounds);
  const states = classifyActivityStates(chronoFiltered);
  const runs = buildActivityRuns(states, chronoFiltered);
  const compRuns = buildCompressorOnRuns(states, chronoFiltered);
  const cutoffs = detectSetpointCutoffEvents(chronoFiltered, states);
  const defrosts = detectDefrostEvents(chronoFiltered);

  if (telemetryChart) {
    telemetryChart.destroy();
  }

  const ctx = canvas.getContext("2d");
  telemetryChart = new Chart(ctx, {
    type: "line",
    plugins: [activityBandsPlugin, telemetryAnnotationsPlugin],
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
          display: false,
        },
        tooltip: {
          enabled: chartInteractionMode === "read",
          backgroundColor: "rgba(15, 23, 42, 0.96)",
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
              if (items[0].element && typeof items[0].element.x === "number") {
                telemetryChart._activeHoverX = items[0].element.x;
              }
              const lines = [];
              const st = findClosestByTs(telemetryChart._activityStates, targetTs);
              let hitRun = null;
              if (st) {
                const info = ACTIVITY_STYLES[st.state];
                let bandDurTxt = "";
                const runsList = telemetryChart._activityRuns || [];
                hitRun = runsList.find(r => targetTs >= r.segStart && targetTs <= r.segEnd);
                if (hitRun) bandDurTxt = ` (${formatDurationCompact(hitRun.durationMin)})`;
                lines.push((info ? info.text : "⏸ Stato: Standby") + bandDurTxt);
                if (hitRun && (hitRun.state === 1 || hitRun.state === 3) && hitRun.thermalKwh > 0) {
                  lines.push(`🔥 Resa blocco: ~${hitRun.thermalKwh.toFixed(2)} kWhₜ · media ${hitRun.avgThermalKw.toFixed(1)} kWₜ`);
                }
              }
              const rawEntry = findClosestByTs(telemetryChart._activityChrono, targetTs);
              if (rawEntry && rawEntry.sample) {
                const s = rawEntry.sample;
                updateLegendValues(s);
                const tin = s.indoor_temp_bticino_c != null ? `${Number(s.indoor_temp_bticino_c).toFixed(1)}°C` : "--";
                const sp = s.indoor_setpoint_bticino_c != null ? `${Number(s.indoor_setpoint_bticino_c).toFixed(1)}°C` : "--";
                const gfTxt = s.grundfos_pump_active === 1 ? "GF ON" : (s.grundfos_pump_active === 0 ? "GF OFF" : "GF --");
                lines.push(`🏠 Casa: ${tin} / SP ${sp} → ${gfTxt}`);
                if (s.pdc_supply_temp_c != null && s.pdc_return_temp_c != null) {
                  const dtPrim = (Number(s.pdc_supply_temp_c) - Number(s.pdc_return_temp_c)).toFixed(1);
                  const p1Txt = s.primary_pump_rotation_percent != null ? ` · P1 ${Math.round(Number(s.primary_pump_rotation_percent))}%` : "";
                  lines.push(`🔁 ΔT Primario (LWT−EWT): ${Number(dtPrim) >= 0 ? "+" : ""}${dtPrim} K${p1Txt}`);
                }
                if (s.pdc_supply_temp_c != null && s.buffer_temp_c != null) {
                  const dtSupBuf = (Number(s.pdc_supply_temp_c) - Number(s.buffer_temp_c)).toFixed(1);
                  lines.push(`🌡️ ΔT Mandata−Puffer: ${Number(dtSupBuf) >= 0 ? "+" : ""}${dtSupBuf} K`);
                }
                if ((s.active_program || "").toLowerCase() === "standby") {
                  const potentialLwt = computeVitocalTargetLwt(s, true);
                  if (potentialLwt !== null) {
                    lines.push(`🎯 Curva PdC (in Standby): ${potentialLwt.toFixed(1)} °C`);
                  }
                }
                const nearbyCutoff = (telemetryChart._setpointCutoffs || []).find(ev => Math.abs(ev.ts - targetTs) <= 10 * 60 * 1000);
                if (nearbyCutoff) {
                  const modTxt = nearbyCutoff.lastMod != null ? `mod ${nearbyCutoff.lastMod}%` : "";
                  lines.push(`⊘ Stop Setpoint: Mandata ${nearbyCutoff.peakSup.toFixed(1)}°C ≥ Target ${nearbyCutoff.targetLwt.toFixed(1)}°C (${modTxt}, ciclo ${formatDurationCompact(nearbyCutoff.durationMin)})`);
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
          grace: "14%",
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
  telemetryChart._compRuns = compRuns;
  telemetryChart._setpointCutoffs = cutoffs;
  telemetryChart._defrostEvents = defrosts;
  telemetryChart._activeHoverX = null;

  applyYScaleOptions(telemetryChart);
  telemetryChart.update("none");
  updateLegendValues(chronoAll.length ? chronoAll[chronoAll.length - 1].sample : null);
  updateVisibleWindowStats();

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
    updateVisibleWindowStats();
  }

  function setTooltipTempEnabled(enabled) {
    if (!telemetryChart) return;
    telemetryChart.options.plugins.tooltip.enabled = enabled && (chartInteractionMode === "read");
    if (!enabled) {
      telemetryChart._activeHoverX = null;
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

  canvas.addEventListener("mouseleave", () => {
    if (telemetryChart) {
      telemetryChart._activeHoverX = null;
      telemetryChart.update("none");
    }
    const chronoAll = parseSamplesChrono(currentSamples);
    updateLegendValues(chronoAll.length ? chronoAll[chronoAll.length - 1].sample : null);
  });

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

function toggleSoloChannel(idx, prevSnapshot = null) {
  const targetKey = CHANNEL_DEFS[idx].key;
  const activeCount = CHANNEL_DEFS.filter(c => c.active).length;
  if (activeCount === 1 && CHANNEL_DEFS[idx].active && soloBackupActive) {
    for (let i = 0; i < CHANNEL_DEFS.length; i++) {
      CHANNEL_DEFS[i].active = Boolean(soloBackupActive[i]);
    }
    soloBackupActive = null;
  } else {
    soloBackupActive = prevSnapshot || CHANNEL_DEFS.map(c => c.active);
    for (let i = 0; i < CHANNEL_DEFS.length; i++) {
      CHANNEL_DEFS[i].active = (CHANNEL_DEFS[i].key === targetKey);
    }
  }
  yAutoFrozen = { yTemp: null, yOther: null };
  syncPresetFromActiveChannels();
  renderChannelPills();
  updateChartData(currentSamples);
}

function renderChannelPills() {
  const container = document.getElementById("channelPillsContainer");
  if (!container) return;

  const groups = [
    { id: "temp", title: "🌡️ Temperature (°C / K)", hint: "Tap: on/off · 2×Tap: isola" },
    { id: "system", title: "⚙️ Inverter, Circolatori, Pressioni & COP", hint: "" },
  ];

  container.innerHTML = groups.map(grp => {
    const items = CHANNEL_DEFS
      .map((ch, idx) => ({ ch, idx }))
      .filter(({ ch }) => ch.group === grp.id && ch.inLegend);

    const chipsHtml = items.map(({ ch, idx }) => {
      const styleClass = ch.borderDash ? (ch.borderDash[0] <= 3 ? "dotted" : "dashed") : "";
      const removeBadge = !ch.defaultInLegend
        ? `<span class="legend-chip-remove" data-remove-idx="${idx}" title="Rimuovi dalla legenda">×</span>`
        : "";
      return `
        <button type="button" class="legend-chip ${ch.active ? "active" : ""}" data-idx="${idx}" style="--chip-color: ${ch.color}">
          <span class="legend-chip-left">
            <span class="legend-line-swatch ${styleClass}"></span>
            <span class="legend-chip-label">${ch.label}</span>
          </span>
          <span class="legend-chip-right">
            <span class="legend-val" data-legend-key="${ch.key}">--</span>
            ${removeBadge}
          </span>
        </button>
      `;
    }).join("");

    return `
      <div class="legend-group">
        <div class="legend-group-header">
          <span>${grp.title}</span>
          ${grp.hint ? `<span class="legend-hint-mini">${grp.hint}</span>` : ""}
        </div>
        <div class="legend-chips-grid">${chipsHtml}</div>
      </div>
    `;
  }).join("");

  container.querySelectorAll(".legend-chip-remove").forEach(rm => {
    rm.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const idx = parseInt(rm.dataset.removeIdx, 10);
      if (isNaN(idx) || !CHANNEL_DEFS[idx]) return;
      CHANNEL_DEFS[idx].inLegend = false;
      CHANNEL_DEFS[idx].active = false;
      saveExtraChannelsSet();
      yAutoFrozen = { yTemp: null, yOther: null };
      syncPresetFromActiveChannels();
      renderChannelPills();
      renderChannelSearchResults();
      updateExtraChannelsBadge();
      updateChartData(currentSamples);
    });
  });

  let lastChipTap = { idx: -1, at: 0, snapshot: null };
  container.querySelectorAll(".legend-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const now = Date.now();
      if (lastChipTap.idx === idx && (now - lastChipTap.at) < 340) {
        const snap = lastChipTap.snapshot;
        lastChipTap = { idx: -1, at: 0, snapshot: null };
        toggleSoloChannel(idx, snap);
        return;
      }
      lastChipTap = { idx, at: now, snapshot: CHANNEL_DEFS.map(c => c.active) };

      soloBackupActive = null;
      CHANNEL_DEFS[idx].active = !CHANNEL_DEFS[idx].active;
      btn.classList.toggle("active", CHANNEL_DEFS[idx].active);
      yAutoFrozen = { yTemp: null, yOther: null };
      syncPresetFromActiveChannels();
      renderChannelSearchResults();
      updateChartData(currentSamples);
    });
  });

  const chronoAll = parseSamplesChrono(currentSamples);
  if (chronoAll.length) {
    updateLegendValues(chronoAll[chronoAll.length - 1].sample);
  }
  updateExtraChannelsBadge();
}

function updateExtraChannelsBadge() {
  const btn = document.getElementById("btnToggleChannelSearch");
  if (!btn) return;
  const extraCount = CHANNEL_DEFS.filter(c => !c.defaultInLegend && c.inLegend).length;
  btn.textContent = extraCount > 0 ? `🔍 + Canali (${extraCount})` : "🔍 + Canali";
  btn.classList.toggle("has-extras", extraCount > 0);
}

function initChannelSearchDrawer() {
  const toggleBtn = document.getElementById("btnToggleChannelSearch");
  const drawer = document.getElementById("channelSearchDrawer");
  const input = document.getElementById("inputChannelSearch");
  const clearBtn = document.getElementById("btnClearChannelSearch");

  if (toggleBtn && toggleBtn.dataset.bound !== "1") {
    toggleBtn.dataset.bound = "1";
    toggleBtn.addEventListener("click", () => {
      if (!drawer) return;
      const open = drawer.classList.toggle("open");
      toggleBtn.classList.toggle("active", open);
      if (open) {
        renderChannelSearchResults();
        if (input) setTimeout(() => input.focus(), 40);
      }
    });
  }

  if (input && input.dataset.bound !== "1") {
    input.dataset.bound = "1";
    input.addEventListener("input", renderChannelSearchResults);
  }

  if (clearBtn && clearBtn.dataset.bound !== "1") {
    clearBtn.dataset.bound = "1";
    clearBtn.addEventListener("click", () => {
      if (input) {
        input.value = "";
        input.focus();
      }
      renderChannelSearchResults();
    });
  }

  renderChannelSearchResults();
  updateExtraChannelsBadge();
}

function renderChannelSearchResults() {
  const listEl = document.getElementById("channelSearchResults");
  if (!listEl) return;
  const input = document.getElementById("inputChannelSearch");
  const q = (input ? input.value : "").trim().toLowerCase();

  const chronoAll = parseSamplesChrono(currentSamples);
  const latestSample = chronoAll.length ? chronoAll[chronoAll.length - 1].sample : null;

  const matches = CHANNEL_DEFS.map((ch, idx) => ({ ch, idx })).filter(({ ch }) => {
    if (!q) return !ch.defaultInLegend || ch.active;
    const hay = `${ch.label} ${ch.key} ${ch.unit || ""} ${ch.yAxis} ${ch.keywords || ""}`.toLowerCase();
    return q.split(/\s+/).every(tok => hay.includes(tok));
  });

  if (!matches.length) {
    listEl.innerHTML = '<div class="channel-search-empty">Nessun canale trovato per la ricerca.</div>';
    return;
  }

  listEl.innerHTML = matches.map(({ ch, idx }) => {
    let valText = "--";
    if (latestSample) {
      const raw = ch.computed ? ch.computed(latestSample) : latestSample[ch.key];
      if (raw !== null && raw !== undefined && raw !== "" && !isNaN(Number(raw))) {
        const num = Number(raw);
        valText = `${Number.isInteger(num) ? num : num.toFixed(1)}${ch.unit ? " " + ch.unit : ""}`;
      }
    }
    const axisTag = ch.yAxis === "yTemp" ? "Asse °C/K" : "Asse %/kW";
    const btnLabel = ch.inLegend ? (ch.active ? "✓ Attivo" : "+ Mostra") : "+ Aggiungi";
    return `
      <div class="channel-search-item ${ch.active ? "is-active" : ""}">
        <div class="channel-search-info">
          <span class="channel-search-dot" style="background:${ch.color};"></span>
          <div class="channel-search-text">
            <span class="channel-search-name">${ch.label}</span>
            <span class="channel-search-meta">${axisTag} · live: <strong>${valText}</strong></span>
          </div>
        </div>
        <button type="button" class="btn-channel-toggle ${ch.active ? "active" : ""}" data-search-idx="${idx}">${btnLabel}</button>
      </div>
    `;
  }).join("");

  listEl.querySelectorAll(".btn-channel-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.searchIdx, 10);
      const ch = CHANNEL_DEFS[idx];
      if (!ch) return;
      soloBackupActive = null;
      if (!ch.inLegend) {
        ch.inLegend = true;
        ch.active = true;
      } else {
        ch.active = !ch.active;
      }
      saveExtraChannelsSet();
      yAutoFrozen = { yTemp: null, yOther: null };
      syncPresetFromActiveChannels();
      renderChannelPills();
      renderChannelSearchResults();
      updateChartData(currentSamples);
    });
  });
}
