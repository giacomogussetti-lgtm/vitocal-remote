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
    svg.setAttribute("viewBox", "0 0 420 850");
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
  const deltaTarget = (inNum != null && spNum != null) ? (inNum - spNum) : null;

  const rod1s = d.heating_rod_level1_s != null ? Number(d.heating_rod_level1_s) : null;
  const rod2s = d.heating_rod_level2_s != null ? Number(d.heating_rod_level2_s) : null;
  const rod1h = rod1s != null ? (rod1s / 3600.0).toFixed(1) : "--";
  const rod2h = rod2s != null ? (rod2s / 3600.0).toFixed(1) : "--";
  const rodHoursStr = (rod1s != null || rod2s != null) ? `${rod1h}h / ${rod2h}h` : "--";
  let rodActive = false;
  if (typeof state !== "undefined" && Array.isArray(state.samples) && state.samples.length >= 2) {
    const prev = state.samples[state.samples.length - 2];
    if (prev) {
      if (rod1s != null && prev.heating_rod_level1_s != null && rod1s > Number(prev.heating_rod_level1_s)) rodActive = true;
      if (rod2s != null && prev.heating_rod_level2_s != null && rod2s > Number(prev.heating_rod_level2_s)) rodActive = true;
    }
  }

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
    rodHoursStr,
    rodStatusShort: rodActive ? `⚡ ON (${rodHoursStr})` : `OFF (${rodHoursStr})`,
    rodColor: rodActive ? "#fb7185" : "#94a3b8",
    rodBorder: rodActive ? "#ef4444" : "#334155",
    pufferTopColor,
  };
}

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
// PORTRAIT LAYOUT (420 x 850) — Zero Horizontal Scroll on Smartphones
// =========================================================================
function renderSynopticPortrait(m) {
  return `
    <rect x="0" y="0" width="420" height="850" fill="#0c1322" rx="10" />

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

    <g transform="translate(174, 292)">
      <rect x="0" y="0" width="72" height="36" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="36" y="13" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">ΔT PRIM.</text>
      <text x="36" y="29" fill="#f8fafc" font-size="11" font-weight="700" text-anchor="middle">${m.deltaPrimStr}</text>
    </g>

    <line x1="125" y1="376" x2="152" y2="376" stroke="${m.rodBorder}" stroke-width="1.3" stroke-dasharray="3,2" />
    ${svgBackupHeaterBlock(152, 340, 122, 54, m)}

    <g transform="translate(312, 326)">
      <rect x="0" y="0" width="96" height="36" rx="6" fill="#161f30" stroke="#3b82f6" stroke-width="1.3" />
      <text x="48" y="13" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">T RITORNO PDC</text>
      <text x="48" y="29" fill="#38bdf8" font-size="12" font-weight="800" text-anchor="middle">${m.ret}</text>
    </g>

    <!-- 4. PUFFER INERZIALE 200 L -->
    <rect x="66" y="404" width="288" height="104" rx="26" fill="url(#pufferGrad)" stroke="#f59e0b" stroke-width="2.4" />
    <text x="210" y="425" fill="#f59e0b" font-size="12" font-weight="800" text-anchor="middle">PUFFER INERZIALE 200 L</text>
    <text x="210" y="439" fill="#94a3b8" font-size="8.5" text-anchor="middle">Disaccoppiatore Idraulico Primario / Secondario</text>
    <rect x="120" y="448" width="180" height="48" rx="8" fill="#0f172a" stroke="#f59e0b" stroke-width="1.3" />
    <text x="210" y="464" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">🌡️ SONDA ACCUMULO SUPERIORE</text>
    <text x="210" y="487" fill="#fbbf24" font-size="17" font-weight="800" text-anchor="middle">${m.buffer}</text>

    <!-- 5. CIRCUITO SECONDARIO VERTICALE (Puffer <-> Casetta + Grundfos) -->
    <!-- Supply runs Puffer(125,508) -> Grundfos(125,550) -> bend at y=584 -> x=50 -> floor slab y=792 -->
    <path d="M 125 508 L 125 584 L 50 584 L 50 792" class="flow-sec-hot" />
    ${svgArrow(125, 520, 0, 1, m.pumpActive ? "#ef4444" : "#7f1d1d")}
    ${svgArrow(50, 695, 0, 1, m.pumpActive ? "#ef4444" : "#7f1d1d")}

    <!-- Return runs floor slab(370,792) -> y=584 -> x=295 -> Puffer(295,508) -->
    <path d="M 370 792 L 370 584 L 295 584 L 295 508" class="flow-sec-cold" />
    ${svgArrow(370, 695, 0, -1, m.pumpActive ? "#3b82f6" : "#1e40af")}
    ${svgArrow(295, 520, 0, -1, m.pumpActive ? "#3b82f6" : "#1e40af")}

    <!-- Grundfos Circulator on Secondary Supply -->
    ${svgCirculator(125, 550, 20, m.pumpActive, "spin-gf", m.pumpColor)}

    <g transform="translate(12, 530)">
      <rect x="0" y="0" width="90" height="40" rx="6" fill="#161f30" stroke="${m.pumpActive ? '#10b981' : '#475569'}" stroke-width="1.3" />
      <text x="45" y="14" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">GRUNDFOS</text>
      <text x="45" y="31" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="11" font-weight="800" text-anchor="middle">${m.pumpStatusShort}</text>
    </g>

    <g transform="translate(166, 532)">
      <rect x="0" y="0" width="88" height="36" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="44" y="13" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">CONS. RELÈ</text>
      <text x="44" y="28" fill="${m.pumpActive ? '#10b981' : '#94a3b8'}" font-size="10.5" font-weight="800" text-anchor="middle">${m.pumpActive ? "⚡ ATTIVO" : "⏸ APERTO"}</text>
    </g>

    <g transform="translate(314, 530)">
      <rect x="0" y="0" width="94" height="40" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="47" y="14" fill="#94a3b8" font-size="7.5" font-weight="700" text-anchor="middle">RIT. PAVIM.</text>
      <text x="47" y="29" fill="#64748b" font-size="8.5" font-weight="600" text-anchor="middle">Sonda assente</text>
    </g>

    <!-- 6. CASETTA STILIZZATA (Aria Esterna vs Aria Interna + Pavimento Radiante) -->
    <!-- Pitched House Roof & Room Body -->
    <polygon points="210,626 20,674 400,674" fill="#1b283f" stroke="#10b981" stroke-width="2.2" stroke-linejoin="round" />
    <text x="210" y="662" fill="#10b981" font-size="10.5" font-weight="800" text-anchor="middle" letter-spacing="0.4">🏠 ABITAZIONE (Massetto Radiante)</text>

    <!-- Outdoor badge cleanly in open air between roof slope and return pipe -->
    <g transform="translate(244, 594)">
      <rect x="0" y="0" width="114" height="30" rx="8" fill="#0c1e36" stroke="#38bdf8" stroke-width="1.2" stroke-dasharray="4,3" />
      <text x="57" y="12" fill="#94a3b8" font-size="7.2" font-weight="700" text-anchor="middle">☁️ ARIA FUORI CASA</text>
      <text x="57" y="25" fill="#38bdf8" font-size="10.5" font-weight="800" text-anchor="middle">${m.oat}</text>
    </g>

    <rect x="34" y="674" width="352" height="166" rx="8" fill="#131c2e" stroke="#10b981" stroke-width="2" />

    <!-- Wall-Mounted BTicino Smarther Thermostat & Indoor Air Card -->
    <rect x="64" y="684" width="292" height="88" rx="8" fill="#0f172a" stroke="#334155" stroke-width="1.2" />
    ${svgThermostatWallIcon(78, 698)}
    <text x="118" y="700" fill="#38bdf8" font-size="9" font-weight="800">TERMOSTATO BTICINO (Corridoio)</text>
    <text x="118" y="722" fill="#10b981" font-size="19" font-weight="800">${m.indoor}</text>
    <text x="195" y="721" fill="#94a3b8" font-size="9" font-weight="600">Aria Interna</text>

    <text x="80" y="745" fill="#94a3b8" font-size="8.5" font-weight="700">SETPOINT:</text>
    <text x="132" y="745" fill="#eab308" font-size="11.5" font-weight="800">${m.setpoint}</text>

    <text x="188" y="745" fill="#94a3b8" font-size="8.5" font-weight="700">UMIDITÀ:</text>
    <text x="234" y="745" fill="#60a5fa" font-size="11.5" font-weight="800">${m.humidity}</text>

    <text x="284" y="745" fill="#94a3b8" font-size="8.5" font-weight="700">ΔT:</text>
    <text x="303" y="745" fill="#e2e8f0" font-size="10.5" font-weight="700">${m.deltaTargetStr}</text>

    <text x="210" y="764" fill="${m.pumpActive ? '#6ee7b7' : '#64748b'}" font-size="8.5" font-weight="700" text-anchor="middle">
      ${m.pumpActive ? "🔥 Rilancio attivo dal Puffer al massetto radiante" : "⏸ Rilancio spento — Puffer disaccoppiato dalla casa"}
    </text>

    <!-- Floor Slab & Radiant Serpentines Connected to Pipes at x=50 and x=370 -->
    <rect x="44" y="778" width="332" height="54" rx="6" fill="#0b1120" stroke="#334155" stroke-width="1" />
    <text x="210" y="790" fill="#64748b" font-size="7.5" font-weight="700" text-anchor="middle">SERPENTINA PAVIMENTO RADIANTE</text>
    <path d="M 50 792
             L 50 798
             L 354 798
             Q 364 804 354 810
             L 66 810
             Q 56 816 66 822
             L 370 822
             L 370 792"
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

    <g transform="translate(442, 246)">
      <rect x="0" y="0" width="86" height="38" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="43" y="14" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">ΔT PRIMARIO</text>
      <text x="43" y="30" fill="#f8fafc" font-size="11.5" font-weight="700" text-anchor="middle">${m.deltaPrimStr}</text>
    </g>

    ${svgBackupHeaterBlock(416, 304, 138, 58, m)}

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

    <!-- 3. ZONE B: PUFFER INERZIALE 200 L -->
    <rect x="570" y="102" width="150" height="414" rx="28" fill="url(#pufferGrad)" stroke="#f59e0b" stroke-width="2.5" />
    <text x="645" y="138" fill="#f59e0b" font-size="13" font-weight="800" text-anchor="middle">PUFFER 200 L</text>
    <text x="645" y="155" fill="#94a3b8" font-size="9" text-anchor="middle">(Disaccoppiatore)</text>

    <rect x="582" y="266" width="126" height="62" rx="8" fill="#0f172a" stroke="#f59e0b" stroke-width="1.3" />
    <text x="645" y="286" fill="#94a3b8" font-size="8" font-weight="700" text-anchor="middle">SONDA ACCUMULO</text>
    <text x="645" y="314" fill="#fbbf24" font-size="17" font-weight="800" text-anchor="middle">${m.buffer}</text>

    <text x="645" y="484" fill="#64748b" font-size="8.5" text-anchor="middle">Disaccoppiatore Idraulico</text>
    <text x="645" y="498" fill="#64748b" font-size="8.5" text-anchor="middle">Primario / Secondario</text>

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
    ${svgBadge(936, 260, 132, 50, "Setpoint Target", m.setpoint, "#eab308")}
    ${svgBadge(1078, 260, 132, 50, "Modalità", m.thermostatMode, "#c084fc")}

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
  const cx = x + w / 2;
  const coilCol = m.rodActive ? "#ef4444" : "#64748b";
  const bg = m.rodActive ? "#2a1219" : "#0f172a";
  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="7" fill="${bg}" stroke="${m.rodBorder}" stroke-width="${m.rodActive ? 1.7 : 1.1}" />
      <text x="${w / 2}" y="13" fill="#94a3b8" font-size="7.4" font-weight="700" text-anchor="middle">RESISTENZA BACKUP</text>
      <path d="M 14 27 L 22 21 L 28 33 L 34 21 L 40 33 L 46 21 L 52 27" fill="none" stroke="${coilCol}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      <text x="${w - 8}" y="30" fill="${m.rodActive ? '#fbbf24' : '#94a3b8'}" font-size="8.2" font-weight="800" text-anchor="end">S1/S2</text>
      <text x="${w / 2}" y="${h - 7}" fill="${m.rodColor}" font-size="9.2" font-weight="800" text-anchor="middle">${m.rodStatusShort}</text>
    </g>
  `;
}
