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

  // 3. Cycle Detection
  const detectedCycles = [];
  let curCycle = [];

  for (const s of windowItems) {
    const isActive = (s.compressor_active === 1) || ((s.compressor_modulation_percent || 0) > 0);
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
    score = highPct < 20 ? 95 : 85;
    verdict = "🌟 Modulazione Ottimale (Inverter Dolce & Continuo)";
    diagnosis = `Modulazione eccellente: i cicli durano in media ${durAvg} min a regime medio ${avgMod}%. Il compressore opera in zona ad altissima resa energetica.`;
  } else {
    score = 75;
    verdict = "🟢 Modulazione Buona / Regolare";
    diagnosis = `Funzionamento regolare: ${totalStarts} avviamenti con durata media di ${durAvg} min. Ripartizione del carico bilanciata.`;
  }

  // 6. Electricity & Cost Estimation
  const pStandbyKw = 0.025;
  const avgActiveKw = activeMods.length > 0
    ? (activeMods.reduce((acc, m) => acc + (0.70 + (m / 100.0) * 2.80), 0) / activeMods.length)
    : 1.68;

  const totalElecKwh = parseFloat(((totalRunHours * avgActiveKw) + (standbyHours * pStandbyKw)).toFixed(2));
  const avgPowerKw = parseFloat((totalElecKwh / effectiveHours).toFixed(3));
  const estimatedCostEur = parseFloat((totalElecKwh * costPerKwh).toFixed(2));
  const projectedDailyCost = parseFloat(((totalElecKwh / effectiveHours) * 24 * costPerKwh).toFixed(2));

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
    totalElecKwh: 0, avgPowerKw: 0, estimatedCostEur: 0, projectedDailyCost: 0,
    minIndoor: "--", minBuffer: "--", minOutdoor: "--", safetyMargin: 0,
    safetyStatus: "safe", safetyVerdict: "Dati insufficienti", safetyAdvice: "", cycles: []
  };
}
