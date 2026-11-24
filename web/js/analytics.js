/**
 * Client-Side Analytics Engine for Vitocal Remote Mobile PWA.
 * Computes compressor starts, cycle durations, inverter modulation quality,
 * electrical consumption (kWh/€), and anti-frost safety margin for the last X hours.
 */

function computePeriodAnalytics(samples, hoursRequested = 24, costPerKwh = 0.25, freezeThreshold = 5.0) {
  if (!samples || samples.length === 0) {
    return getEmptyAnalytics(hoursRequested);
  }

  // 1. Filter samples within requested window (relative to latest sample)
  const valid = [];
  for (const s of samples) {
    if (!s.timestamp_utc) continue;
    const d = new Date(s.timestamp_utc);
    if (!isNaN(d.getTime())) {
      valid.push({ d, s });
    }
  }

  if (valid.length === 0) return getEmptyAnalytics(hoursRequested);
  valid.sort((a, b) => a.d - b.d);

  const latestDate = valid[valid.length - 1].d;
  const cutoff = new Date(latestDate.getTime() - hoursRequested * 60 * 60 * 1000);

  let windowItems = valid.filter(item => item.d >= cutoff).map(item => item.s);
  if (windowItems.length === 0) {
    windowItems = valid.map(item => item.s);
  }

  const firstDate = new Date(windowItems[0].timestamp_utc);
  const lastDate = new Date(windowItems[windowItems.length - 1].timestamp_utc);
  const effectiveHours = Math.max((lastDate - firstDate) / (1000 * 3600), 0.1);

  // 2. Hardware counters delta
  const startsArr = windowItems.filter(s => s.compressor_starts != null).map(s => s.compressor_starts);
  const hoursArr = windowItems.filter(s => s.compressor_hours != null).map(s => s.compressor_hours);

  const hwStartsDelta = startsArr.length > 0 ? Math.max(0, startsArr[startsArr.length - 1] - startsArr[0]) : 0;
  const hwHoursDelta = hoursArr.length > 0 ? Math.max(0, hoursArr[hoursArr.length - 1] - hoursArr[0]) : 0;

  // 3. Cycle Detection (ignoring corrupted empty Viessmann polls like 21/11 13:41:25)
  const detectedCycles = [];
  let curCycle = [];
  let defrostEpisodes = 0;
  let defrostMinutes = 0;
  let prevDefrost = false;

  for (let idx = 0; idx < windowItems.length; idx++) {
    const s = windowItems[idx];
    const viessmannCorrupted =
      s.pdc_supply_temp_c == null &&
      s.active_program == null &&
      s.compressor_modulation_percent == null;
    if (viessmannCorrupted) {
      // Do not falsely break an active cycle on a transient empty Viessmann poll
      continue;
    }
    const isActive = (s.compressor_active === 1) || ((s.compressor_modulation_percent || 0) > 0);
    const isDef = String(s.compressor_phase || "").toLowerCase().includes("defrost");
    if (isDef && !prevDefrost) defrostEpisodes++;
    prevDefrost = isDef;

    if (isActive) {
      curCycle.push(s);
    } else {
      if (curCycle.length > 0) {
        detectedCycles.push(summarizeCycleJs(curCycle));
        curCycle = [];
      }
    }
  }
  if (curCycle.length > 0) {
    detectedCycles.push(summarizeCycleJs(curCycle));
  }

  const detectedStarts = detectedCycles.length;
  const totalStarts = Math.max(hwStartsDelta, detectedStarts);
  const detectedHours = detectedCycles.reduce((acc, c) => acc + c.duration_minutes, 0) / 60.0;
  let totalRunHours = Math.max(hwHoursDelta, detectedHours);
  totalRunHours = Math.min(totalRunHours, effectiveHours);
  const standbyHours = Math.max(0, effectiveHours - totalRunHours);
  const dutyCyclePct = ((totalRunHours / effectiveHours) * 100).toFixed(1);

  // 4. Durations
  let durAvg = 0, durMin = 0, durMax = 0;
  if (detectedCycles.length > 0) {
    const durs = detectedCycles.map(c => c.duration_minutes);
    durAvg = (durs.reduce((a, b) => a + b, 0) / durs.length).toFixed(1);
    durMin = Math.min(...durs).toFixed(1);
    durMax = Math.max(...durs).toFixed(1);
  } else if (totalStarts > 0 && totalRunHours > 0) {
    durAvg = ((totalRunHours * 60) / totalStarts).toFixed(1);
    durMin = (durAvg * 0.8).toFixed(1);
    durMax = (durAvg * 1.2).toFixed(1);
  }

  // 5. Modulation Quality Analysis
  const activeMods = windowItems
    .filter(s => (s.compressor_active === 1) || ((s.compressor_modulation_percent || 0) > 0))
    .map(s => s.compressor_modulation_percent || 0);

  const avgMod = activeMods.length > 0 ? (activeMods.reduce((a, b) => a + b, 0) / activeMods.length).toFixed(1) : 0;
  const maxMod = activeMods.length > 0 ? Math.max(...activeMods).toFixed(0) : 0;

  const lowLoadCount = activeMods.filter(m => m >= 1 && m <= 30).length;
  const midLoadCount = activeMods.filter(m => m >= 31 && m <= 60).length;
  const highLoadCount = activeMods.filter(m => m > 60).length;
  const nAct = Math.max(activeMods.length, 1);

  const lowPct = ((lowLoadCount / nAct) * 100).toFixed(0);
  const midPct = ((midLoadCount / nAct) * 100).toFixed(0);
  const highPct = ((highLoadCount / nAct) * 100).toFixed(0);

  const isShortCycling = totalStarts > 0 && (parseFloat(durAvg) < 20 || (totalStarts / effectiveHours) > 1.8);

  let score = 100;
  let verdict = "";
  let diagnosis = "";

  if (totalStarts === 0) {
    score = 100;
    verdict = "⚪ Standby / Macchina Inattiva";
    diagnosis = "Nessun avviamento del compressore nelle ultime ore. Temperatura interna sempre sopra il setpoint antigelo: zero sprechi!";
  } else if (isShortCycling) {
    score = Math.max(35, 100 - (totalStarts * 10) - (parseFloat(durAvg) < 15 ? 20 : 10));
    verdict = "⚠️ Short-Cycling Rilevato (Cicli Brevi)";
    diagnosis = `La PdC ha effettuato ${totalStarts} avviamenti di soli ${durAvg} min in media. Sui 200L di puffer, la macchina si arresta precocemente. Suggerito sincronizzare con Grundfos.`;
  } else if (parseFloat(durAvg) >= 40) {
    const defrostPenalty = Math.min(20, defrostEpisodes * 3);
    score = Math.max(55, (highPct < 20 ? 95 : (highPct < 55 ? 85 : 75)) - defrostPenalty);
    verdict = defrostEpisodes >= 4
      ? "❄️ Cicli Lunghi ma Alti Sbrinamenti (Defrost)"
      : "🌟 Modulazione Ottimale (Inverter Dolce & Continuo)";
    diagnosis = defrostEpisodes >= 4
      ? `Cicli lunghi (${durAvg} min, carico medio ${avgMod}%) ma ${defrostEpisodes} episodi di defrost che penalizzano il COP netto. Consigliato Soft-Start + Defrost Guard attivi.`
      : `Modulazione eccellente: i cicli durano in media ${durAvg} min a regime medio ${avgMod}%. Il compressore opera in zona ad alta resa energetica.`;
  } else {
    score = 75;
    verdict = "🟢 Modulazione Buona / Regolare";
    diagnosis = `Funzionamento regolare: ${totalStarts} avviamenti con durata media di ${durAvg} min. Ripartizione del carico bilanciata.`;
  }

  // 6. Trapezoidal Time-Integrated Calibrated Consumption & Daily Ledger
  const fallbackEstimatePower = (s) => {
    const gfKw = s.grundfos_pump_active === 1 ? 0.030 : 0.0;
    const isComp = s.compressor_active === 1 || (Number(s.compressor_modulation_percent) || 0) > 0;
    if (!isComp) return { pElecKw: 0.020 + gfKw, pThermalKw: 0, isDefrost: false };
    const isDef = String(s.compressor_phase || "").toLowerCase().includes("defrost");
    if (isDef) return { pElecKw: 1.35 + gfKw, pThermalKw: -3.5, isDefrost: true };
    const mod = Number(s.compressor_modulation_percent) || 0;
    const pEl = 0.55 + 2.55 * (mod / 100.0) + 0.045 + gfKw;
    return { pElecKw: pEl, pThermalKw: pEl * 3.1, isDefrost: false };
  };
  const pwrFn = (typeof window !== "undefined" && typeof window.estimateSamplePower === "function")
    ? window.estimateSamplePower
    : fallbackEstimatePower;

  let integElecKwh = 0;
  let integThermalNetKwh = 0;
  const dailyMap = new Map();

  for (let i = 0; i < windowItems.length; i++) {
    const s = windowItems[i];
    const tCur = new Date(s.timestamp_utc).getTime();
    let dtH = 5 / 60.0;
    if (i + 1 < windowItems.length) {
      const tNext = new Date(windowItems[i + 1].timestamp_utc).getTime();
      const dtMs = Math.max(15000, Math.min(30 * 60 * 1000, tNext - tCur));
      dtH = dtMs / 3600000.0;
    } else if (i > 0) {
      const tPrev = new Date(windowItems[i - 1].timestamp_utc).getTime();
      const dtMs = Math.max(15000, Math.min(30 * 60 * 1000, tCur - tPrev));
      dtH = dtMs / 3600000.0;
    }
    const viessmannCorrupted =
      s.pdc_supply_temp_c == null &&
      s.active_program == null &&
      s.compressor_modulation_percent == null;
    const refSample = (viessmannCorrupted && i > 0) ? windowItems[i - 1] : s;
    const pwr = pwrFn(refSample);
    const dEl = pwr.pElecKw * dtH;
    const dTh = pwr.pThermalKw * dtH;
    integElecKwh += dEl;
    integThermalNetKwh += dTh;
    if (pwr.isDefrost) defrostMinutes += dtH * 60.0;

    // Daily bucket (local date)
    const dObj = new Date(tCur);
    const dayKey = `${String(dObj.getDate()).padStart(2, "0")}/${String(dObj.getMonth() + 1).padStart(2, "0")}`;
    if (!dailyMap.has(dayKey)) {
      dailyMap.set(dayKey, {
        day: dayKey,
        sortTs: dObj.getTime(),
        elecKwh: 0,
        thermalNetKwh: 0,
        runMin: 0,
        defrosts: 0,
        prevDef: false,
        tinMin: Infinity,
        tinMax: -Infinity,
      });
    }
    const bucket = dailyMap.get(dayKey);
    bucket.elecKwh += dEl;
    bucket.thermalNetKwh += dTh;
    const compOn = refSample.compressor_active === 1 || (Number(refSample.compressor_modulation_percent) || 0) > 0;
    if (compOn) bucket.runMin += dtH * 60.0;
    if (pwr.isDefrost && !bucket.prevDef) bucket.defrosts++;
    bucket.prevDef = pwr.isDefrost;
    if (s.indoor_temp_bticino_c != null) {
      const tin = Number(s.indoor_temp_bticino_c);
      bucket.tinMin = Math.min(bucket.tinMin, tin);
      bucket.tinMax = Math.max(bucket.tinMax, tin);
    }
  }

  // Add backup electric heatingRod energy if S1/S2 incremented in this window (3 kW per stage)
  const r1Arr = windowItems.filter(s => s.heating_rod_level1_s != null).map(s => Number(s.heating_rod_level1_s));
  const r2Arr = windowItems.filter(s => s.heating_rod_level2_s != null).map(s => Number(s.heating_rod_level2_s));
  const dr1s = r1Arr.length >= 2 ? Math.max(0, r1Arr[r1Arr.length - 1] - r1Arr[0]) : 0;
  const dr2s = r2Arr.length >= 2 ? Math.max(0, r2Arr[r2Arr.length - 1] - r2Arr[0]) : 0;
  const rodElecKwh = ((dr1s + dr2s) / 3600.0) * 3.0;
  integElecKwh += rodElecKwh;
  integThermalNetKwh += rodElecKwh;

  const totalElecKwh = parseFloat(integElecKwh.toFixed(2));
  const totalThermalNetKwh = parseFloat(Math.max(0, integThermalNetKwh).toFixed(1));
  const realNetCop = (totalElecKwh > 0.2 && totalThermalNetKwh > 0)
    ? parseFloat((totalThermalNetKwh / totalElecKwh).toFixed(2))
    : 0;
  const avgPowerKw = parseFloat((totalElecKwh / effectiveHours).toFixed(3));
  const estimatedCostEur = parseFloat((totalElecKwh * costPerKwh).toFixed(2));
  const projectedDailyCost = parseFloat(((totalElecKwh / effectiveHours) * 24 * costPerKwh).toFixed(2));

  const dailyBreakdown = Array.from(dailyMap.values())
    .sort((a, b) => b.sortTs - a.sortTs)
    .slice(0, 7)
    .map(b => ({
      day: b.day,
      runMin: Math.round(b.runMin),
      defrosts: b.defrosts,
      elecKwh: parseFloat(b.elecKwh.toFixed(2)),
      thermalNetKwh: parseFloat(Math.max(0, b.thermalNetKwh).toFixed(1)),
      netCop: (b.elecKwh > 0.5 && b.thermalNetKwh > 0) ? parseFloat((b.thermalNetKwh / b.elecKwh).toFixed(2)) : null,
      costEur: parseFloat((b.elecKwh * costPerKwh).toFixed(2)),
      tinRange: b.tinMin < Infinity ? `${b.tinMin.toFixed(1)}–${b.tinMax.toFixed(1)}°` : "--",
    }));

  // 7. Anti-frost safety
  const inTemps = windowItems.filter(s => s.indoor_temp_bticino_c != null).map(s => s.indoor_temp_bticino_c);
  const bufTemps = windowItems.filter(s => s.buffer_temp_c != null).map(s => s.buffer_temp_c);
  const outTemps = windowItems.filter(s => s.external_temp_c != null).map(s => s.external_temp_c);

  const minIndoor = inTemps.length > 0 ? Math.min(...inTemps) : 7.8;
  const minBuffer = bufTemps.length > 0 ? Math.min(...bufTemps) : 13.0;
  const minOutdoor = outTemps.length > 0 ? Math.min(...outTemps) : 4.0;
  const safetyMargin = parseFloat((minIndoor - freezeThreshold).toFixed(1));

  let safetyStatus = "safe";
  let safetyVerdict = "";
  let safetyAdvice = "";

  if (safetyMargin >= 2.0) {
    safetyStatus = "safe";
    safetyVerdict = `🛡️ CASA AL SICURO DAL GELO (Margine +${safetyMargin} °C)`;
    safetyAdvice = `Minima interna: ${minIndoor.toFixed(1)} °C. Spesa proiettata a regime: ${projectedDailyCost} €/giorno. Nessun consumo superfluo: sicurezza garantita al costo minimo.`;
  } else if (safetyMargin >= 0.5) {
    safetyStatus = "caution";
    safetyVerdict = `⚠️ MARGINE GELO RIDOTTO (+${safetyMargin} °C)`;
    safetyAdvice = `Minima interna: ${minIndoor.toFixed(1)} °C, vicina alla soglia di guardia (${freezeThreshold} °C).`;
  } else {
    safetyStatus = "danger";
    safetyVerdict = `🚨 RISCHIO GELO ATTIVO!`;
    safetyAdvice = `ALLERTA: Temperatura interna a ${minIndoor.toFixed(1)} °C. Attivare il riscaldamento!`;
  }

  return {
    hoursRequested,
    effectiveHours: effectiveHours.toFixed(1),
    samplesCount: windowItems.length,
    totalStarts,
    totalRunHours: totalRunHours.toFixed(2),
    standbyHours: standbyHours.toFixed(2),
    dutyCyclePct,
    durAvg,
    durMin,
    durMax,
    avgMod,
    maxMod,
    lowPct,
    midPct,
    highPct,
    isShortCycling,
    score,
    verdict,
    diagnosis,
    totalElecKwh,
    totalThermalNetKwh,
    realNetCop,
    defrostEpisodes,
    defrostMinutes: Math.round(defrostMinutes),
    rodElecKwh: parseFloat(rodElecKwh.toFixed(2)),
    dailyBreakdown,
    avgPowerKw,
    estimatedCostEur,
    projectedDailyCost,
    minIndoor: minIndoor.toFixed(1),
    minBuffer: minBuffer.toFixed(1),
    minOutdoor: minOutdoor.toFixed(1),
    safetyMargin,
    safetyStatus,
    safetyVerdict,
    safetyAdvice,
    cycles: detectedCycles,
  };
}

