/**
 * Responsive Industrial SCADA Synoptic Canvas (SVG) for Vitocal 111-S & BTicino Smarther.
 * Automatically adapts geometry between Portrait (vertical mobile stack) and
 * Landscape (widescreen schematic) based on viewport dimensions & orientation.
 */

let lastSynopticData = null;
let lastSynopticMode = null;
let resizeTimerSynoptic = null;

function detectSynopticMode() {
  const w = window.innerWidth || document.documentElement.clientWidth || 400;
  const h = window.innerHeight || document.documentElement.clientHeight || 700;
  return (w < 720 && h >= w) ? "portrait" : "landscape";
}

function bindSynopticResizeOnce() {
  if (window._synopticResizeBound) return;
  window._synopticResizeBound = true;

  const handleResize = () => {
    clearTimeout(resizeTimerSynoptic);
    resizeTimerSynoptic = setTimeout(() => {
      const nextMode = detectSynopticMode();
      if (nextMode !== lastSynopticMode) {
        renderSynoptic(lastSynopticData);
      }
    }, 120);
  };

  window.addEventListener("resize", handleResize);
  window.addEventListener("orientationchange", handleResize);
}

function renderSynoptic(data) {
  bindSynopticResizeOnce();
  lastSynopticData = data || lastSynopticData || {};
  const svg = document.getElementById("synopticSvg");
  if (!svg) return;

  const mode = detectSynopticMode();
  lastSynopticMode = mode;

  const m = extractSynopticMetrics(lastSynopticData);

  // Update toolbar indicators & SVG viewport classes
  const titleEl = document.getElementById("synopticToolbarTitle");
  const badgeEl = document.getElementById("synopticOrientationBadge");
  if (mode === "portrait") {
    svg.setAttribute("viewBox", "0 0 420 914");
    svg.classList.add("mode-portrait");
    svg.classList.remove("mode-landscape");
    if (titleEl) titleEl.textContent = "SINOTTICO VERTICALE IMPIANTO";
    if (badgeEl) badgeEl.textContent = "📱 VERTICALE";
  } else {
    svg.setAttribute("viewBox", "0 0 1260 560");
    svg.classList.add("mode-landscape");
    svg.classList.remove("mode-portrait");
    if (titleEl) titleEl.textContent = "SINOTTICO ORIZZONTALE SCADA";
    if (badgeEl) badgeEl.textContent = "🖥️ ORIZZONTALE";
  }

  const sharedDefs = buildSharedSvgDefs(m);
  const body = (mode === "portrait")
    ? renderSynopticPortrait(m)
    : renderSynopticLandscape(m);

  svg.innerHTML = sharedDefs + body;
  renderWo1cCutoffMargin(lastSynopticData);
}

function extractSynopticMetrics(d) {
  const fmt = (v, unit = "°C", decimals = 1, def = "--") => {
    if (v === null || v === undefined || isNaN(Number(v))) return `${def}${unit ? " " + unit : ""}`;
    return `${Number(v).toFixed(decimals)}${unit ? " " + unit : ""}`;
  };

  const oatNum = d.external_temp_c != null ? Number(d.external_temp_c) : null;
  const bufNum = d.buffer_temp_c != null ? Number(d.buffer_temp_c) : null;
  const supNum = d.pdc_supply_temp_c != null ? Number(d.pdc_supply_temp_c) : null;
  const retNum = d.pdc_return_temp_c != null ? Number(d.pdc_return_temp_c) : null;
  const inNum = d.indoor_temp_bticino_c != null ? Number(d.indoor_temp_bticino_c) : null;
  const spNum = d.indoor_setpoint_bticino_c != null ? Number(d.indoor_setpoint_bticino_c) : null;

  const compActive = (d.compressor_active === 1) || ((Number(d.compressor_modulation_percent) || 0) > 0);
  const compModNum = d.compressor_modulation_percent != null ? Number(d.compressor_modulation_percent) : 0;
  const primRotNum = d.primary_pump_rotation_percent != null ? Number(d.primary_pump_rotation_percent) : 0;
  const primPumpActive = primRotNum > 0 || compActive;
  const pumpActive = d.grundfos_pump_active === 1;

  const deltaPrim = (supNum != null && retNum != null) ? (supNum - retNum) : null;
  const deltaAir = (inNum != null && oatNum != null) ? (inNum - oatNum) : null;

  // Real target water (Puffer/LWT WO1C) and real room target (Autopilot band vs manual)
  const apCfg = (typeof cmdState !== "undefined" && cmdState.lastAutopilotConfig) ? cmdState.lastAutopilotConfig : null;
  const apSt = (typeof cmdState !== "undefined" && cmdState.lastAutopilotState) ? cmdState.lastAutopilotState : null;
  const apEnabled = Boolean(apCfg && apCfg.enabled);
  const apStateCode = apEnabled ? String((apSt && apSt.state) || "IDLE") : "MANUAL";

  const progLower = (d.active_program || "standby").toLowerCase();
  const liveWaterTarget = (typeof computeVitocalTargetLwt === "function") ? computeVitocalTargetLwt(d, false) : null;
  const autoWaterTarget = (apSt && apSt.calculated_target_lwt_c != null) ? Number(apSt.calculated_target_lwt_c) : null;
  const curveStandbyWater = (typeof computeVitocalTargetLwt === "function") ? computeVitocalTargetLwt(d, true) : null;

  let targetWaterVal = "--";
  let targetWaterSub = "Curva PdC";
  if (liveWaterTarget != null && progLower !== "standby") {
    targetWaterVal = `${liveWaterTarget.toFixed(1)} °C`;
    targetWaterSub = "Target Attivo (Puffer)";
  } else if (apEnabled && autoWaterTarget != null) {
    targetWaterVal = `~${autoWaterTarget.toFixed(1)} °C`;
    targetWaterSub = "Auto (al prox. avvio)";
  } else if (curveStandbyWater != null) {
    targetWaterVal = `~${curveStandbyWater.toFixed(1)} °C`;
    targetWaterSub = "Curva (in Standby)";
  }

  let targetRoomReal = fmt(spNum, "°C");
  let targetRoomSub = "Manuale BTicino";
  let deltaTarget = (inNum != null && spNum != null) ? (inNum - spNum) : null;
  if (apEnabled && apCfg) {
    const tMin = Number(apCfg.t_min_c != null ? apCfg.t_min_c : 7.5);
    const tMax = Number(apCfg.t_max_c != null ? apCfg.t_max_c : 8.8);
    if (apStateCode === "HEATING_SYNC") {
      targetRoomReal = `→ ${tMax.toFixed(1)} °C`;
      targetRoomSub = `Full-Auto (Avvio ${tMin.toFixed(1)}°)`;
      deltaTarget = inNum != null ? (inNum - tMax) : null;
    } else {
      targetRoomReal = `${tMin.toFixed(1)}–${tMax.toFixed(1)} °C`;
      targetRoomSub = `Full-Auto (${apStateCode})`;
      deltaTarget = inNum != null ? (inNum - tMin) : null;
    }
  }

  const rod1s = d.heating_rod_level1_s != null ? Number(d.heating_rod_level1_s) : null;
  const rod2s = d.heating_rod_level2_s != null ? Number(d.heating_rod_level2_s) : null;
  const rod1h = rod1s != null ? (rod1s / 3600.0).toFixed(1) : "--";
  const rod2h = rod2s != null ? (rod2s / 3600.0).toFixed(1) : "--";
  const rodHoursStr = (rod1s != null || rod2s != null) ? `${rod1h}h / ${rod2h}h` : "--";
  let rodActive = false;
  const samplesList = (typeof state !== "undefined" && Array.isArray(state.samples)) ? state.samples : [];
  if (samplesList.length >= 2) {
    const prev = samplesList[samplesList.length - 2];
    if (prev) {
      if (rod1s != null && prev.heating_rod_level1_s != null && rod1s > Number(prev.heating_rod_level1_s)) rodActive = true;
      if (rod2s != null && prev.heating_rod_level2_s != null && rod2s > Number(prev.heating_rod_level2_s)) rodActive = true;
    }
  }
  const rodTodayMin = computeRodTodayMinutes(samplesList);
  const rodStatusCompact = rodActive
    ? "⚡ ON"
    : (rodTodayMin > 0 ? `OGGI ${rodTodayMin}m` : "OFF · 0m");

  let pufferTopColor = "#1e3a5f";
  if (bufNum != null) {
    if (bufNum >= 22) pufferTopColor = "#b45309";
    else if (bufNum >= 16) pufferTopColor = "#78350f";
    else if (bufNum >= 12) pufferTopColor = "#1e3a5f";
    else pufferTopColor = "#0f2942";
  }

  return {
    oat: fmt(oatNum, "°C"),
    dhw: fmt(d.dhw_storage_temp_c, "°C"),
    supply: fmt(supNum, "°C"),
    ret: fmt(retNum, "°C"),
    buffer: fmt(bufNum, "°C"),
    indoor: fmt(inNum, "°C"),
    setpoint: fmt(spNum, "°C"),
    targetWaterVal,
    targetWaterSub,
    targetRoomReal,
    targetRoomSub,
    apStateBadge: apEnabled ? `AUTO (${apStateCode})` : "MANUALE",
    humidity: fmt(d.humidity_percent, "%", 0),
    compActive,
    compMod: `${compModNum.toFixed(0)} %`,
    compColor: compActive ? "#10b981" : "#64748b",
    compStatusShort: compActive ? `ON (${compModNum.toFixed(0)}%)` : "SPENTO",
    primPumpActive,
    primPumpText: d.primary_pump_rotation_percent != null ? `${primRotNum.toFixed(0)} %` : (compActive ? "ON" : "0 %"),
    primSpinDur: primRotNum >= 70 ? "0.9s" : (primRotNum >= 30 ? "1.3s" : "1.8s"),
    pumpActive,
    pumpColor: pumpActive ? "#10b981" : "#1e293b",
    pumpBorder: pumpActive ? "#ffffff" : "#64748b",
    pumpStatusShort: pumpActive ? "ACCESA" : "SPENTA",
    gasPress: fmt(d.hot_gas_pressure_bar, "bar"),
    hotGas: fmt(d.hot_gas_temp_c, "°C"),
    liqGas: fmt(d.liquid_gas_temp_c, "°C"),
    sucGas: fmt(d.suction_gas_temp_c, "°C"),
    copH: compActive && d.cop_heating != null ? Number(d.cop_heating).toFixed(1) : (d.cop_heating != null ? Number(d.cop_heating).toFixed(1) : "--"),
    copTot: d.cop_total != null ? Number(d.cop_total).toFixed(1) : "--",
    compHours: fmt(d.compressor_hours, "h", 0),
    compStarts: d.compressor_starts != null ? `${d.compressor_starts}` : "--",
    slope: d.heating_curve_slope != null ? Number(d.heating_curve_slope).toFixed(1) : "0.6",
    shift: d.heating_curve_shift != null ? Number(d.heating_curve_shift).toFixed(0) : "0",
    prog: (d.active_program || "standby").toUpperCase(),
    mode: d.active_mode || "dhwAndHeating",
    thermostatMode: (d.active_preset === "cloud_github_actions" ? "PROGRAMMA" : (d.active_preset || "AUTO")).toUpperCase(),
    deltaPrimStr: deltaPrim != null ? `${deltaPrim >= 0 ? "+" : ""}${deltaPrim.toFixed(1)} °C` : "--",
    deltaAirStr: deltaAir != null ? `${deltaAir >= 0 ? "+" : ""}${deltaAir.toFixed(1)} °C` : "--",
    deltaTargetStr: deltaTarget != null ? `${deltaTarget >= 0 ? "+" : ""}${deltaTarget.toFixed(1)} °C` : "--",
    rodActive,
    rodTodayMin,
    rodHoursStr,
    rodStatusCompact,
    rodStatusShort: rodActive ? `⚡ ON (${rodHoursStr})` : `OFF (${rodHoursStr})`,
    rodColor: rodActive ? "#fb7185" : (rodTodayMin > 0 ? "#fbbf24" : "#94a3b8"),
    rodBorder: rodActive ? "#ef4444" : (rodTodayMin > 0 ? "#f59e0b" : "#334155"),
    pufferTopColor,
    wo1cGauge: computeWo1cCutoffMargin(d, samplesList),
  };
}

