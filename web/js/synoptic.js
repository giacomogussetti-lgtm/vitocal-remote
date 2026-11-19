/**
 * Industrial SCADA Synoptic Canvas (SVG) for Vitocal 111-S & BTicino Smarther.
 * Renders hydraulic schematics, thermodynamic sensors, and animated components.
 */

function renderSynoptic(data) {
  const svg = document.getElementById("synopticSvg");
  if (!svg) return;

  const d = data || {};

  // Formatter helper
  const val = (v, unit = "°C", def = "--") => {
    if (v === null || v === undefined) return def;
    return typeof v === "number" ? `${v.toFixed(1)} ${unit}` : `${v} ${unit}`;
  };

  const oat = val(d.external_temp_c);
  const dhw = val(d.dhw_storage_temp_c);
  const supply = val(d.pdc_supply_temp_c);
  const ret = val(d.pdc_return_temp_c);
  const buffer = val(d.buffer_temp_c);
  const indoor = val(d.indoor_temp_bticino_c);
  const setpoint = val(d.indoor_setpoint_bticino_c);
  const humidity = d.humidity_percent != null ? `${d.humidity_percent.toFixed(0)} %` : "-- %";
  
  const compActive = (d.compressor_active === 1) || ((d.compressor_modulation_percent || 0) > 0);
  const compMod = (d.compressor_modulation_percent != null) ? `${d.compressor_modulation_percent.toFixed(0)} %` : "0 %";
  const compColor = compActive ? "#10b981" : "#64748b";
  const compStatusText = compActive ? `ATTIVO (${compMod})` : "SPENTO";

  const pumpActive = d.grundfos_pump_active === 1;
  const pumpColor = pumpActive ? "#10b981" : "#334155";
  const pumpBorder = pumpActive ? "#ffffff" : "#64748b";
  const pumpStatusText = pumpActive ? "ACCESA (Radiante)" : "SPENTA (Standby)";

  const gasPress = d.hot_gas_pressure_bar != null ? `${d.hot_gas_pressure_bar.toFixed(1)} bar` : "-- bar";
  const hotGas = val(d.hot_gas_temp_c);
  const liqGas = val(d.liquid_gas_temp_c);
  const sucGas = val(d.suction_gas_temp_c);
  const primPump = d.primary_pump_rotation_percent != null ? `${d.primary_pump_rotation_percent.toFixed(0)} %` : "Attivo";
  const copH = d.cop_heating != null ? d.cop_heating.toFixed(1) : "--";
  const copTot = d.cop_total != null ? d.cop_total.toFixed(1) : "--";
  const compHours = d.compressor_hours != null ? `${d.compressor_hours.toFixed(0)} h` : "-- h";
  const compStarts = d.compressor_starts != null ? `${d.compressor_starts}` : "--";
  const slope = d.heating_curve_slope != null ? d.heating_curve_slope.toFixed(1) : "0.6";
  const shift = d.heating_curve_shift != null ? d.heating_curve_shift.toFixed(0) : "0";
  const prog = (d.active_program || "standby").toUpperCase();
  const mode = d.active_mode || "dhwAndHeating";

  // Coordinates
  const pdcW = 385, pdcH = 520, pdcX = 30, pdcY = 40;
  const pufferW = 160, pufferH = 440, pufferX = 540, pufferY = 80;
  const houseW = 430, houseH = 520, houseX = 840, houseY = 40;
  
  const pipeSupplyY = 150;
  const pipeReturnY = 450;
  const grundfosX = (pufferX + pufferW + houseX) / 2; // ~770

  svg.innerHTML = `
    <defs>
      <!-- Gradients -->
      <linearGradient id="pufferGrad" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#1e293b" />
        <stop offset="50%" stop-color="#0f172a" />
        <stop offset="100%" stop-color="#1e293b" />
      </linearGradient>

      <!-- Animated Water Dash Pattern -->
      <style>
        .flow-hot {
          stroke: #ef4444;
          stroke-width: 6;
          stroke-linecap: round;
          ${compActive ? 'stroke-dasharray: 12, 10; animation: flowHot 1s linear infinite;' : ''}
        }
        .flow-cold {
          stroke: #3b82f6;
          stroke-width: 6;
          stroke-linecap: round;
          ${compActive ? 'stroke-dasharray: 12, 10; animation: flowCold 1s linear infinite;' : ''}
        }
        .flow-sec-hot {
          stroke: #ef4444;
          stroke-width: 6;
          stroke-linecap: round;
          ${pumpActive ? 'stroke-dasharray: 12, 10; animation: flowHot 1s linear infinite;' : ''}
        }
        .flow-sec-cold {
          stroke: #3b82f6;
          stroke-width: 6;
          stroke-linecap: round;
          ${pumpActive ? 'stroke-dasharray: 12, 10; animation: flowCold 1s linear infinite;' : ''}
        }
        @keyframes flowHot {
          from { stroke-dashoffset: 22; }
          to { stroke-dashoffset: 0; }
        }
        @keyframes flowCold {
          from { stroke-dashoffset: 0; }
          to { stroke-dashoffset: 22; }
        }
        .pump-rotate {
          transform-origin: ${grundfosX}px ${pipeSupplyY}px;
          ${pumpActive ? 'animation: spinPump 1.2s linear infinite;' : ''}
        }
        @keyframes spinPump {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      </style>
    </defs>

    <!-- Background -->
    <rect x="0" y="0" width="1300" height="600" fill="#0c1322" rx="10" />

    <!-- 1. PIPING CONNECTIONS -->
    <!-- Primary Supply (PdC -> Puffer) -->
    <line x1="${pdcX + pdcW}" y1="${pipeSupplyY}" x2="${pufferX}" y2="${pipeSupplyY}" class="flow-hot" />
    <!-- Primary Return (Puffer -> PdC) -->
    <line x1="${pufferX}" y1="${pipeReturnY}" x2="${pdcX + pdcW}" y2="${pipeReturnY}" class="flow-cold" />

    <!-- Secondary Supply (Puffer -> Grundfos -> House) -->
    <line x1="${pufferX + pufferW}" y1="${pipeSupplyY}" x2="${grundfosX - 22}" y2="${pipeSupplyY}" class="flow-sec-hot" />
    <line x1="${grundfosX + 22}" y1="${pipeSupplyY}" x2="${houseX}" y2="${pipeSupplyY}" class="flow-sec-hot" />
    <!-- Secondary Return (House -> Puffer) -->
    <line x1="${houseX}" y1="${pipeReturnY}" x2="${pufferX + pufferW}" y2="${pipeReturnY}" class="flow-sec-cold" />

    <!-- PIPE SENSOR TAGS (Centered between blocks) -->
    <!-- T Mandata PdC -->
    <g transform="translate(${(pdcX + pdcW + pufferX)/2 - 60}, ${pipeSupplyY - 44})">
      <rect x="0" y="0" width="120" height="36" rx="6" fill="#161f30" stroke="#ef4444" stroke-width="1.5" />
      <text x="60" y="14" fill="#94a3b8" font-size="9" font-weight="600" text-anchor="middle">T MANDATA PDC</text>
      <text x="60" y="29" fill="#ef4444" font-size="12" font-weight="700" text-anchor="middle">${supply}</text>
    </g>

    <!-- T Ritorno PdC -->
    <g transform="translate(${(pdcX + pdcW + pufferX)/2 - 60}, ${pipeReturnY + 12})">
      <rect x="0" y="0" width="120" height="36" rx="6" fill="#161f30" stroke="#3b82f6" stroke-width="1.5" />
      <text x="60" y="14" fill="#94a3b8" font-size="9" font-weight="600" text-anchor="middle">T RITORNO PDC</text>
      <text x="60" y="29" fill="#38bdf8" font-size="12" font-weight="700" text-anchor="middle">${ret}</text>
    </g>

    <!-- 2. ZONE A: VITOCAL 111-S (Pompa di Calore) -->
    <rect x="${pdcX}" y="${pdcY}" width="${pdcW}" height="${pdcH}" rx="12" fill="#161f30" stroke="#38bdf8" stroke-width="2" />
    <text x="${pdcX + 16}" y="${pdcY + 26}" fill="#38bdf8" font-size="12" font-weight="700" letter-spacing="0.5">POMPA DI CALORE VIESSMANN (Vitocal 111-S)</text>

    <!-- Badges Grid Inside Zone A -->
    ${svgBadge(pdcX + 14, pdcY + 40, 172, 48, "Sonda Esterna OAT", oat, "#f59e0b")}
    ${svgBadge(pdcX + 198, pdcY + 40, 172, 48, "Bollitore ACS 220L", dhw, "#c084fc")}

    ${svgBadge(pdcX + 14, pdcY + 94, 172, 48, "Compressore Inverter", compStatusText, compColor)}
    ${svgBadge(pdcX + 198, pdcY + 94, 172, 48, "Pressione Gas Caldo", gasPress, "#ec4899")}

    ${svgBadge(pdcX + 14, pdcY + 148, 172, 48, "T Gas Caldo", hotGas, "#f87171")}
    ${svgBadge(pdcX + 198, pdcY + 148, 172, 48, "T Gas Liquido Frigo", liqGas, "#38bdf8")}

    ${svgBadge(pdcX + 14, pdcY + 202, 172, 48, "T Gas Aspirazione", sucGas, "#93c5fd")}
    ${svgBadge(pdcX + 198, pdcY + 202, 172, 48, "Circolatore Primario", primPump, "#34d399")}

    ${svgBadge(pdcX + 14, pdcY + 256, 172, 48, "COP Riscaldamento", compActive ? copH : "--", "#10b981")}
    ${svgBadge(pdcX + 198, pdcY + 256, 172, 48, "COP Totale Macchina", compActive ? copTot : "--", "#6ee7b7")}

    ${svgBadge(pdcX + 14, pdcY + 310, 172, 48, "Ore Compressore", compHours, "#e2e8f0")}
    ${svgBadge(pdcX + 198, pdcY + 310, 172, 48, "Avvii Totali", compStarts, "#e2e8f0")}

    ${svgBadge(pdcX + 14, pdcY + 364, 172, 48, "Curva Climatica", `Slp ${slope} | Shf ${shift}`, "#60a5fa")}
    ${svgBadge(pdcX + 198, pdcY + 364, 172, 48, "Programma Attivo", prog, "#a78bfa")}

    <!-- Bottom Strip in Zone A -->
    <rect x="${pdcX + 14}" y="${pdcY + 460}" width="${pdcW - 28}" height="32" rx="6" fill="#0f172a" stroke="#334155" />
    <text x="${pdcX + pdcW / 2}" y="${pdcY + 481}" fill="#94a3b8" font-size="10" font-weight="600" text-anchor="middle">
      MODO: ${mode}  |  CURVA: ${slope}/${shift}  |  WO1C CU401B
    </text>

    <!-- 3. ZONE B: PUFFER INERZIALE 200L -->
    <rect x="${pufferX}" y="${pufferY}" width="${pufferW}" height="${pufferH}" rx="30" fill="url(#pufferGrad)" stroke="#f59e0b" stroke-width="2.5" />
    <text x="${pufferX + pufferW / 2}" y="${pufferY + 36}" fill="#f59e0b" font-size="13" font-weight="700" text-anchor="middle">PUFFER 200 L</text>
    <text x="${pufferX + pufferW / 2}" y="${pufferY + 54}" fill="#94a3b8" font-size="9" text-anchor="middle">(Disaccoppiatore)</text>

    <!-- Sonda Accumulo Puffer Badge (Center of tank) -->
    ${svgBadge(pufferX + 15, pufferY + 180, 130, 56, "Sonda Accumulo 200L", buffer, "#f59e0b")}

    <text x="${pufferX + pufferW / 2}" y="${pufferY + pufferH - 30}" fill="#64748b" font-size="9" text-anchor="middle">Disaccoppiatore Idraulico</text>
    <text x="${pufferX + pufferW / 2}" y="${pufferY + pufferH - 16}" fill="#64748b" font-size="9" text-anchor="middle">Primario / Secondario</text>

    <!-- 4. CIRCOLATORE GRUNDFOS (Rilancio Secondario) -->
    <g>
      <circle cx="${grundfosX}" cy="${pipeSupplyY}" r="24" fill="${pumpColor}" stroke="${pumpBorder}" stroke-width="2.5" />
      <g class="pump-rotate">
        <line x1="${grundfosX - 14}" y1="${pipeSupplyY}" x2="${grundfosX + 14}" y2="${pipeSupplyY}" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" />
        <line x1="${grundfosX}" y1="${pipeSupplyY - 14}" x2="${grundfosX}" y2="${pipeSupplyY + 14}" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" />
      </g>
      <circle cx="${grundfosX}" cy="${pipeSupplyY}" r="7" fill="#0f172a" stroke="#ffffff" stroke-width="1.5" />
      <text x="${grundfosX}" y="${pipeSupplyY - 34}" fill="#94a3b8" font-size="10" font-weight="700" text-anchor="middle">Circolatore Grundfos</text>
      <text x="${grundfosX}" y="${pipeSupplyY + 44}" fill="${pumpActive ? '#10b981' : '#94a3b8'}" font-size="10" font-weight="700" text-anchor="middle">${pumpStatusText}</text>
    </g>

    <!-- 5. ZONE C: ABITAZIONE & TERMOSTATO BTICINO -->
    <rect x="${houseX}" y="${houseY}" width="${houseW}" height="${houseH}" rx="12" fill="#161f30" stroke="#10b981" stroke-width="2" />
    <text x="${houseX + 16}" y="${houseY + 26}" fill="#10b981" font-size="12" font-weight="700" letter-spacing="0.5">ABITAZIONE (Massetto Radiante a Pavimento)</text>

    <!-- Underfloor Radiant Serpentines Visual Symbol -->
    <path d="M ${houseX + 24} ${houseY + 50} 
             L ${houseX + houseW - 30} ${houseY + 50} 
             Q ${houseX + houseW - 16} ${houseY + 60} ${houseX + houseW - 30} ${houseY + 70} 
             L ${houseX + 30} ${houseY + 70} 
             Q ${houseX + 16} ${houseY + 80} ${houseX + 30} ${houseY + 90} 
             L ${houseX + houseW - 30} ${houseY + 90} 
             Q ${houseX + houseW - 16} ${houseY + 100} ${houseX + houseW - 30} ${houseY + 110} 
             L ${houseX + 24} ${houseY + 110}" 
          fill="none" stroke="${pumpActive ? '#ef4444' : '#334155'}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />

    <!-- BTicino Smarther Card -->
    <rect x="${houseX + 16}" y="${houseY + 140}" width="${houseW - 32}" height="320" rx="10" fill="#0f172a" stroke="#10b981" stroke-width="1.5" />
    <text x="${houseX + 32}" y="${houseY + 168}" fill="#38bdf8" font-size="12" font-weight="700">TERMOSTATO BTICINO SMARTHER (Corridoio)</text>

    ${svgBadge(houseX + 30, houseY + 190, 175, 52, "Temperatura Ambiente", indoor, "#10b981")}
    ${svgBadge(houseX + 225, houseY + 190, 175, 52, "Umidità Relativa", humidity, "#60a5fa")}

    ${svgBadge(houseX + 30, houseY + 254, 175, 52, "Setpoint Impostato", setpoint, "#eab308")}
    ${svgBadge(houseX + 225, houseY + 254, 175, 52, "Modalità Operativa", (d.active_preset || "MANUALE").toUpperCase(), "#c084fc")}

    <!-- Relay Status Card -->
    <rect x="${houseX + 30}" y="${houseY + 322}" width="${houseW - 60}" height="110" rx="8" fill="#161f30" stroke="${pumpActive ? '#10b981' : '#334155'}" stroke-width="1.5" />
    <text x="${houseX + 46}" y="${houseY + 348}" fill="#94a3b8" font-size="11" font-weight="600">Consenso Relè Pompa Pavimento:</text>
    <text x="${houseX + 46}" y="${houseY + 378}" fill="${pumpActive ? '#10b981' : '#94a3b8'}" font-size="16" font-weight="700">
      ${pumpActive ? "⚡ CONSENSO ATTIVO (Pompa in moto)" : "⏸ NESSUNA RICHIESTA (Rilancio spento)"}
    </text>
    <text x="${houseX + 46}" y="${houseY + 410}" fill="#64748b" font-size="10">
      ${pumpActive ? "Il calore dal Puffer viene trasferito al pavimento radiante" : "Puffer termicamente disaccoppiato dall'abitazione"}
    </text>
  `;
}

function svgBadge(x, y, w, h, label, value, color) {
  return `
    <g transform="translate(${x}, ${y})">
      <rect x="0" y="0" width="${w}" height="${h}" rx="6" fill="#0f172a" stroke="#334155" stroke-width="1" />
      <text x="10" y="15" fill="#94a3b8" font-size="8.5" font-weight="600" text-anchor="start">${label.toUpperCase()}</text>
      <text x="10" y="37" fill="${color}" font-size="13.5" font-weight="700" text-anchor="start">${value}</text>
    </g>
  `;
}