function summarizeCycleJs(cycleSamples) {
  const t0 = new Date(cycleSamples[0].timestamp_utc);
  const t1 = new Date(cycleSamples[cycleSamples.length - 1].timestamp_utc);
  let dur = Math.max((t1 - t0) / (1000 * 60), 5.0);
  const mods = cycleSamples.map(s => s.compressor_modulation_percent || 0);

  return {
    start: cycleSamples[0].timestamp_utc,
    end: cycleSamples[cycleSamples.length - 1].timestamp_utc,
    duration_minutes: parseFloat(dur.toFixed(1)),
    avg_modulation: mods.length > 0 ? (mods.reduce((a, b) => a + b, 0) / mods.length).toFixed(1) : 0,
    max_modulation: mods.length > 0 ? Math.max(...mods).toFixed(0) : 0,
  };
}

function getEmptyAnalytics(hours) {
  return {
    hoursRequested: hours, effectiveHours: "0", samplesCount: 0,
    totalStarts: 0, totalRunHours: "0", standbyHours: "0", dutyCyclePct: "0",
    durAvg: "0", durMin: "0", durMax: "0", avgMod: "0", maxMod: "0",
    lowPct: "0", midPct: "0", highPct: "0", isShortCycling: false,
    score: 100, verdict: "In attesa di dati...", diagnosis: "Nessun dato registrato nel periodo.",
    totalElecKwh: 0, totalThermalNetKwh: 0, realNetCop: 0, defrostEpisodes: 0, defrostMinutes: 0, rodElecKwh: 0, dailyBreakdown: [],
    avgPowerKw: 0, estimatedCostEur: 0, projectedDailyCost: 0,
    minIndoor: "--", minBuffer: "--", minOutdoor: "--", safetyMargin: 0,
    safetyStatus: "safe", safetyVerdict: "Dati insufficienti", safetyAdvice: "", cycles: []
  };
}