function computeRodTodayMinutes(samples) {
  if (!Array.isArray(samples) || !samples.length) return 0;
  const todayKey = new Date().toDateString();
  const vals = [];
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    if (!s || !s.timestamp_utc) continue;
    if (s.heating_rod_level1_s == null && s.heating_rod_level2_s == null) continue;
    const d = new Date(s.timestamp_utc);
    if (!isNaN(d.getTime()) && d.toDateString() === todayKey) {
      vals.push(Number(s.heating_rod_level1_s || 0) + Number(s.heating_rod_level2_s || 0));
    }
  }
  if (vals.length < 2) return 0;
  const deltaS = Math.max(0, vals[vals.length - 1] - vals[0]);
  return Math.round(deltaS / 60);
}
window.computeRodTodayMinutes = computeRodTodayMinutes;

function buildSharedSvgDefs(m) {
  return `
    <defs>
      <linearGradient id="pufferGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${m.pufferTopColor}" />
        <stop offset="55%" stop-color="#162136" />
        <stop offset="100%" stop-color="#0f172a" />
      </linearGradient>

      <linearGradient id="skyGrad" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#0c1e36" />
        <stop offset="50%" stop-color="#102542" />
        <stop offset="100%" stop-color="#0c1e36" />
      </linearGradient>

      <style>
        .flow-prim-hot {
          stroke: ${m.primPumpActive ? "#ef4444" : "#7f1d1d"};
          stroke-width: 5.5;
          stroke-linecap: round;
          fill: none;
          ${m.primPumpActive ? "stroke-dasharray: 10, 9; animation: flowFwd 0.9s linear infinite;" : ""}
        }
        .flow-prim-cold {
          stroke: ${m.primPumpActive ? "#38bdf8" : "#1e3a5f"};
          stroke-width: 5.5;
          stroke-linecap: round;
          fill: none;
          ${m.primPumpActive ? "stroke-dasharray: 10, 9; animation: flowFwd 0.9s linear infinite;" : ""}
        }
        .flow-sec-hot {
          stroke: ${m.pumpActive ? "#ef4444" : "#642b2b"};
          stroke-width: 5.5;
          stroke-linecap: round;
          fill: none;
          ${m.pumpActive ? "stroke-dasharray: 10, 9; animation: flowFwd 0.9s linear infinite;" : ""}
        }
        .flow-sec-cold {
          stroke: ${m.pumpActive ? "#3b82f6" : "#1e3a5f"};
          stroke-width: 5.5;
          stroke-linecap: round;
          fill: none;
          ${m.pumpActive ? "stroke-dasharray: 10, 9; animation: flowFwd 0.9s linear infinite;" : ""}
        }
        @keyframes flowFwd {
          from { stroke-dashoffset: 19; }
          to { stroke-dashoffset: 0; }
        }
        .spin-prim {
          transform-origin: 0px 0px;
          ${m.primPumpActive ? `animation: spinImpeller ${m.primSpinDur} linear infinite;` : ""}
        }
        .spin-gf {
          transform-origin: 0px 0px;
          ${m.pumpActive ? "animation: spinImpeller 1.0s linear infinite;" : ""}
        }
        .spin-fan {
          transform-origin: 0px 0px;
          ${m.compActive ? "animation: spinImpeller 1.4s linear infinite;" : ""}
        }
        @keyframes spinImpeller {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      </style>
    </defs>
  `;
}

// =========================================================================
// PORTRAIT LAYOUT (420 x 914) — Zero Horizontal Scroll on Smartphones
// =========================================================================
function renderSynopticPortrait(m) {
  return `
    <rect x="0" y="0" width="420" height="914" fill="#0c1322" rx="10" />

    <!-- 1. ARIA ESTERNA (Outdoor Atmosphere Strip) -->
    <rect x="12" y="8" width="396" height="64" rx="10" fill="url(#skyGrad)" stroke="#38bdf8" stroke-width="1.4" stroke-dasharray="5,4" />
    ${svgCloudThermometerIcon(42, 40)}
    <text x="72" y="29" fill="#94a3b8" font-size="9" font-weight="700" letter-spacing="0.4">ARIA ESTERNA (Sonda PdC)</text>
    <text x="72" y="55" fill="#38bdf8" font-size="20" font-weight="800">${m.oat}</text>
    <g transform="translate(256, 16)">
      <rect x="0" y="0" width="140" height="48" rx="8" fill="#0c1526" stroke="#334155" stroke-width="1" />
      <text x="70" y="17" fill="#94a3b8" font-size="8.2" font-weight="700" text-anchor="middle">SALTO CASA vs FUORI</text>
      <text x="70" y="38" fill="#e2e8f0" font-size="14" font-weight="700" text-anchor="middle">${m.deltaAirStr}</text>
    </g>

    <!-- Dashed sensor link down to Heat Pump -->
    <line x1="64" y1="72" x2="64" y2="86" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="3,2" />

    <!-- 2. POMPA DI CALORE VITOCAL 111-S -->
    <rect x="12" y="86" width="396" height="198" rx="12" fill="#161f30" stroke="#38bdf8" stroke-width="2" />
    <text x="26" y="106" fill="#38bdf8" font-size="11" font-weight="700" letter-spacing="0.4">⚡ PDC VITOCAL 111-S (Inverter R410A)</text>

    <!-- Evaporator Fan + Compressor Status (Left) -->
    <rect x="24" y="114" width="84" height="96" rx="8" fill="#0f172a" stroke="${m.compColor}" stroke-width="1.3" />
    ${svgEvaporatorFan(66, 148, 22, m.compActive)}
    <text x="66" y="185" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">COMPRESSORE</text>
    <text x="66" y="201" fill="${m.compColor}" font-size="10.5" font-weight="800" text-anchor="middle">${m.compStatusShort}</text>

    <!-- Refrigerant & COP Badges (Center 2x2 grid) -->
    ${svgBadge(116, 114, 88, 45, "P Gas Caldo", m.gasPress, "#ec4899")}
    ${svgBadge(210, 114, 88, 45, "T Gas Caldo", m.hotGas, "#f87171")}
    ${svgBadge(116, 165, 88, 45, "COP Risc / Tot", `${m.copH} | ${m.copTot}`, "#10b981")}
    ${svgBadge(210, 165, 88, 45, "Curva Clim.", `${m.slope} / ${m.shift}`, "#60a5fa")}

    <!-- Mini Bollitore ACS 220L (Right) -->
    ${svgMiniBoiler(306, 114, 90, 96, m.dhw)}

    <!-- Bottom Strip inside PdC -->
    ${svgBadge(24, 218, 120, 54, "Gas Liq / Aspir.", `${m.liqGas} / ${m.sucGas}`, "#93c5fd")}
    ${svgBadge(150, 218, 120, 54, "Ore / Avvii", `${m.compHours} / ${m.compStarts}`, "#e2e8f0")}
    ${svgBadge(276, 218, 120, 54, "Programma Attivo", m.prog, "#a78bfa")}

    <!-- 3. CIRCUITO PRIMARIO VERTICALE (PdC <-> Puffer + Circolatore P1) -->
    <!-- Supply Pipe (down) -->
    <line x1="125" y1="284" x2="125" y2="404" class="flow-prim-hot" />
    ${svgArrow(125, 302, 0, 1, m.primPumpActive ? "#ef4444" : "#991b1b")}
    ${svgArrow(125, 386, 0, 1, m.primPumpActive ? "#ef4444" : "#991b1b")}

    <!-- Return Pipe (up) -->
    <line x1="295" y1="404" x2="295" y2="284" class="flow-prim-cold" />
    ${svgArrow(295, 386, 0, -1, m.primPumpActive ? "#38bdf8" : "#1e40af")}
    ${svgArrow(295, 302, 0, -1, m.primPumpActive ? "#38bdf8" : "#1e40af")}

    <!-- Primary Circulator P1 on Supply Pipe -->
    ${svgCirculator(125, 344, 19, m.primPumpActive, "spin-prim", m.primPumpActive ? "#10b981" : "#1e293b")}

    <!-- Pipe Tags (Zero Overlap) -->
    <g transform="translate(12, 298)">
      <rect x="0" y="0" width="96" height="36" rx="6" fill="#161f30" stroke="#ef4444" stroke-width="1.3" />
      <text x="48" y="13" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">T MANDATA PDC</text>
      <text x="48" y="29" fill="#ef4444" font-size="12" font-weight="800" text-anchor="middle">${m.supply}</text>
    </g>
    <g transform="translate(12, 344)">
      <rect x="0" y="0" width="96" height="36" rx="6" fill="#0f172a" stroke="${m.primPumpActive ? '#34d399' : '#475569'}" stroke-width="1.2" />
      <text x="48" y="13" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">CIRCOLATORE P1</text>
      <text x="48" y="29" fill="${m.primPumpActive ? '#34d399' : '#94a3b8'}" font-size="11.5" font-weight="800" text-anchor="middle">${m.primPumpText}</text>
    </g>

    <g transform="translate(174, 304)">
      <rect x="0" y="0" width="72" height="34" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="36" y="12" fill="#94a3b8" font-size="7.2" font-weight="700" text-anchor="middle">ΔT PRIM.</text>
      <text x="36" y="27" fill="#f8fafc" font-size="10.8" font-weight="700" text-anchor="middle">${m.deltaPrimStr}</text>
    </g>

    ${svgBackupHeaterBlock(174, 344, 72, 28, m)}

    <g transform="translate(312, 326)">
      <rect x="0" y="0" width="96" height="36" rx="6" fill="#161f30" stroke="#3b82f6" stroke-width="1.3" />
      <text x="48" y="13" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">T RITORNO PDC</text>
      <text x="48" y="29" fill="#38bdf8" font-size="12" font-weight="800" text-anchor="middle">${m.ret}</text>
    </g>

    <!-- 4. PUFFER INERZIALE 200 L (+ SCADA Anti-Stacco 7209 Gauge) -->
    <rect x="36" y="404" width="348" height="168" rx="26" fill="url(#pufferGrad)" stroke="#f59e0b" stroke-width="2.4" />
    <text x="210" y="423" fill="#f59e0b" font-size="11.2" font-weight="800" text-anchor="middle">PUFFER INERZIALE 200 L (Sensore Regolaz. WO1C)</text>
    <rect x="52" y="431" width="150" height="58" rx="8" fill="#0f172a" stroke="#f59e0b" stroke-width="1.3" />
    <text x="127" y="446" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">🌡️ PUFFER REALE</text>
    <text x="127" y="471" fill="#fbbf24" font-size="15.5" font-weight="800" text-anchor="middle">${m.buffer}</text>
    <text x="127" y="484" fill="#64748b" font-size="6.6" text-anchor="middle">Accumulo superiore</text>
    <rect x="218" y="431" width="150" height="58" rx="8" fill="#0f172a" stroke="#e879f9" stroke-width="1.3" />
    <text x="293" y="446" fill="#e879f9" font-size="7.5" font-weight="700" text-anchor="middle">🎯 TARGET ACQUA</text>
    <text x="293" y="471" fill="#f0abfc" font-size="15" font-weight="800" text-anchor="middle">${m.targetWaterVal}</text>
    <text x="293" y="484" fill="#94a3b8" font-size="6.6" text-anchor="middle">${m.targetWaterSub}</text>
    ${svgPufferAntiStaccoPortrait(52, 496, 316, 66, m.wo1cGauge)}

    <!-- 5. CIRCUITO SECONDARIO VERTICALE (Puffer <-> Casetta + Grundfos) -->
    <!-- Supply runs Puffer(125,572) -> Grundfos(125,614) -> bend at y=648 -> x=50 -> floor slab y=856 -->
    <path d="M 125 572 L 125 648 L 50 648 L 50 856" class="flow-sec-hot" />
    ${svgArrow(125, 584, 0, 1, m.pumpActive ? "#ef4444" : "#7f1d1d")}
    ${svgArrow(50, 759, 0, 1, m.pumpActive ? "#ef4444" : "#7f1d1d")}

    <!-- Return runs floor slab(370,856) -> y=648 -> x=295 -> Puffer(295,572) -->
    <path d="M 370 856 L 370 648 L 295 648 L 295 572" class="flow-sec-cold" />
    ${svgArrow(370, 759, 0, -1, m.pumpActive ? "#3b82f6" : "#1e40af")}
    ${svgArrow(295, 584, 0, -1, m.pumpActive ? "#3b82f6" : "#1e40af")}

    <!-- Grundfos Circulator on Secondary Supply -->
    ${svgCirculator(125, 614, 20, m.pumpActive, "spin-gf", m.pumpColor)}

    <g transform="translate(12, 594)">
      <rect x="0" y="0" width="90" height="40" rx="6" fill="#161f30" stroke="${m.pumpActive ? '#10b981' : '#475569'}" stroke-width="1.3" />
      <text x="45" y="14" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">GRUNDFOS</text>
      <text x="45" y="31" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="11" font-weight="800" text-anchor="middle">${m.pumpStatusShort}</text>
    </g>

    <g transform="translate(166, 596)">
      <rect x="0" y="0" width="88" height="36" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="44" y="13" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">CONS. RELÈ</text>
      <text x="44" y="28" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="10.5" font-weight="800" text-anchor="middle">${m.pumpActive ? "⚡ ATTIVO" : "⏸ APERTO"}</text>
    </g>

    <g transform="translate(314, 594)">
      <rect x="0" y="0" width="94" height="40" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="47" y="14" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">RIT. PAVIM.</text>
      <text x="47" y="29" fill="#64748b" font-size="8.5" font-weight="600" text-anchor="middle">Sonda assente</text>
    </g>

    <!-- 6. CASETTA STILIZZATA (Aria Esterna vs Aria Interna + Pavimento Radiante) -->
    <!-- Pitched House Roof & Room Body -->
    <polygon points="210,690 20,738 400,738" fill="#1b283f" stroke="#10b981" stroke-width="2.2" stroke-linejoin="round" />
    <text x="210" y="726" fill="#10b981" font-size="10.5" font-weight="800" text-anchor="middle" letter-spacing="0.4">🏠 ABITAZIONE (Massetto Radiante)</text>

    <!-- Outdoor badge cleanly in open air between roof slope and return pipe -->
    <g transform="translate(244, 658)">
      <rect x="0" y="0" width="114" height="30" rx="8" fill="#0c1e36" stroke="#38bdf8" stroke-width="1.2" stroke-dasharray="4,3" />
      <text x="57" y="12" fill="#94a3b8" font-size="7.2" font-weight="700" text-anchor="middle">☁️ ARIA FUORI CASA</text>
      <text x="57" y="25" fill="#38bdf8" font-size="10.5" font-weight="800" text-anchor="middle">${m.oat}</text>
    </g>

    <rect x="34" y="738" width="352" height="166" rx="8" fill="#131c2e" stroke="#10b981" stroke-width="2" />

    <!-- Wall-Mounted BTicino Smarther Thermostat & Indoor Air Card -->
    <rect x="52" y="748" width="316" height="88" rx="8" fill="#0f172a" stroke="#334155" stroke-width="1.2" />
    ${svgThermostatWallIcon(64, 762)}
    <text x="102" y="764" fill="#38bdf8" font-size="8.8" font-weight="800">ARIA CASA (Corridoio · ${m.apStateBadge})</text>
    <text x="102" y="786" fill="#10b981" font-size="19" font-weight="800">${m.indoor}</text>
    <text x="180" y="785" fill="#94a3b8" font-size="8.6" font-weight="600">UR ${m.humidity}</text>

    <text x="64" y="809" fill="#94a3b8" font-size="8.2" font-weight="700">🎯 TARGET CASA:</text>
    <text x="148" y="809" fill="#fde047" font-size="11.2" font-weight="800">${m.targetRoomReal}</text>

    <text x="250" y="809" fill="#94a3b8" font-size="8.2" font-weight="700">MARGINE:</text>
    <text x="302" y="809" fill="#e2e8f0" font-size="10.5" font-weight="700">${m.deltaTargetStr}</text>

    <text x="210" y="828" fill="${m.pumpActive ? '#6ee7b7' : '#64748b'}" font-size="8.5" font-weight="700" text-anchor="middle">
      ${m.pumpActive ? "🔥 Rilancio attivo dal Puffer al massetto radiante" : "⏸ Rilancio spento — Puffer disaccoppiato dalla casa"}
    </text>

    <!-- Floor Slab & Radiant Serpentines Connected to Pipes at x=50 and x=370 -->
    <rect x="44" y="842" width="332" height="54" rx="6" fill="#0b1120" stroke="#334155" stroke-width="1" />
    <text x="210" y="854" fill="#64748b" font-size="7.5" font-weight="700" text-anchor="middle">SERPENTINA PAVIMENTO RADIANTE</text>
    <path d="M 50 856
             L 50 862
             L 354 862
             Q 364 868 354 874
             L 66 874
             Q 56 880 66 886
             L 370 886
             L 370 856"
          fill="none" stroke="${m.pumpActive ? '#ef4444' : '#334155'}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />
  `;
}

// =========================================================================
// LANDSCAPE LAYOUT (1260 x 560) — Widescreen Industrial SCADA Schematic
// =========================================================================
function renderSynopticLandscape(m) {
  return `
    <rect x="0" y="0" width="1260" height="560" fill="#0c1322" rx="10" />

    <!-- TOP ATMOSPHERIC BAR: ARIA ESTERNA -->
    <rect x="20" y="10" width="1220" height="46" rx="10" fill="url(#skyGrad)" stroke="#38bdf8" stroke-width="1.3" stroke-dasharray="5,4" />
    ${svgCloudThermometerIcon(46, 33)}
    <text x="74" y="38" fill="#94a3b8" font-size="10.5" font-weight="700">ARIA ESTERNA (Sonda Climatica PdC):</text>
    <text x="305" y="39" fill="#38bdf8" font-size="17" font-weight="800">${m.oat}</text>
    <text x="415" y="37" fill="#cbd5e1" font-size="11" font-weight="600">|  Salto Casa–Fuori: <tspan fill="#10b981" font-weight="800">${m.deltaAirStr}</tspan></text>
    <text x="1222" y="37" fill="#94a3b8" font-size="10.5" font-weight="700" text-anchor="end">MODO: ${m.mode}  •  PROG: ${m.prog}  •  CURVA: ${m.slope}/${m.shift}</text>

    <!-- Dashed outdoor link to PdC -->
    <line x1="80" y1="56" x2="80" y2="70" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="3,2" />

    <!-- 1. PIPING CONNECTIONS -->
    <!-- Primary Supply (PdC -> P1 -> Puffer) -->
    <line x1="400" y1="168" x2="570" y2="168" class="flow-prim-hot" />
    ${svgArrow(432, 168, 1, 0, m.primPumpActive ? "#ef4444" : "#7f1d1d")}
    ${svgArrow(542, 168, 1, 0, m.primPumpActive ? "#ef4444" : "#7f1d1d")}
    <!-- Primary Return (Puffer -> PdC) -->
    <line x1="570" y1="450" x2="400" y2="450" class="flow-prim-cold" />
    ${svgArrow(525, 450, -1, 0, m.primPumpActive ? "#38bdf8" : "#1e3a5f")}
    ${svgArrow(445, 450, -1, 0, m.primPumpActive ? "#38bdf8" : "#1e3a5f")}

    <!-- Secondary Supply (Puffer -> Grundfos -> House radiant) -->
    <line x1="720" y1="168" x2="880" y2="168" class="flow-sec-hot" />
    ${svgArrow(752, 168, 1, 0, m.pumpActive ? "#ef4444" : "#7f1d1d")}
    ${svgArrow(852, 168, 1, 0, m.pumpActive ? "#ef4444" : "#7f1d1d")}
    <!-- Secondary Return (House -> Puffer) -->
    <line x1="880" y1="450" x2="720" y2="450" class="flow-sec-cold" />
    ${svgArrow(825, 450, -1, 0, m.pumpActive ? "#3b82f6" : "#1e3a5f")}
    ${svgArrow(765, 450, -1, 0, m.pumpActive ? "#3b82f6" : "#1e3a5f")}

    <!-- PIPE TAGS (Primary) -->
    <g transform="translate(425, 96)">
      <rect x="0" y="0" width="120" height="36" rx="6" fill="#161f30" stroke="#ef4444" stroke-width="1.4" />
      <text x="60" y="13" fill="#94a3b8" font-size="8.5" font-weight="700" text-anchor="middle">T MANDATA PDC</text>
      <text x="60" y="29" fill="#ef4444" font-size="12.5" font-weight="800" text-anchor="middle">${m.supply}</text>
    </g>

    ${svgCirculator(485, 168, 22, m.primPumpActive, "spin-prim", m.primPumpActive ? "#10b981" : "#1e293b")}
    <text x="485" y="206" fill="#94a3b8" font-size="9" font-weight="700" text-anchor="middle">Circolatore PdC P1</text>
    <text x="485" y="221" fill="${m.primPumpActive ? '#34d399' : '#64748b'}" font-size="10.5" font-weight="800" text-anchor="middle">${m.primPumpText}</text>

    <g transform="translate(442, 258)">
      <rect x="0" y="0" width="86" height="36" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="43" y="13" fill="#94a3b8" font-size="7.8" font-weight="700" text-anchor="middle">ΔT PRIMARIO</text>
      <text x="43" y="29" fill="#f8fafc" font-size="11.2" font-weight="700" text-anchor="middle">${m.deltaPrimStr}</text>
    </g>

    ${svgBackupHeaterBlock(442, 302, 86, 30, m)}

    <g transform="translate(425, 464)">
      <rect x="0" y="0" width="120" height="36" rx="6" fill="#161f30" stroke="#3b82f6" stroke-width="1.4" />
      <text x="60" y="13" fill="#94a3b8" font-size="8.5" font-weight="700" text-anchor="middle">T RITORNO PDC</text>
      <text x="60" y="29" fill="#38bdf8" font-size="12.5" font-weight="800" text-anchor="middle">${m.ret}</text>
    </g>

    <!-- 2. ZONE A: VITOCAL 111-S -->
    <rect x="20" y="70" width="380" height="474" rx="12" fill="#161f30" stroke="#38bdf8" stroke-width="2" />
    <text x="36" y="94" fill="#38bdf8" font-size="11.5" font-weight="800" letter-spacing="0.4">⚡ POMPA DI CALORE VIESSMANN (Vitocal 111-S)</text>

    <!-- Evaporator fan + Compressor + Mini ACS -->
    <rect x="34" y="106" width="108" height="106" rx="8" fill="#0f172a" stroke="${m.compColor}" stroke-width="1.3" />
    ${svgEvaporatorFan(88, 144, 24, m.compActive)}
    <text x="88" y="185" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">COMPRESSORE</text>
    <text x="88" y="202" fill="${m.compColor}" font-size="11" font-weight="800" text-anchor="middle">${m.compStatusShort}</text>

    ${svgBadge(152, 106, 128, 50, "Pressione Gas Caldo", m.gasPress, "#ec4899")}
    ${svgBadge(152, 162, 128, 50, "Circolatore Primario", m.primPumpText, "#34d399")}

    ${svgMiniBoiler(290, 106, 96, 106, m.dhw)}

    ${svgBadge(34, 222, 170, 48, "T Gas Caldo", m.hotGas, "#f87171")}
    ${svgBadge(214, 222, 172, 48, "T Gas Liquido Frigo", m.liqGas, "#38bdf8")}

    ${svgBadge(34, 278, 170, 48, "T Gas Aspirazione", m.sucGas, "#93c5fd")}
    ${svgBadge(214, 278, 172, 48, "Sonda Esterna OAT", m.oat, "#f59e0b")}

    ${svgBadge(34, 334, 170, 48, "COP Riscaldamento", m.copH, "#10b981")}
    ${svgBadge(214, 334, 172, 48, "COP Totale Macchina", m.copTot, "#6ee7b7")}

    ${svgBadge(34, 390, 170, 48, "Ore Compressore", m.compHours, "#e2e8f0")}
    ${svgBadge(214, 390, 172, 48, "Avvii Totali", m.compStarts, "#e2e8f0")}

    ${svgBadge(34, 446, 170, 48, "Curva Climatica", `Slp ${m.slope} | Shf ${m.shift}`, "#60a5fa")}
    ${svgBadge(214, 446, 172, 48, "Programma Attivo", m.prog, "#a78bfa")}

    <rect x="34" y="502" width="352" height="30" rx="6" fill="#0f172a" stroke="#334155" />
    <text x="210" y="521" fill="#94a3b8" font-size="9.5" font-weight="700" text-anchor="middle">MODO: ${m.mode}  |  WO1C CU401B</text>

    <!-- 3. ZONE B: PUFFER INERZIALE 200 L (+ SCADA Anti-Stacco 7209 Gauge) -->
    <rect x="570" y="102" width="150" height="414" rx="28" fill="url(#pufferGrad)" stroke="#f59e0b" stroke-width="2.5" />
    <text x="645" y="134" fill="#f59e0b" font-size="12.5" font-weight="800" text-anchor="middle">PUFFER 200 L</text>
    <text x="645" y="149" fill="#94a3b8" font-size="8.5" text-anchor="middle">(Sensore WO1C)</text>

    <rect x="582" y="162" width="126" height="54" rx="8" fill="#0f172a" stroke="#f59e0b" stroke-width="1.3" />
    <text x="645" y="179" fill="#94a3b8" font-size="7.8" font-weight="700" text-anchor="middle">SONDA ACCUMULO</text>
    <text x="645" y="205" fill="#fbbf24" font-size="16" font-weight="800" text-anchor="middle">${m.buffer}</text>

    <rect x="582" y="222" width="126" height="60" rx="8" fill="#0f172a" stroke="#e879f9" stroke-width="1.3" />
    <text x="645" y="239" fill="#e879f9" font-size="7.6" font-weight="700" text-anchor="middle">🎯 TARGET ACQUA</text>
    <text x="645" y="263" fill="#f0abfc" font-size="15" font-weight="800" text-anchor="middle">${m.targetWaterVal}</text>
    <text x="645" y="276" fill="#94a3b8" font-size="6.6" text-anchor="middle">${m.targetWaterSub}</text>

    ${svgPufferAntiStaccoLandscape(580, 290, 130, 154, m.wo1cGauge)}

    <text x="645" y="484" fill="#64748b" font-size="8.2" font-weight="700" text-anchor="middle">Disaccoppiatore Idraulico</text>
    <text x="645" y="497" fill="#64748b" font-size="8.2" text-anchor="middle">Primario / Secondario</text>

    <!-- 4. CIRCOLATORE GRUNDFOS -->
    ${svgCirculator(800, 168, 24, m.pumpActive, "spin-gf", m.pumpColor)}
    <text x="800" y="132" fill="#94a3b8" font-size="9.5" font-weight="700" text-anchor="middle">Circolatore Grundfos</text>
    <text x="800" y="210" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="10.5" font-weight="800" text-anchor="middle">${m.pumpStatusShort}</text>

    <g transform="translate(744, 464)">
      <rect x="0" y="0" width="112" height="36" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="56" y="13" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">RITORNO RADIANTE</text>
      <text x="56" y="28" fill="#64748b" font-size="8.5" font-weight="600" text-anchor="middle">Sonda non presente</text>
    </g>

    <!-- 5. ZONE C: CASETTA STILIZZATA (Interno vs Esterno + Massetto Radiante) -->
    <polygon points="1060,78 866,132 1254,132" fill="#1b283f" stroke="#10b981" stroke-width="2.2" stroke-linejoin="round" />
    <text x="1060" y="118" fill="#10b981" font-size="11.5" font-weight="800" text-anchor="middle">🏠 ABITAZIONE (Interno vs Esterno)</text>

    <!-- Outdoor badge cleanly outside right roof slope -->
    <g transform="translate(1120, 64)">
      <rect x="0" y="0" width="124" height="32" rx="8" fill="#0c1e36" stroke="#38bdf8" stroke-width="1.2" stroke-dasharray="4,3" />
      <text x="62" y="13" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">☁️ ARIA ESTERNA</text>
      <text x="62" y="26" fill="#38bdf8" font-size="11" font-weight="800" text-anchor="middle">${m.oat}</text>
    </g>

    <rect x="880" y="132" width="360" height="412" rx="10" fill="#131c2e" stroke="#10b981" stroke-width="2" />

    <!-- Internal pipe drop along left inner wall from y=168 to radiant slab y=424 -->
    <line x1="880" y1="168" x2="906" y2="168" class="flow-sec-hot" />
    <line x1="906" y1="168" x2="906" y2="424" class="flow-sec-hot" />
    <line x1="906" y1="450" x2="880" y2="450" class="flow-sec-cold" />

    <!-- BTicino Smarther Card inside room -->
    <rect x="922" y="146" width="302" height="236" rx="10" fill="#0f172a" stroke="#10b981" stroke-width="1.4" />
    ${svgThermostatWallIcon(938, 162)}
    <text x="976" y="172" fill="#38bdf8" font-size="10.5" font-weight="800">BTICINO SMARTHER (Corridoio)</text>
    <text x="976" y="187" fill="#94a3b8" font-size="8.5" font-weight="600">Sensore Aria Interna Casa</text>

    ${svgBadge(936, 202, 132, 50, "Aria Interna", m.indoor, "#10b981")}
    ${svgBadge(1078, 202, 132, 50, "Umidità Relativa", m.humidity, "#60a5fa")}
    ${svgBadge(936, 260, 132, 50, "Target Casa Reale", m.targetRoomReal, "#fde047")}
    ${svgBadge(1078, 260, 132, 50, "Regia Attiva", m.apStateBadge, "#c084fc")}

    <!-- Relay Banner inside house -->
    <rect x="936" y="320" width="274" height="50" rx="8" fill="#161f30" stroke="${m.pumpActive ? '#10b981' : '#334155'}" stroke-width="1.3" />
    <text x="1073" y="341" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="11.5" font-weight="800" text-anchor="middle">
      ${m.pumpActive ? "⚡ CONSENSO POMPA ATTIVO" : "⏸ NESSUNA RICHIESTA (Standby)"}
    </text>
    <text x="1073" y="359" fill="#64748b" font-size="8.5" text-anchor="middle">
      ${m.pumpActive ? "Calore trasferito al massetto radiante" : "Puffer disaccoppiato dall'abitazione"}
    </text>

    <!-- Underfloor Radiant Floor Slab (connected to pipes!) -->
    <rect x="896" y="400" width="328" height="128" rx="8" fill="#0b1120" stroke="#334155" stroke-width="1.2" />
    <text x="1060" y="416" fill="#64748b" font-size="8.5" font-weight="700" text-anchor="middle">SERPENTINE PAVIMENTO RADIANTE</text>
    <path d="M 906 424
             L 1200 424
             Q 1214 432 1200 440
             L 928 440
             Q 914 448 928 456
             L 1200 456
             Q 1214 464 1200 472
             L 928 472
             Q 914 480 928 488
             L 1200 488
             Q 1214 498 1200 508
             L 906 508
             L 906 450"
          fill="none" stroke="${m.pumpActive ? '#ef4444' : '#334155'}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
  `;
}

// =========================================================================
// REUSABLE SCADA SVG PRIMITIVES
// =========================================================================
function svgBadge(x, y, w, h, label, value, color) {
  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="8" y="14" fill="#94a3b8" font-size="7.8" font-weight="700" text-anchor="start">${label.toUpperCase()}</text>
      <text x="8" y="${h - 10}" fill="${color}" font-size="12.5" font-weight="800" text-anchor="start">${value}</text>
    </g>
  `;
}

function svgCirculator(cx, cy, r, active, spinClass, fillCol) {
  const border = active ? "#ffffff" : "#64748b";
  const bLen = Math.round(r * 0.58);
  const hubR = Math.max(4, Math.round(r * 0.28));
  return `
    <g transform="translate(${cx}, ${cy})">
      <circle cx="0" cy="0" r="${r}" fill="${fillCol}" stroke="${border}" stroke-width="2.2" />
      <g class="${spinClass}">
        <line x1="-${bLen}" y1="0" x2="${bLen}" y2="0" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" />
        <line x1="0" y1="-${bLen}" x2="0" y2="${bLen}" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" />
      </g>
      <circle cx="0" cy="0" r="${hubR}" fill="#0f172a" stroke="#ffffff" stroke-width="1.4" />
    </g>
  `;
}

function svgEvaporatorFan(cx, cy, r, active) {
  const col = active ? "#38bdf8" : "#475569";
  return `
    <g transform="translate(${cx}, ${cy})">
      <circle cx="0" cy="0" r="${r}" fill="#0c1526" stroke="${col}" stroke-width="1.6" stroke-dasharray="3,2" />
      <g class="spin-fan">
        <path d="M 0 0 C -5 -14 7 -18 8 -7 C 9 -2 3 0 0 0 Z" fill="${col}" />
        <path d="M 0 0 C 14 2 14 14 4 11 C -1 9 -1 3 0 0 Z" fill="${col}" />
        <path d="M 0 0 C -11 10 -18 0 -10 -7 C -6 -10 -1 -3 0 0 Z" fill="${col}" />
      </g>
      <circle cx="0" cy="0" r="4" fill="#0f172a" stroke="#e2e8f0" stroke-width="1.2" />
    </g>
  `;
}

function svgMiniBoiler(x, y, w, h, tempStr) {
  const cx = x + w / 2;
  return `
    <g>
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="#0f172a" stroke="#c084fc" stroke-width="1.4" />
      <text x="${cx}" y="${y + 15}" fill="#c084fc" font-size="8" font-weight="800" text-anchor="middle">BOLLITORE ACS</text>
      <text x="${cx}" y="${y + 26}" fill="#94a3b8" font-size="7.5" text-anchor="middle">220 Litri</text>
      <path d="M ${cx - 18} ${y + 36} Q ${cx + 22} ${y + 42} ${cx - 18} ${y + 48} Q ${cx + 22} ${y + 54} ${cx - 18} ${y + 60}"
            fill="none" stroke="#a855f7" stroke-width="2" stroke-linecap="round" opacity="0.7" />
      <text x="${cx}" y="${y + h - 12}" fill="#e9d5ff" font-size="13.5" font-weight="800" text-anchor="middle">${tempStr}</text>
    </g>
  `;
}

function svgCloudThermometerIcon(cx, cy) {
  return `
    <g transform="translate(${cx}, ${cy})">
      <path d="M -14 6 C -18 6 -20 2 -18 -2 C -16 -6 -10 -7 -7 -4 C -4 -11 7 -11 10 -3 C 15 -3 18 1 16 5 C 15 7 12 7 9 7 L -14 7 Z"
            fill="#1e3a5f" stroke="#38bdf8" stroke-width="1.4" />
      <rect x="6" y="-8" width="5" height="14" rx="2.5" fill="#0f172a" stroke="#f59e0b" stroke-width="1.2" />
      <circle cx="8.5" cy="7" r="4" fill="#f59e0b" />
    </g>
  `;
}

function svgThermostatWallIcon(x, y) {
  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="26" height="26" rx="5" fill="#1e293b" stroke="#38bdf8" stroke-width="1.4" />
      <rect x="4" y="5" width="18" height="10" rx="2" fill="#0c1526" />
      <circle cx="13" cy="20" r="2" fill="#10b981" />
    </g>
  `;
}

function svgArrow(x, y, dx, dy, color) {
  const size = 5;
  let pts = "";
  if (dx > 0) pts = `${x - size},${y - size} ${x + size},${y} ${x - size},${y + size}`;
  else if (dx < 0) pts = `${x + size},${y - size} ${x - size},${y} ${x + size},${y + size}`;
  else if (dy > 0) pts = `${x - size},${y - size} ${x},${y + size} ${x + size},${y - size}`;
  else pts = `${x - size},${y + size} ${x},${y - size} ${x + size},${y + size}`;
  return `<polygon points="${pts}" fill="${color}" />`;
}

function svgBackupHeaterBlock(x, y, w, h, m) {
  const bg = m.rodActive ? "#2a1219" : "#0f172a";
  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="6" fill="${bg}" stroke="${m.rodBorder}" stroke-width="${m.rodActive ? 1.5 : 1}" />
      <text x="${w / 2}" y="11" fill="#94a3b8" font-size="6.8" font-weight="700" text-anchor="middle">RESIST. S1/S2</text>
      <text x="${w / 2}" y="${h - 5}" fill="${m.rodColor}" font-size="8.6" font-weight="800" text-anchor="middle">${m.rodStatusCompact}</text>
    </g>
  `;
}

// =========================================================================
// LIVE WO1C ANTI-STACCO (7209) & HYSTERESIS (7203) / DEFROST BPHE GAUGE
// Calibrated on real 21/11, 24/11 & 26/11 Vitocal 111-S peaks & cutoffs:
//   - 7209 cutoff occurs when BOTH BUF >= Target + 2.1..2.7 K AND EWT >= Target - 0.2 K
//   - 7203 restart occurs when BUF <= Target - 5.0 K
//   - Defrost BPHE guard: LWT >= 12.0 C, BUF >= 17.0 C
// =========================================================================
function computeLastCyclePeak7209(samplesList) {
  if (!Array.isArray(samplesList) || samplesList.length === 0) return null;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let foundActive = false;
  let lastActiveMs = null;
  let best = null;

  for (let i = samplesList.length - 1; i >= 0; i--) {
    const s = samplesList[i];
    if (!s || !s.timestamp_utc) continue;
    const tMs = new Date(s.timestamp_utc).getTime();
    if (isNaN(tMs)) continue;

    const mod = s.compressor_modulation_percent != null ? Number(s.compressor_modulation_percent) : 0;
    const active = (s.compressor_active === 1) || (mod > 0);
    const phase = String(s.compressor_phase || "").toLowerCase();

    if (!active) {
      if (foundActive && lastActiveMs != null && (lastActiveMs - tMs) > 45 * 60000) {
        break; // Reached standby before this cycle started
      }
      continue;
    }

    foundActive = true;
    lastActiveMs = tMs;
    if (phase.includes("defrost")) continue;

    const buf = s.buffer_temp_c != null ? Number(s.buffer_temp_c) : null;
    const ewt = s.pdc_return_temp_c != null ? Number(s.pdc_return_temp_c) : null;
    let tgt = s.target_supply_temp_c != null ? Number(s.target_supply_temp_c) : null;
    if (tgt == null && typeof computeVitocalTargetLwt === "function") {
      tgt = computeVitocalTargetLwt(s, false);
    }
    if (buf == null || tgt == null) continue;

    const marginBuf = (tgt + 2.5) - buf;
    const marginEwt = ewt != null ? (tgt - ewt) : null;
    const satBuf = clamp((buf - (tgt - 0.5)) / 3.0, 0, 1);
    const satEwt = ewt != null ? clamp((ewt - (tgt - 2.5)) / 2.5, 0, 1) : satBuf * 0.85;
    let satFrac = 0.50 * satBuf + 0.50 * satEwt;
    if ((buf - tgt) > 0.6 && mod >= 68) satFrac = Math.min(1.0, satFrac + 0.08);
    if (marginEwt != null && marginEwt > 0.35) satFrac = Math.min(satFrac, 0.78);
    if (marginBuf <= 0.8 && (marginEwt == null || marginEwt <= 0.30)) satFrac = Math.max(satFrac, 0.88);
    const pct = Math.round(clamp(satFrac, 0.04, 1.0) * 100);

    if (!best || pct > best.maxPct) {
      const dt = new Date(tMs);
      const dd = String(dt.getDate()).padStart(2, "0");
      const mm = String(dt.getMonth() + 1).padStart(2, "0");
      const hh = String(dt.getHours()).padStart(2, "0");
      const mi = String(dt.getMinutes()).padStart(2, "0");
      best = {
        maxPct: pct,
        maxTone: pct >= 85 ? "danger" : (pct >= 64 ? "warn" : "safe"),
        satBufPct: Math.round(satBuf * 100),
        satEwtPct: Math.round(satEwt * 100),
        marginBuf,
        marginEwt,
        buf,
        ewt,
        tgt,
        mod,
        timeStr: `${dd}/${mm} ${hh}:${mi}`,
        shortTime: `${hh}:${mi}`,
      };
    }
  }
  return best;
}

function computeWo1cCutoffMargin(d, samplesList) {
  const lastPeak = computeLastCyclePeak7209(samplesList);
  if (!d) {
    return {
      mode: "standby",
      title: "🛡️ Anti-Stacco WO1C (7209)",
      badge: "STANDBY",
      tone: "idle",
      pct: 0,
      pctLabel: "STBY",
      satBufPct: 0,
      satEwtPct: 0,
      lastPeak,
      summary: "In attesa dati telemetrici...",
      chips: [],
    };
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const progLower = String(d.active_program || "standby").toLowerCase();
  const phaseLower = String(d.compressor_phase || "off").toLowerCase();
  const modNum = d.compressor_modulation_percent != null ? Number(d.compressor_modulation_percent) : 0;
  const compActive = (d.compressor_active === 1) || (modNum > 0);
  const isDefrost = phaseLower.includes("defrost");

  const buf = d.buffer_temp_c != null ? Number(d.buffer_temp_c) : null;
  const ewt = d.pdc_return_temp_c != null ? Number(d.pdc_return_temp_c) : null;
  const lwt = d.pdc_supply_temp_c != null ? Number(d.pdc_supply_temp_c) : null;

  const apSt = (typeof cmdState !== "undefined" && cmdState.lastAutopilotState) ? cmdState.lastAutopilotState : null;
  let targetLwt = d.target_supply_temp_c != null ? Number(d.target_supply_temp_c) : null;
  if (targetLwt == null && typeof computeVitocalTargetLwt === "function") {
    targetLwt = computeVitocalTargetLwt(d, progLower === "standby");
  }
  if (targetLwt == null && apSt && apSt.calculated_target_lwt_c != null) {
    targetLwt = Number(apSt.calculated_target_lwt_c);
  }

  // Standby: PdC off and outside active heating schedule -> show standby state + last cycle peak memory!
  if (!compActive && progLower === "standby") {
    const pkIcon = lastPeak ? (lastPeak.maxPct >= 85 ? "🔴" : (lastPeak.maxPct >= 64 ? "🟡" : "🟢")) : "⏸";
    return {
      mode: "standby",
      title: "🛡️ Anti-Stacco WO1C (7209)",
      badge: lastPeak ? `STANDBY · ULT. PICCO ${pkIcon} ${lastPeak.maxPct}%` : "STANDBY (attivo in marcia)",
      tone: "idle",
      pct: 0,
      pctLabel: "OFF",
      ghostPct: lastPeak ? lastPeak.maxPct : null,
      ghostTone: lastPeak ? lastPeak.maxTone : "idle",
      satBufPct: lastPeak ? lastPeak.satBufPct : 0,
      satEwtPct: lastPeak ? lastPeak.satEwtPct : 0,
      marginBuf: null,
      marginEwt: null,
      modNum: 0,
      lastPeak,
      summary: lastPeak
        ? `PdC a riposo. Ultimo ciclo (${lastPeak.timeStr}): picco saturazione ${lastPeak.maxPct}% (marg. min Testa ${lastPeak.marginBuf >= 0 ? "+" : ""}${lastPeak.marginBuf.toFixed(1)} K${lastPeak.marginEwt != null ? `, Fondo ${lastPeak.marginEwt >= 0 ? "+" : ""}${lastPeak.marginEwt.toFixed(1)} K` : ""}). Tocca per dettagli.`
        : "PdC in standby: il tachimetro si accende in tempo reale appena parte il compressore.",
      chips: lastPeak
        ? [
            {
              lbl: `Picco Testa (${lastPeak.shortTime})`,
              val: `${lastPeak.buf.toFixed(1)}° / ${(lastPeak.tgt + 2.5).toFixed(1)}°`,
              sub: `Marg. min ${lastPeak.marginBuf >= 0 ? "+" : ""}${lastPeak.marginBuf.toFixed(1)} K (Tgt ${lastPeak.tgt.toFixed(1)}°)`,
            },
            {
              lbl: `Picco Fondo (${lastPeak.shortTime})`,
              val: lastPeak.ewt != null ? `${lastPeak.ewt.toFixed(1)}° / ${lastPeak.tgt.toFixed(1)}°` : "--",
              sub: lastPeak.marginEwt != null ? `Marg. min ${lastPeak.marginEwt >= 0 ? "+" : ""}${lastPeak.marginEwt.toFixed(1)} K` : "--",
            },
            {
              lbl: "Puffer Ora (Riposo)",
              val: buf != null ? `BUF ${buf.toFixed(1)} °C` : "--",
              sub: `Ult. picco: Mod ${lastPeak.mod.toFixed(0)}% · Sat ${lastPeak.maxPct}%`,
            },
          ]
        : [
            { lbl: "Puffer Attuale", val: buf != null ? `${buf.toFixed(1)} °C` : "--", sub: "Macchina a riposo" },
            { lbl: "Ritorno Attuale", val: ewt != null ? `${ewt.toFixed(1)} °C` : "--", sub: "Circolatori fermi" },
            { lbl: "Soglia WO1C 7209", val: "BUF +2.5K & EWT ≥ Tgt", sub: "Attivo a compressore ON" },
          ],
    };
  }

  // Compute real trend over the last 2.5 - 10 min from telemetry history
  let dBufPerMin = null;
  let dEwtPerMin = null;
  let dModPerMin = null;
  if (Array.isArray(samplesList) && samplesList.length >= 2 && d.timestamp_utc) {
    const nowMs = new Date(d.timestamp_utc).getTime();
    if (!isNaN(nowMs)) {
      let ref = null;
      for (let i = samplesList.length - 2; i >= 0; i--) {
        const s = samplesList[i];
        if (!s || !s.timestamp_utc) continue;
        const tMs = new Date(s.timestamp_utc).getTime();
        if (isNaN(tMs)) continue;
        const dtMin = (nowMs - tMs) / 60000.0;
        if (dtMin >= 2.5 && dtMin <= 12.0) {
          ref = { s, dtMin };
          break;
        }
        if (dtMin > 12.0) break;
      }
      if (ref && ref.dtMin > 0) {
        if (buf != null && ref.s.buffer_temp_c != null) {
          dBufPerMin = (buf - Number(ref.s.buffer_temp_c)) / ref.dtMin;
        }
        if (ewt != null && ref.s.pdc_return_temp_c != null) {
          dEwtPerMin = (ewt - Number(ref.s.pdc_return_temp_c)) / ref.dtMin;
        }
        if (ref.s.compressor_modulation_percent != null) {
          dModPerMin = (modNum - Number(ref.s.compressor_modulation_percent)) / ref.dtMin;
        }
      }
    }
  }

  // Case A: Defrost active -> Show live BPHE safety reserve (LWT >= 12 C, BUF >= 17 C)
  if (isDefrost) {
    const lwtMarg = lwt != null ? (lwt - 12.0) : null;
    const bufMarg = buf != null ? (buf - 17.0) : null;
    const stressPct = lwt != null ? Math.round(clamp((22.0 - lwt) / 10.0, 0.08, 1.0) * 100) : 50;
    let tone = "defrost";
    let badge = "❄️ DEFROST · BPHE OK";
    let summary = "Sbrinamento in corso: riserva termica scambiatore BPHE nella fascia sicura.";
    if ((lwtMarg != null && lwtMarg < 0.5) || (bufMarg != null && bufMarg < -1.0)) {
      tone = "danger";
      badge = "🔴 DEFROST · BPHE CRITICO";
      summary = "Acqua BPHE vicina/sotto soglia 12 °C: possibile intervento resistenza o stress termico.";
    } else if ((lwtMarg != null && lwtMarg < 2.0) || (bufMarg != null && bufMarg < 0.5)) {
      tone = "warn";
      badge = "⚠️ DEFROST · BPHE IN CALO";
      summary = "Sbrinamento profondo: monitorare LWT minima (soglia sicurezza ≥ 12.0 °C).";
    }
    return {
      mode: "defrost",
      title: "❄️ Riserva BPHE Sbrinamento (Live)",
      badge,
      tone,
      pct: stressPct,
      pctLabel: lwt != null ? `${lwt.toFixed(1)}°` : "--",
      satBufPct: bufMarg != null ? Math.round(clamp((6.0 - bufMarg) / 6.0, 0.05, 1.0) * 100) : 40,
      satEwtPct: lwtMarg != null ? Math.round(clamp((10.0 - lwtMarg) / 10.0, 0.05, 1.0) * 100) : 40,
      marginBuf: bufMarg,
      marginEwt: lwtMarg,
      modNum,
      lastPeak,
      summary,
      chips: [
        {
          lbl: "Mandata BPHE (LWT)",
          val: lwt != null ? `${lwt.toFixed(1)}° / min 12.0°` : "--",
          sub: lwtMarg != null ? `Marg. ${lwtMarg >= 0 ? "+" : ""}${lwtMarg.toFixed(1)} K` : "Soglia guardia 12.0 °C",
        },
        {
          lbl: "Puffer 200L (BUF)",
          val: buf != null ? `${buf.toFixed(1)}° / min 17.0°` : "--",
          sub: bufMarg != null ? `Marg. ${bufMarg >= 0 ? "+" : ""}${bufMarg.toFixed(1)} K` : "Riserva accumulo",
        },
        {
          lbl: "Fase & Ritorno",
          val: `Mod ${modNum.toFixed(0)}% · Defrost`,
          sub: ewt != null ? `EWT ${ewt.toFixed(1)}°C · P1 ${d.primary_pump_rotation_percent ?? 0}%` : "Inversione 4-vie",
        },
      ],
    };
  }

  // Case B: Paused / Off / Preparing inside active heating schedule -> WO1C 7203 restart countdown
  if (!compActive && progLower !== "standby") {
    const restartThr = targetLwt != null ? (targetLwt - 5.0) : null;
    const distRestart = (buf != null && restartThr != null) ? (buf - restartThr) : null;
    const coolPct = (buf != null && targetLwt != null)
      ? Math.round(clamp(((targetLwt + 2.5) - buf) / 7.5, 0.05, 1.0) * 100)
      : 50;
    let etaTxt = "";
    if (distRestart != null && distRestart > 0 && dBufPerMin != null && dBufPerMin < -0.05) {
      const mins = Math.max(1, Math.round(distRestart / (-dBufPerMin)));
      if (mins <= 45) etaTxt = ` · riavvio stimato ~${mins} min`;
    }
    const isPrep = phaseLower === "preparing";
    return {
      mode: "pause",
      title: isPrep ? "⏳ Avviamento Compressore WO1C" : "⏸️ Pausa Isteresi WO1C (7203)",
      badge: isPrep ? "AVVIAMENTO..." : "PAUSA 7203",
      tone: "pause",
      pct: isPrep ? 96 : coolPct,
      pctLabel: distRestart != null ? `${distRestart <= 0 ? "0.0" : distRestart.toFixed(1)}K` : "--",
      satBufPct: isPrep ? 96 : coolPct,
      satEwtPct: coolPct,
      marginBuf: distRestart,
      marginEwt: null,
      modNum: 0,
      lastPeak,
      summary: isPrep
        ? "Puffer sceso a soglia 7203: compressore in fase di preparazione / riavvio."
        : (distRestart != null && restartThr != null
          ? `Stacco per puffer saturo: riaccensione WO1C prevista a BUF ≤ ${restartThr.toFixed(1)} °C (mancano ${Math.max(0, distRestart).toFixed(1)} K${etaTxt}).`
          : "Compressore in pausa termostatica all'interno della fascia attiva."),
      chips: [
        {
          lbl: "Puffer (BUF) → Riavvio",
          val: (buf != null && restartThr != null) ? `${buf.toFixed(1)}° → ${restartThr.toFixed(1)}°` : "--",
          sub: distRestart != null ? `Restano ${Math.max(0, distRestart).toFixed(1)} K (7203)` : "Isteresi −5.0 K",
        },
        {
          lbl: "Fondo / Ritorno (EWT)",
          val: (ewt != null && targetLwt != null) ? `${ewt.toFixed(1)}° / Tgt ${targetLwt.toFixed(1)}°` : "--",
          sub: (ewt != null && targetLwt != null) ? `Δ ${(ewt - targetLwt) >= 0 ? "+" : ""}${(ewt - targetLwt).toFixed(1)} K` : "--",
        },
        {
          lbl: "Scarico Puffer",
          val: dBufPerMin != null ? `${dBufPerMin >= 0 ? "+" : ""}${dBufPerMin.toFixed(2)} °C/m` : "In attesa trend",
          sub: d.grundfos_pump_active === 1 ? "Grundfos ON (scarica casa)" : "Grundfos OFF",
        },
      ],
    };
  }

  // Case C: Active Heating -> Dual-sensor WO1C 7209 Cutoff Proximity Gauge
  if (buf == null || targetLwt == null) {
    return {
      mode: "heating",
      title: "🛡️ Anti-Stacco WO1C (7209)",
      badge: "IN MARCIA",
      tone: "safe",
      pct: 25,
      pctLabel: "--%",
      satBufPct: 25,
      satEwtPct: 25,
      marginBuf: null,
      marginEwt: null,
      modNum,
      lastPeak,
      summary: "Compressore attivo; in attesa di sonde Puffer/Target per calcolare il margine 7209.",
      chips: [
        { lbl: "Testa Puffer (BUF)", val: buf != null ? `${buf.toFixed(1)} °C` : "--", sub: "--" },
        { lbl: "Fondo / Ritorno (EWT)", val: ewt != null ? `${ewt.toFixed(1)} °C` : "--", sub: "--" },
        { lbl: "Inverter & Trend PI", val: `Mod ${modNum.toFixed(0)}%`, sub: "--" },
      ],
    };
  }

  const cutoffBuf = targetLwt + 2.5; // Real verified 7209 top threshold (+2.1..+2.7 K)
  const cutoffEwt = targetLwt;       // Real verified 7209 bottom threshold (-0.2..+0.1 K)
  const deltaBuf = buf - targetLwt;  // Signed delta vs Target (+0.45 K at steady state)
  const deltaEwt = ewt != null ? (ewt - targetLwt) : null; // Signed delta vs Target (-1.37 K at steady state)
  const marginBuf = cutoffBuf - buf; // Remaining headroom before +2.5 K (>0 safe, <=0 exceeded)
  const marginEwt = ewt != null ? (cutoffEwt - ewt) : null; // Remaining headroom before 0.0 K

  // Recalibrated on 1,907 real samples (21/11, 24/11, 26/11):
  // Steady state (BUF = Tgt+0.45K, EWT = Tgt-1.37K, Mod 40-50%) -> ~38% GREEN (never false yellow!)
  // Dual saturation (BUF >= Tgt+1.7K AND EWT >= Tgt-0.3K) -> 85-100% RED!
  const satBuf = clamp((buf - (targetLwt - 0.5)) / 3.0, 0, 1);
  const satEwt = ewt != null ? clamp((ewt - (targetLwt - 2.5)) / 2.5, 0, 1) : satBuf * 0.85;
  let satFrac = (satBuf * 0.50) + (satEwt * 0.50);

  // PI wind-up urgency: only when buffer already exceeds target + 0.6 K AND modulation >= 68% AND rising
  const piLagPush = (deltaBuf > 0.6 && modNum >= 68 && (dBufPerMin == null || dBufPerMin > 0.04));
  if (piLagPush) satFrac = Math.min(1.0, satFrac + 0.10);

  // Key verified physical invariant (21/11 11:51 & 24/11 13:25): if EWT is still >= 0.35 K below Target,
  // bottom of puffer is absorbing heat and WO1C does NOT trip 7209 yet -> cap below red!
  if (marginEwt != null && marginEwt > 0.35) {
    satFrac = Math.min(satFrac, 0.78);
  }
  // Dual saturation imminent (24/11 14:11, 26/11 11:53 & 13:02): both top and bottom near limit!
  if (marginBuf <= 0.8 && (marginEwt == null || marginEwt <= 0.30)) {
    satFrac = Math.max(satFrac, 0.88);
  }
  const satPct = Math.round(clamp(satFrac, 0.04, 1.0) * 100);

  // Optional ETA to cutoff when climbing toward saturation
  let etaStr = "";
  if (satPct >= 60 && dBufPerMin != null && dBufPerMin > 0.05 && marginBuf > 0) {
    const etaBuf = marginBuf / dBufPerMin;
    const etaEwt = (marginEwt != null && marginEwt > 0 && dEwtPerMin != null && dEwtPerMin > 0.03)
      ? (marginEwt / dEwtPerMin)
      : null;
    const etaMin = etaEwt != null ? Math.max(etaBuf, etaEwt) : etaBuf;
    if (etaMin <= 30) {
      etaStr = ` · limite in ~${Math.max(1, Math.round(etaMin))} min se Mod non cala`;
    }
  }

  const fmtSigned = v => `${v >= 0 ? "+" : ""}${v.toFixed(1)} K`;
  let tone = "safe";
  let badge = "🟢 MARGINE AMPIO";
  let summary = `Regime sicuro: testa a ${marginBuf.toFixed(1)} K dallo stacco (BUF ${fmtSigned(deltaBuf)} su Tgt)${marginEwt != null ? `, fondo a ${marginEwt.toFixed(1)} K (EWT ${fmtSigned(deltaEwt)})` : ""}.`;

  if (satPct >= 85 || (marginBuf <= 0.8 && (marginEwt == null || marginEwt <= 0.30))) {
    tone = "danger";
    badge = "🔴 RISCHIO STACCO 7209";
    summary = `Puffer quasi saturo testa-fondo: BUF ${fmtSigned(deltaBuf)} su Tgt (marg. ${marginBuf.toFixed(1)} K), EWT ${deltaEwt != null ? fmtSigned(deltaEwt) : "--"}${etaStr}.`;
  } else if (satPct >= 64 || (marginBuf <= 1.2 && (marginEwt == null || marginEwt <= 0.8)) || piLagPush) {
    tone = "warn";
    badge = piLagPush ? "🟡 ATTENZIONE (PI ALTO)" : "🟡 IN AVVICINAMENTO";
    if (marginEwt != null && marginEwt > 0.35) {
      summary = `Testa alta (BUF ${fmtSigned(deltaBuf)} su Tgt, marg. ${marginBuf.toFixed(1)} K) ma fondo ancora sotto target (EWT ${fmtSigned(deltaEwt)}): se il PI frena evita lo stacco${etaStr}.`;
    } else {
      summary = `Puffer vicino alla soglia 7209: mancano ${marginBuf.toFixed(1)} K in testa e ${marginEwt != null ? marginEwt.toFixed(1) : "--"} K sul fondo${etaStr}.`;
    }
  }

  const dBufTxt = dBufPerMin != null ? `${dBufPerMin >= 0 ? "+" : ""}${dBufPerMin.toFixed(2)}°/m` : "trend --";
  const dModTxt = dModPerMin != null && Math.abs(dModPerMin) >= 0.3 ? ` (${dModPerMin >= 0 ? "+" : ""}${dModPerMin.toFixed(1)}%/m)` : "";
  let piNote = "Regime";
  if (modNum <= 45) piNote = "Inverter dolce ✓";
  else if (dModPerMin != null && dModPerMin <= -0.8) piNote = "PI in frenata ✓";
  else if (modNum >= 75 && buf >= targetLwt - 1.0) piNote = "PI spinge forte!";
  else if (lwt != null) piNote = `LWT ${lwt.toFixed(1)}°C`;

  return {
    mode: "heating",
    title: "🛡️ Anti-Stacco WO1C (7209)",
    badge,
    tone,
    pct: satPct,
    pctLabel: `${satPct}%`,
    satBufPct: Math.round(satBuf * 100),
    satEwtPct: Math.round(satEwt * 100),
    marginBuf,
    marginEwt,
    modNum,
    lastPeak,
    summary,
    chips: [
      {
        lbl: "Testa Puffer (BUF)",
        val: `${buf.toFixed(1)}° / ${cutoffBuf.toFixed(1)}°`,
        sub: `Marg. ${marginBuf >= 0 ? "+" : ""}${marginBuf.toFixed(1)} K (Tgt ${targetLwt.toFixed(1)}°)`,
      },
      {
        lbl: "Fondo / Ritorno (EWT)",
        val: ewt != null ? `${ewt.toFixed(1)}° / ${cutoffEwt.toFixed(1)}°` : "--",
        sub: marginEwt != null
          ? `Marg. ${marginEwt >= 0 ? "+" : ""}${marginEwt.toFixed(1)} K (${marginEwt > 0.6 ? "assorbe" : "saturo"})`
          : "Sonda ritorno n.d.",
      },
      {
        lbl: "Inverter & Trend PI",
        val: `Mod ${modNum.toFixed(0)}%${dModTxt}`,
        sub: `BUF ${dBufTxt} · ${piNote}`,
      },
    ],
  };
}

function wo1cTonePalette(tone) {
  switch (tone) {
    case "danger":  return { main: "#ef4444", glow: "rgba(239,68,68,0.45)", text: "#fca5a5" };
    case "warn":    return { main: "#f59e0b", glow: "rgba(245,158,11,0.40)", text: "#fde68a" };
    case "defrost": return { main: "#38bdf8", glow: "rgba(56,189,248,0.40)", text: "#bae6fd" };
    case "pause":   return { main: "#a78bfa", glow: "rgba(167,139,250,0.40)", text: "#ddd6fe" };
    case "safe":    return { main: "#10b981", glow: "rgba(16,185,129,0.40)", text: "#6ee7b7" };
    default:        return { main: "#64748b", glow: "rgba(100,116,139,0.25)", text: "#94a3b8" };
  }
}

function renderScadaArcDialInner(cx, cy, r, opts) {
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const pt = (rad, frac) => {
    const f = clamp(frac, 0, 1);
    const ang = Math.PI * (1.0 - f);
    return [cx + rad * Math.cos(ang), cy - rad * Math.sin(ang)];
  };
  const arc = (rad, f0, f1) => {
    const a0 = clamp(f0, 0, 0.998);
    const a1 = clamp(f1, a0 + 0.002, 1.0);
    const [x0, y0] = pt(rad, a0);
    const [x1, y1] = pt(rad, a1);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${rad.toFixed(2)} ${rad.toFixed(2)} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };

  const isStandby = opts.mode === "standby";
  const pal = wo1cTonePalette(opts.tone);
  const ghostPal = wo1cTonePalette(opts.ghostTone || "idle");
  const activeFrac = isStandby
    ? (opts.ghostPct != null ? clamp(opts.ghostPct / 100, 0.03, 1.0) : 0.04)
    : clamp((opts.pct || 0) / 100, 0.03, 1.0);

  const swOuter = Math.max(4.5, r * 0.15);
  const rInner = r - swOuter * 0.92;

  // Floating bezel pointer (leaves center 100% clear for digital readout!)
  const pAng = Math.PI * (1.0 - activeFrac);
  const cosA = Math.cos(pAng);
  const sinA = Math.sin(pAng);
  const pxTip = cx + (r - swOuter * 0.55) * cosA;
  const pyTip = cy - (r - swOuter * 0.55) * sinA;
  const baseR = r + swOuter * 0.62;
  const perp = 2.6;
  const bx1 = cx + baseR * cosA - perp * sinA;
  const by1 = cy - baseR * sinA - perp * cosA;
  const bx2 = cx + baseR * cosA + perp * sinA;
  const by2 = cy - baseR * sinA + perp * cosA;

  // Ticks at 0%, 39% (steady), 64% (warn), 85% (danger), 100%
  const ticks = [0, 0.39, 0.64, 0.85, 1.0].map(tf => {
    const [tx0, ty0] = pt(r - swOuter * 0.65, tf);
    const [tx1, ty1] = pt(r - swOuter * 1.25, tf);
    return `<line x1="${tx0.toFixed(1)}" y1="${ty0.toFixed(1)}" x2="${tx1.toFixed(1)}" y2="${ty1.toFixed(1)}" stroke="#475569" stroke-width="1.1" />`;
  }).join("");

  const ptrColor = isStandby ? (opts.ghostPct != null ? ghostPal.main : "#64748b") : "#f8fafc";
  const progColor = isStandby ? ghostPal.main : pal.main;
  const progDash = isStandby ? `stroke-dasharray="3,2" opacity="0.65"` : `opacity="0.95"`;
  const valFontSize = opts.valFontSize || Math.round(r * 0.36);
  const subFontSize = opts.subFontSize || Math.max(6.2, r * 0.16);

  return `
    <path d="${arc(r, 0, 1)}" fill="none" stroke="#09101d" stroke-width="${(swOuter + 2.5).toFixed(1)}" stroke-linecap="round" />
    <path d="${arc(r, 0.00, 0.625)}" fill="none" stroke="#10b981" stroke-opacity="${isStandby ? 0.22 : 0.34}" stroke-width="${swOuter.toFixed(1)}" />
    <path d="${arc(r, 0.640, 0.835)}" fill="none" stroke="#f59e0b" stroke-opacity="${isStandby ? 0.24 : 0.38}" stroke-width="${swOuter.toFixed(1)}" />
    <path d="${arc(r, 0.850, 1.000)}" fill="none" stroke="#ef4444" stroke-opacity="${isStandby ? 0.26 : 0.44}" stroke-width="${swOuter.toFixed(1)}" />
    ${ticks}
    ${(!isStandby || opts.ghostPct != null)
      ? `<path d="${arc(rInner, 0, activeFrac)}" fill="none" stroke="${progColor}" stroke-width="${Math.max(2.4, swOuter * 0.52).toFixed(1)}" stroke-linecap="round" ${progDash} />`
      : ""}
    <polygon points="${pxTip.toFixed(1)},${pyTip.toFixed(1)} ${bx1.toFixed(1)},${by1.toFixed(1)} ${bx2.toFixed(1)},${by2.toFixed(1)}"
             fill="${ptrColor}" stroke="#0f172a" stroke-width="0.8" />
    <text x="${cx}" y="${(cy - r * 0.28).toFixed(1)}" fill="${isStandby ? (opts.ghostPct != null ? ghostPal.text : '#94a3b8') : '#f8fafc'}"
          font-size="${valFontSize}" font-weight="800" text-anchor="middle">${opts.centerText || "--"}</text>
    <text x="${cx}" y="${(cy - 2).toFixed(1)}" fill="${isStandby ? '#64748b' : pal.text}"
          font-size="${subFontSize.toFixed(1)}" font-weight="700" text-anchor="middle">${opts.subText || ""}</text>
  `;
}

function buildWo1cTachometerSvg(info) {
  const isStby = info.mode === "standby";
  const centerText = isStby
    ? (info.lastPeak ? `${info.lastPeak.maxPct}%` : "OFF")
    : (info.pctLabel || `${info.pct || 0}%`);
  const subText = isStby
    ? (info.lastPeak ? "ULT. PICCO" : "STANDBY")
    : (info.mode === "defrost" ? "BPHE LWT" : (info.mode === "pause" ? "RIAVVIO 7203" : "SATUR. 7209"));
  return `
    <svg viewBox="0 0 118 70" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
      ${renderScadaArcDialInner(59, 61, 45, {
        mode: info.mode,
        tone: info.tone,
        pct: info.pct,
        ghostPct: info.ghostPct,
        ghostTone: info.ghostTone,
        centerText,
        subText,
        valFontSize: 15.5,
        subFontSize: 6.8,
      })}
    </svg>
  `;
}

function svgPufferAntiStaccoPortrait(x, y, w, h, g) {
  const info = g || { mode: "standby", tone: "idle", pct: 0 };
  const isStby = info.mode === "standby";
  const pal = wo1cTonePalette(isStby && info.lastPeak ? info.lastPeak.maxTone : info.tone);
  const borderCol = isStby ? "#334155" : pal.main;
  const centerTxt = isStby
    ? (info.lastPeak ? `${info.lastPeak.maxPct}%` : "STBY")
    : (info.pctLabel || `${info.pct || 0}%`);
  const subTxt = isStby ? (info.lastPeak ? "ULT.MAX" : "RIPOSO") : (info.mode === "defrost" ? "BPHE" : "7209");

  let pillTxt = "STANDBY";
  if (!isStby) {
    if (info.mode === "defrost") pillTxt = "DEFROST BPHE";
    else if (info.mode === "pause") pillTxt = "PAUSA 7203";
    else if (info.tone === "danger") pillTxt = "RISCHIO STACCO";
    else if (info.tone === "warn") pillTxt = "AVVICINAMENTO";
    else pillTxt = "MARGINE OK";
  } else if (info.lastPeak) {
    pillTxt = `ULT. ${info.lastPeak.shortTime}`;
  }

  const bPct = Math.max(4, Math.min(100, Number(info.satBufPct || 0)));
  const ePct = Math.max(4, Math.min(100, Number(info.satEwtPct || 0)));
  const bCol = bPct >= 82 ? "#ef4444" : (bPct >= 62 ? "#f59e0b" : "#10b981");
  const eCol = ePct >= 82 ? "#ef4444" : (ePct >= 62 ? "#f59e0b" : "#38bdf8");

  let mBufStr = "--";
  let mEwtStr = "--";
  let footLine = "Attivo in marcia (stacco su Testa +2.5K & Fondo ≥ Tgt)";
  if (!isStby && info.mode === "heating") {
    mBufStr = info.marginBuf != null ? `${info.marginBuf >= 0 ? "+" : ""}${info.marginBuf.toFixed(1)}K` : "--";
    mEwtStr = info.marginEwt != null ? `${info.marginEwt >= 0 ? "+" : ""}${info.marginEwt.toFixed(1)}K` : "--";
    footLine = `Margine stacco: Testa ${mBufStr} · Fondo ${mEwtStr} · Mod ${(info.modNum || 0).toFixed(0)}%`;
  } else if (!isStby && info.mode === "defrost") {
    mBufStr = info.marginBuf != null ? `${info.marginBuf >= 0 ? "+" : ""}${info.marginBuf.toFixed(1)}K` : "--";
    mEwtStr = info.marginEwt != null ? `${info.marginEwt >= 0 ? "+" : ""}${info.marginEwt.toFixed(1)}K` : "--";
    footLine = `Riserva BPHE: LWT ${mEwtStr} su 12° · BUF ${mBufStr} su 17°`;
  } else if (!isStby && info.mode === "pause") {
    mBufStr = info.marginBuf != null ? `${Math.max(0, info.marginBuf).toFixed(1)}K` : "--";
    footLine = `Attesa riavvio 7203 (−5.0K): mancano ${mBufStr}`;
  } else if (info.lastPeak) {
    mBufStr = `${info.lastPeak.marginBuf >= 0 ? "+" : ""}${info.lastPeak.marginBuf.toFixed(1)}K`;
    mEwtStr = info.lastPeak.marginEwt != null ? `${info.lastPeak.marginEwt >= 0 ? "+" : ""}${info.lastPeak.marginEwt.toFixed(1)}K` : "--";
    footLine = `Ult. ciclo (${info.lastPeak.timeStr}): picco ${info.lastPeak.maxPct}% (T ${mBufStr} / F ${mEwtStr})`;
  }

  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="10" fill="#0b1220" stroke="${borderCol}" stroke-width="1.3" />
      ${renderScadaArcDialInner(48, 56, 36, {
        mode: info.mode,
        tone: info.tone,
        pct: info.pct,
        ghostPct: info.ghostPct,
        ghostTone: info.ghostTone,
        centerText: centerTxt,
        subText: subTxt,
        valFontSize: 12.2,
        subFontSize: 5.8,
      })}
      <text x="98" y="15" fill="#cbd5e1" font-size="7.6" font-weight="800">🛡️ ANTI-STACCO WO1C</text>
      <rect x="${w - 86}" y="5" width="78" height="14" rx="7" fill="#162033" stroke="${pal.main}" stroke-width="0.9" />
      <text x="${w - 47}" y="14.5" fill="${pal.text}" font-size="6.5" font-weight="800" text-anchor="middle">${pillTxt}</text>

      <!-- Dual Head / Bottom Micro-Bars -->
      <text x="98" y="31" fill="#94a3b8" font-size="6.4" font-weight="700">TESTA</text>
      <rect x="126" y="25.5" width="66" height="6" rx="3" fill="#1e293b" />
      <rect x="126" y="25.5" width="${Math.round(0.66 * bPct)}" height="6" rx="3" fill="${bCol}" opacity="${isStby ? 0.55 : 0.95}" />

      <text x="202" y="31" fill="#94a3b8" font-size="6.4" font-weight="700">FONDO</text>
      <rect x="232" y="25.5" width="66" height="6" rx="3" fill="#1e293b" />
      <rect x="232" y="25.5" width="${Math.round(0.66 * ePct)}" height="6" rx="3" fill="${eCol}" opacity="${isStby ? 0.55 : 0.95}" />

      <!-- Zone threshold mini ruler -->
      <rect x="98" y="39" width="126" height="3.5" rx="1.7" fill="#10b981" opacity="0.32" />
      <rect x="226" y="39" width="40" height="3.5" rx="1.7" fill="#f59e0b" opacity="0.36" />
      <rect x="268" y="39" width="38" height="3.5" rx="1.7" fill="#ef4444" opacity="0.40" />

      <text x="98" y="56" fill="#94a3b8" font-size="6.7" font-weight="600">${footLine}</text>
    </g>
  `;
}

function svgPufferAntiStaccoLandscape(x, y, w, h, g) {
  const info = g || { mode: "standby", tone: "idle", pct: 0 };
  const isStby = info.mode === "standby";
  const pal = wo1cTonePalette(isStby && info.lastPeak ? info.lastPeak.maxTone : info.tone);
  const borderCol = isStby ? "#334155" : pal.main;
  const centerTxt = isStby
    ? (info.lastPeak ? `${info.lastPeak.maxPct}%` : "STBY")
    : (info.pctLabel || `${info.pct || 0}%`);
  const subTxt = isStby
    ? (info.lastPeak ? `ULT. ${info.lastPeak.shortTime}` : "STANDBY")
    : (info.mode === "defrost" ? "BPHE LWT" : (info.mode === "pause" ? "PAUSA 7203" : "SATUR. 7209"));

  const bPct = Math.max(4, Math.min(100, Number(info.satBufPct || 0)));
  const ePct = Math.max(4, Math.min(100, Number(info.satEwtPct || 0)));
  const bCol = bPct >= 82 ? "#ef4444" : (bPct >= 62 ? "#f59e0b" : "#10b981");
  const eCol = ePct >= 82 ? "#ef4444" : (ePct >= 62 ? "#f59e0b" : "#38bdf8");

  let mBufStr = "--";
  let mEwtStr = "--";
  if (!isStby && info.marginBuf != null) mBufStr = `${info.marginBuf >= 0 ? "+" : ""}${info.marginBuf.toFixed(1)}K`;
  else if (isStby && info.lastPeak) mBufStr = `${info.lastPeak.marginBuf >= 0 ? "+" : ""}${info.lastPeak.marginBuf.toFixed(1)}K`;

  if (!isStby && info.marginEwt != null) mEwtStr = `${info.marginEwt >= 0 ? "+" : ""}${info.marginEwt.toFixed(1)}K`;
  else if (isStby && info.lastPeak && info.lastPeak.marginEwt != null) mEwtStr = `${info.lastPeak.marginEwt >= 0 ? "+" : ""}${info.lastPeak.marginEwt.toFixed(1)}K`;

  const footerTxt = isStby
    ? (info.lastPeak ? `Ult. picco ${info.lastPeak.timeStr}` : "Attivo a PdC accesa")
    : (info.tone === "danger" ? "🔴 RISCHIO STACCO" : (info.tone === "warn" ? "🟡 IN AVVICINAMENTO" : "🟢 MARGINE SICURO"));

  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="10" fill="#0b1220" stroke="${borderCol}" stroke-width="1.3" />
      <text x="${w / 2}" y="14" fill="#cbd5e1" font-size="7.4" font-weight="800" text-anchor="middle">🛡️ ANTI-STACCO 7209</text>
      ${renderScadaArcDialInner(w / 2, 74, 41, {
        mode: info.mode,
        tone: info.tone,
        pct: info.pct,
        ghostPct: info.ghostPct,
        ghostTone: info.ghostTone,
        centerText: centerTxt,
        subText: subTxt,
        valFontSize: 13.5,
        subFontSize: 6.2,
      })}
      <text x="8" y="95" fill="#94a3b8" font-size="6.4" font-weight="700">TESTA</text>
      <rect x="38" y="89.5" width="54" height="5.5" rx="2.7" fill="#1e293b" />
      <rect x="38" y="89.5" width="${Math.round(0.54 * bPct)}" height="5.5" rx="2.7" fill="${bCol}" opacity="${isStby ? 0.55 : 0.95}" />
      <text x="${w - 7}" y="95" fill="#cbd5e1" font-size="6.4" font-weight="700" text-anchor="end">${mBufStr}</text>

      <text x="8" y="113" fill="#94a3b8" font-size="6.4" font-weight="700">FONDO</text>
      <rect x="38" y="107.5" width="54" height="5.5" rx="2.7" fill="#1e293b" />
      <rect x="38" y="107.5" width="${Math.round(0.54 * ePct)}" height="5.5" rx="2.7" fill="${eCol}" opacity="${isStby ? 0.55 : 0.95}" />
      <text x="${w - 7}" y="113" fill="#cbd5e1" font-size="6.4" font-weight="700" text-anchor="end">${mEwtStr}</text>

      <line x1="10" y1="126" x2="${w - 10}" y2="126" stroke="#1e293b" stroke-width="1" />
      <text x="${w / 2}" y="141" fill="${isStby ? '#94a3b8' : pal.text}" font-size="6.8" font-weight="700" text-anchor="middle">${footerTxt}</text>
    </g>
  `;
}

function renderWo1cCutoffMargin(sample) {
  const card = document.getElementById("wo1cCutoffMarginCard");
  if (!card) return;
  const samplesList = (typeof state !== "undefined" && Array.isArray(state.samples)) ? state.samples : [];
  const info = computeWo1cCutoffMargin(sample, samplesList);

  const toggleEl = document.getElementById("wo1cCockpitToggle");
  const dialEl = document.getElementById("wo1cGaugeDialBox");
  const titleEl = document.getElementById("wo1cMarginTitle");
  const badgeEl = document.getElementById("wo1cMarginBadge");
  const markerEl = document.getElementById("wo1cZoneMarker");
  const bodyEl = document.getElementById("wo1cMarginBody");
  const sumEl = document.getElementById("wo1cMarginSummary");

  if (toggleEl && !toggleEl.dataset.boundToggle) {
    toggleEl.dataset.boundToggle = "1";
    const onToggle = (ev) => {
      if (ev.target && ev.target.closest && ev.target.closest(".help-info-btn")) return;
      const b = document.getElementById("wo1cMarginBody");
      if (!b) return;
      const isHidden = b.style.display === "none";
      b.style.display = isHidden ? "" : "none";
      card.dataset.userToggled = isHidden ? "open" : "closed";
    };
    toggleEl.addEventListener("click", onToggle);
    toggleEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        onToggle(ev);
      }
    });
  }

  const isStandby = info.mode === "standby";
  card.className = `wo1c-margin-card tone-${info.tone || "idle"}${isStandby ? " is-standby" : ""}`;
  if (titleEl) titleEl.textContent = info.title || "🛡️ Anti-Stacco WO1C (7209)";
  if (badgeEl) {
    badgeEl.textContent = info.badge || "STANDBY";
    badgeEl.className = `wo1c-margin-badge tone-${isStandby && info.lastPeak ? info.lastPeak.maxTone : (info.tone || "idle")}`;
  }
  if (dialEl) {
    dialEl.innerHTML = buildWo1cTachometerSvg(info);
  }
  if (markerEl) {
    const markerPct = isStandby
      ? (info.lastPeak ? info.lastPeak.maxPct : 4)
      : Math.max(4, Math.min(98, Number(info.pct || 0)));
    markerEl.style.left = `${markerPct}%`;
    markerEl.style.opacity = isStandby ? (info.lastPeak ? "0.65" : "0.35") : "1";
  }
  if (sumEl) sumEl.textContent = info.summary || "--";

  if (bodyEl) {
    if (card.dataset.lastMode !== info.mode) {
      card.dataset.lastMode = info.mode;
      delete card.dataset.userToggled;
    }
    if (card.dataset.userToggled === "open") {
      bodyEl.style.display = "";
    } else if (card.dataset.userToggled === "closed") {
      bodyEl.style.display = "none";
    } else {
      bodyEl.style.display = isStandby ? "none" : "";
    }
  }

  const c = Array.isArray(info.chips) ? info.chips : [];
  const ids = [
    ["wo1cChipBufLbl", "wo1cChipBuf", "wo1cChipBufSub"],
    ["wo1cChipEwtLbl", "wo1cChipEwt", "wo1cChipEwtSub"],
    ["wo1cChipModLbl", "wo1cChipMod", "wo1cChipModSub"],
  ];
  ids.forEach((tri, idx) => {
    const item = c[idx];
    if (!item) return;
    const eL = document.getElementById(tri[0]);
    const eV = document.getElementById(tri[1]);
    const eS = document.getElementById(tri[2]);
    if (eL) eL.textContent = item.lbl;
    if (eV) eV.textContent = item.val;
    if (eS) eS.textContent = item.sub;
  });
}

window.computeWo1cCutoffMargin = computeWo1cCutoffMargin;
window.renderWo1cCutoffMargin = renderWo1cCutoffMargin;
