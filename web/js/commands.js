/**
 * Bidirectional Remote Control Controller for Vitocal 111-S & BTicino Smarther.
 * Routes commands to local Flask API when on LAN Wi-Fi, or securely via
 * GitHub Actions workflow_dispatch (apply_command.yml) when running over 4G/5G.
 */

const cmdState = {
  initialized: false,
  hydratedOnce: false,
  isSending: false,
  autopilotEnabled: false,
  autopilotState: "DISABLED",
  pendingAction: null,
  baseline: {
    pdcMode: "dhwAndHeating",
    slope: 0.6,
    shift: 0,
    normal: 12,
    reduced: 12,
    dhw: 10,
    bticinoSp: 7.0,
    oat: 5.0,
    program: "standby",
  },
  dirty: {
    mode: false,
    curve: false,
    temps: false,
    bticino: false,
  },
};

function initCommandsUI() {
  if (cmdState.initialized) return;
  cmdState.initialized = true;

  populateTimeSelects();
  bindSteppers();
  bindDirtyWatchers();
  bindCommandButtons();
  bindAutopilotButtons();
  bindConfirmModal();
  updateCommandsTransportUI();
}

function populateTimeSelects() {
  const startSel = document.getElementById("cmdSchedStart");
  const endSel = document.getElementById("cmdSchedEnd");
  if (!startSel || !endSel) return;

  const opts = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m += 10) {
      const val = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
      opts.push(`<option value="${val}">${val}</option>`);
    }
  }
  const html = opts.join("");
  startSel.innerHTML = html;
  endSel.innerHTML = html;
  startSel.value = "11:00";
  endSel.value = "16:00";
}

function bindSteppers() {
  document.querySelectorAll(".btn-step").forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.target;
      const stepDelta = parseFloat(btn.dataset.step);
      const input = document.getElementById(targetId);
      if (!input || isNaN(stepDelta)) return;

      const cur = parseFloat(input.value);
      const min = input.min !== "" ? parseFloat(input.min) : -999;
      const max = input.max !== "" ? parseFloat(input.max) : 999;
      const base = isNaN(cur) ? 0 : cur;
      const decimals = (String(Math.abs(stepDelta)).split(".")[1] || "").length;
      const next = Math.max(min, Math.min(max, Number((base + stepDelta).toFixed(decimals))));
      input.value = decimals > 0 ? next.toFixed(decimals) : String(Math.round(next));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
}

function bindDirtyWatchers() {
  const modeSel = document.getElementById("cmdPdcModeSelect");
  if (modeSel) {
    modeSel.addEventListener("change", () => {
      cmdState.dirty.mode = modeSel.value !== cmdState.baseline.pdcMode;
      updateCommandLeds();
    });
  }

  for (const id of ["cmdSlopeInput", "cmdShiftInput"]) {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => {
        const s = parseFloat(document.getElementById("cmdSlopeInput").value);
        const sh = parseInt(document.getElementById("cmdShiftInput").value, 10);
        cmdState.dirty.curve = (Math.abs(s - cmdState.baseline.slope) > 0.05) || (sh !== cmdState.baseline.shift);
        updateCurvePreview();
        updateCommandLeds();
      });
    }
  }

  for (const id of ["cmdTempNormal", "cmdTempReduced", "cmdTempDhw"]) {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => {
        const tn = parseInt(document.getElementById("cmdTempNormal").value, 10);
        const tr = parseInt(document.getElementById("cmdTempReduced").value, 10);
        const td = parseInt(document.getElementById("cmdTempDhw").value, 10);
        cmdState.dirty.temps = (tn !== cmdState.baseline.normal) || (tr !== cmdState.baseline.reduced) || (td !== cmdState.baseline.dhw);
        updateCurvePreview();
        updateCommandLeds();
      });
    }
  }

  const btSp = document.getElementById("cmdBticinoTemp");
  if (btSp) {
    btSp.addEventListener("input", () => {
      const val = parseFloat(btSp.value);
      cmdState.dirty.bticino = isNaN(val) || Math.abs(val - cmdState.baseline.bticinoSp) > 0.1;
      updateCommandLeds();
    });
  }
}

function updateCurvePreview() {
  const preview = document.getElementById("cmdCurveLwtPreview");
  if (!preview || typeof window.computeVitocalTargetLwt !== "function") return;
  const slope = parseFloat(document.getElementById("cmdSlopeInput").value);
  const shift = parseInt(document.getElementById("cmdShiftInput").value, 10);
  const tNorm = parseInt(document.getElementById("cmdTempNormal").value, 10);
  const tRed = parseInt(document.getElementById("cmdTempReduced").value, 10);

  const synthetic = {
    external_temp_c: cmdState.baseline.oat,
    heating_curve_slope: isNaN(slope) ? cmdState.baseline.slope : slope,
    heating_curve_shift: isNaN(shift) ? cmdState.baseline.shift : shift,
    normal_setpoint_c: isNaN(tNorm) ? cmdState.baseline.normal : tNorm,
    reduced_setpoint_c: isNaN(tRed) ? cmdState.baseline.reduced : tRed,
    active_program: cmdState.baseline.program === "reduced" ? "reduced" : "normal",
  };
  const lwt = window.computeVitocalTargetLwt(synthetic, true);
  const oatStr = cmdState.baseline.oat != null ? `${Number(cmdState.baseline.oat).toFixed(1)} °C` : "--";
  preview.textContent = lwt != null
    ? `🎯 Target LWT stimato (a OAT ${oatStr}): ${lwt.toFixed(1)} °C`
    : "🎯 Target LWT stimato: -- °C";
}

function updateCommandLeds() {
  setLed("ledPdcMode", cmdState.dirty.mode);
  setLed("ledPdcCurve", cmdState.dirty.curve);
  setLed("ledPdcTemps", cmdState.dirty.temps);
  setLed("ledBticinoSp", cmdState.dirty.bticino);
}

function setLed(id, isPending) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = isPending ? "🟠 Da inviare" : "🟢 Sincronizzato";
  el.classList.toggle("pending", isPending);
  el.classList.toggle("synced", !isPending);
}

function syncCommandsFromTelemetry(sample) {
  if (!sample) return;
  if (!cmdState.initialized) initCommandsUI();

  if (sample.active_mode) cmdState.baseline.pdcMode = sample.active_mode;
  if (sample.heating_curve_slope != null) cmdState.baseline.slope = Number(sample.heating_curve_slope);
  if (sample.heating_curve_shift != null) cmdState.baseline.shift = Math.round(Number(sample.heating_curve_shift));
  if (sample.normal_setpoint_c != null) cmdState.baseline.normal = Math.round(Number(sample.normal_setpoint_c));
  if (sample.reduced_setpoint_c != null) cmdState.baseline.reduced = Math.round(Number(sample.reduced_setpoint_c));
  if (sample.dhw_setpoint_c != null) cmdState.baseline.dhw = Math.round(Number(sample.dhw_setpoint_c));
  if (sample.indoor_setpoint_bticino_c != null) cmdState.baseline.bticinoSp = Number(sample.indoor_setpoint_bticino_c);
  if (sample.external_temp_c != null) cmdState.baseline.oat = Number(sample.external_temp_c);
  if (sample.active_program) cmdState.baseline.program = sample.active_program;

  if (!cmdState.dirty.mode) {
    const modeSel = document.getElementById("cmdPdcModeSelect");
    if (modeSel && ["standby", "dhw", "dhwAndHeating"].includes(cmdState.baseline.pdcMode)) {
      modeSel.value = cmdState.baseline.pdcMode;
    }
  }
  if (!cmdState.dirty.curve) {
    const slpEl = document.getElementById("cmdSlopeInput");
    const shfEl = document.getElementById("cmdShiftInput");
    if (slpEl) slpEl.value = cmdState.baseline.slope.toFixed(1);
    if (shfEl) shfEl.value = String(cmdState.baseline.shift);
  }
  if (!cmdState.dirty.temps) {
    const tn = document.getElementById("cmdTempNormal");
    const tr = document.getElementById("cmdTempReduced");
    const td = document.getElementById("cmdTempDhw");
    if (tn) tn.value = String(cmdState.baseline.normal);
    if (tr) tr.value = String(cmdState.baseline.reduced);
    if (td) td.value = String(cmdState.baseline.dhw);
  }
  if (!cmdState.dirty.bticino) {
    const btEl = document.getElementById("cmdBticinoTemp");
    if (btEl) btEl.value = cmdState.baseline.bticinoSp.toFixed(1);
  }

  const presetTag = document.getElementById("cmdPresetLiveState");
  if (presetTag) {
    const compOn = (sample.compressor_active === 1) || ((sample.compressor_modulation_percent || 0) > 0);
    const gfOn = sample.grundfos_pump_active === 1;
    presetTag.textContent = `PdC: ${compOn ? "ON" : "OFF"} | GF: ${gfOn ? "ON" : "OFF"}`;
  }

  const progTag = document.getElementById("cmdPdcActiveProg");
  if (progTag) {
    progTag.textContent = `PROG: ${(sample.active_program || "--").toUpperCase()}`;
  }

  cmdState.hydratedOnce = true;
  updateCurvePreview();
  updateCommandLeds();
}

function updateCommandsTransportUI() {
  const badge = document.getElementById("cmdTransportBadge");
  const warn = document.getElementById("cmdTokenWarning");
  const hasBackend = typeof state !== "undefined" && state.backendConnected;
  const hasToken = typeof state !== "undefined" && Boolean(state.githubToken);

  if (badge) {
    badge.textContent = hasBackend ? "LAN Locale (Diretto)" : "Cloud Actions (4G/5G)";
    badge.style.color = hasBackend ? "#10b981" : "#38bdf8";
  }
  if (warn) {
    warn.style.display = (!hasBackend && !hasToken) ? "block" : "none";
  }
}

function getDaysListFromSelect(val) {
  if (val === "weekdays") return ["mon", "tue", "wed", "thu", "fri"];
  if (val === "weekend") return ["sat", "sun"];
  return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
}

function bindCommandButtons() {
  // Resets
  const btnResetCurve = document.getElementById("btnResetPdcCurve");
  if (btnResetCurve) {
    btnResetCurve.addEventListener("click", () => {
      document.getElementById("cmdSlopeInput").value = cmdState.baseline.slope.toFixed(1);
      document.getElementById("cmdShiftInput").value = String(cmdState.baseline.shift);
      cmdState.dirty.curve = false;
      updateCurvePreview();
      updateCommandLeds();
    });
  }

  const btnResetBt = document.getElementById("btnResetBticinoSp");
  if (btnResetBt) {
    btnResetBt.addEventListener("click", () => {
      document.getElementById("cmdBticinoTemp").value = cmdState.baseline.bticinoSp.toFixed(1);
      cmdState.dirty.bticino = false;
      updateCommandLeds();
    });
  }

  // Presets
  const btnSyncPulse = document.getElementById("btnPresetSyncPulse");
  if (btnSyncPulse) {
    btnSyncPulse.addEventListener("click", () => {
      const temp = parseFloat(document.getElementById("cmdSyncTemp").value);
      const dur = parseInt(document.getElementById("cmdSyncDuration").value, 10);
      requestCommandConfirm(
        "preset_sync_pulse",
        { temp, duration_minutes: dur },
        `Avviare ciclo sincronizzato: PdC in Riscaldamento + ACS e BTicino a ${temp.toFixed(1)} °C per ${dur} minuti (accendendo la Grundfos)?`,
        "all"
      );
    });
  }

  const btnStopAll = document.getElementById("btnPresetStopAll");
  if (btnStopAll) {
    btnStopAll.addEventListener("click", () => {
      requestCommandConfirm(
        "preset_stop_all",
        {},
        "Mettere la Vitocal 111-S in STANDBY e il BTicino Smarther in modalità ANTIGELO (HG)?",
        "all"
      );
    });
  }

  // Viessmann Mode
  const btnMode = document.getElementById("btnSendPdcMode");
  if (btnMode) {
    btnMode.addEventListener("click", () => {
      const mode = document.getElementById("cmdPdcModeSelect").value;
      requestCommandConfirm(
        "viessmann_mode",
        { mode },
        `Impostare la modalità operativa Vitocal su "${mode}"?`,
        "mode"
      );
    });
  }

  // Viessmann Curve
  const btnCurve = document.getElementById("btnSendPdcCurve");
  if (btnCurve) {
    btnCurve.addEventListener("click", () => {
      const slope = Number(parseFloat(document.getElementById("cmdSlopeInput").value).toFixed(1));
      const shift = parseInt(document.getElementById("cmdShiftInput").value, 10);
      requestCommandConfirm(
        "viessmann_curve",
        { slope, shift },
        `Inviare nuova Curva Climatica alla Vitocal: Slope = ${slope.toFixed(1)}, Shift = ${shift} K?`,
        "curve"
      );
    });
  }

  // Viessmann Temperatures
  const btnTemps = document.getElementById("btnSendPdcTemps");
  if (btnTemps) {
    btnTemps.addEventListener("click", () => {
      const normal = parseInt(document.getElementById("cmdTempNormal").value, 10);
      const reduced = parseInt(document.getElementById("cmdTempReduced").value, 10);
      const dhw = parseInt(document.getElementById("cmdTempDhw").value, 10);
      requestCommandConfirm(
        "viessmann_temps",
        { normal, reduced, dhw },
        `Impostare le temperature Vitocal: Normale = ${normal} °C, Ridotta = ${reduced} °C, Bollitore ACS = ${dhw} °C?`,
        "temps"
      );
    });
  }

  const btnDhwBoost = document.getElementById("btnSendDhwBoost");
  if (btnDhwBoost) {
    btnDhwBoost.addEventListener("click", () => {
      requestCommandConfirm(
        "viessmann_dhw_boost",
        { active: true },
        "Avviare una carica singola rapida del bollitore ACS sanitario?",
        null
      );
    });
  }

  // Viessmann Schedule
  const btnSched = document.getElementById("btnSendPdcSchedule");
  if (btnSched) {
    btnSched.addEventListener("click", () => {
      const daysVal = document.getElementById("cmdSchedDays").value;
      const days = getDaysListFromSelect(daysVal);
      const start = document.getElementById("cmdSchedStart").value;
      const end = document.getElementById("cmdSchedEnd").value;
      const mode = document.getElementById("cmdSchedMode").value;
      if (start >= end) {
        showToast("⚠️ L'orario di fine deve essere successivo all'inizio.");
        return;
      }
      requestCommandConfirm(
        "viessmann_schedule",
        { days, start, end, mode, clear: false },
        `Impostare fascia oraria PdC (${days.join(", ")}) dalle ${start} alle ${end} in modalità "${mode}"?`,
        null
      );
    });
  }

  const btnClearSched = document.getElementById("btnClearPdcSchedule");
  if (btnClearSched) {
    btnClearSched.addEventListener("click", () => {
      const daysVal = document.getElementById("cmdSchedDays").value;
      const days = getDaysListFromSelect(daysVal);
      requestCommandConfirm(
        "viessmann_schedule",
        { days, clear: true },
        `Svuotare le fasce orarie PdC per (${days.join(", ")}) lasciando il circuito in Standby?`,
        null
      );
    });
  }

  // BTicino Manual Setpoint
  const btnBtManual = document.getElementById("btnSendBticinoManual");
  if (btnBtManual) {
    btnBtManual.addEventListener("click", () => {
      const temp = Number(parseFloat(document.getElementById("cmdBticinoTemp").value).toFixed(1));
      const dur = parseInt(document.getElementById("cmdBticinoDuration").value, 10);
      requestCommandConfirm(
        "bticino_setpoint",
        { mode: "manual", temp, duration_minutes: dur },
        `Impostare BTicino Smarther (Corridoio) in manuale a ${temp.toFixed(1)} °C per ${dur} minuti?`,
        "bticino"
      );
    });
  }

  // BTicino Mode Pills
  document.querySelectorAll(".cmd-bt-mode").forEach(btn => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      const labelMap = { home: "Programma Settimanale (Home)", hg: "Antigelo (HG)", away: "Assente (Away)" };
      requestCommandConfirm(
        "bticino_setpoint",
        { mode },
        `Passare il termostato BTicino Smarther a: ${labelMap[mode] || mode}?`,
        "bticino"
      );
    });
  });

  // BTicino Schedule Switch
  const btnBtSched = document.getElementById("btnSendBticinoSchedule");
  if (btnBtSched) {
    btnBtSched.addEventListener("click", () => {
      const sel = document.getElementById("cmdBticinoScheduleSelect");
      const val = sel ? sel.value : "";
      const opt = sel && sel.selectedOptions ? sel.selectedOptions[0] : null;
      const label = opt ? opt.textContent : val;
      const payload = (opt && opt.dataset.id) ? { schedule_id: opt.dataset.id, schedule_name: label } : { schedule_name: val };
      requestCommandConfirm(
        "bticino_switch_schedule",
        payload,
        `Attivare sul BTicino Smarther la programmazione "${label}"?`,
        null
      );
    });
  }

  const btnRefSched = document.getElementById("btnRefreshSchedules");
  if (btnRefSched) {
    btnRefSched.addEventListener("click", refreshSchedulesFromLocal);
  }
}

async function refreshSchedulesFromLocal() {
  if (!state.backendConnected) {
    showToast("ℹ️ Rilettura dinamica disponibile su Wi-Fi locale; elenco precaricato pronto.");
    return;
  }
  try {
    const res = await fetch("./api/schedules");
    const data = await res.json();
    if (data && data.success && Array.isArray(data.bticino_schedules) && data.bticino_schedules.length) {
      const sel = document.getElementById("cmdBticinoScheduleSelect");
      if (sel) {
        sel.innerHTML = data.bticino_schedules.map(sc =>
          `<option value="${sc.name}" data-id="${sc.id}" ${sc.selected ? "selected" : ""}>${sc.name}${sc.selected ? " (Attiva)" : ""}</option>`
        ).join("");
        showToast("✅ Programmazioni BTicino aggiornate dal server locale.");
      }
    }
  } catch (e) {
    showToast(`⚠️ Errore lettura programmazioni: ${e.message}`);
  }
}

function requestCommandConfirm(command, params, summaryText, dirtyKey) {
  if (cmdState.isSending) {
    showToast("⏳ Un altro comando è già in esecuzione...");
    return;
  }
  updateCommandsTransportUI();
  const forceCloud = command === "cronjob_test";
  const useLocal = state.backendConnected && !forceCloud;
  if (!useLocal && !state.githubToken) {
    showToast("⚠️ Inserisci il GitHub Personal Access Token nella scheda Sync per testare/comandare via GitHub Actions!");
    return;
  }

  cmdState.pendingAction = { command, params, dirtyKey, forceCloud };
  const modal = document.getElementById("commandConfirmModal");
  const sumEl = document.getElementById("cmdConfirmSummary");
  const routeEl = document.getElementById("cmdConfirmRouteHint");
  const cancelBtn = document.getElementById("btnCancelCmdConfirm");

  if (sumEl) sumEl.textContent = summaryText;
  if (routeEl) {
    routeEl.textContent = useLocal
      ? "🔌 Canale: Server Locale Wi-Fi (esecuzione diretta ~2–4 s)."
      : "☁️ Canale: GitHub Actions (apply_command.yml, esecuzione ~25–35 s).";
  }

  if (modal) {
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    if (cancelBtn) setTimeout(() => cancelBtn.focus(), 40);
  }
}

function closeConfirmModal() {
  const modal = document.getElementById("commandConfirmModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  cmdState.pendingAction = null;
}

function bindConfirmModal() {
  const modal = document.getElementById("commandConfirmModal");
  if (!modal || modal.dataset.bound === "1") return;
  modal.dataset.bound = "1";

  const closeBtn = document.getElementById("btnCloseCmdConfirm");
  const cancelBtn = document.getElementById("btnCancelCmdConfirm");
  const confirmBtn = document.getElementById("btnConfirmSendCmd");

  if (closeBtn) closeBtn.addEventListener("click", closeConfirmModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeConfirmModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeConfirmModal();
  });

  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      if (!cmdState.pendingAction) return;
      const action = cmdState.pendingAction;
      closeConfirmModal();
      await executeCommandAction(action);
    });
  }
}

function setReceiptBanner(statusClass, text) {
  const box = document.getElementById("lastCommandReceiptBox");
  if (!box) return;
  box.className = `cmd-receipt-box ${statusClass || ""}`.trim();
  box.textContent = text;
}

function clearDirtyFlag(dirtyKey) {
  if (!dirtyKey) return;
  if (dirtyKey === "all") {
    cmdState.dirty = { mode: false, curve: false, temps: false, bticino: false };
  } else if (dirtyKey in cmdState.dirty) {
    cmdState.dirty[dirtyKey] = false;
  }
  updateCommandLeds();
}

async function executeCommandAction({ command, params, dirtyKey, forceCloud }) {
  cmdState.isSending = true;

  if (state.backendConnected && !forceCloud) {
    setReceiptBanner("pending", `⏳ Invio comando '${command}' tramite server locale...`);
    try {
      const res = await fetch("./api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, params }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        clearDirtyFlag(dirtyKey);
        setReceiptBanner("ok", `✅ ${data.message}`);
        showToast("✅ Comando eseguito e verificato!");
        if (data.sample) {
          state.samples.push(data.sample);
          state.latestSample = data.sample;
          updateUI();
        }
        await refreshAutopilotStatus();
      } else {
        setReceiptBanner("err", `❌ ${data.message || "Errore esecuzione comando"}`);
        showToast(`❌ ${data.message || "Errore comando"}`);
      }
    } catch (e) {
      setReceiptBanner("err", `❌ Errore rete locale: ${e.message}`);
      showToast(`❌ Errore rete: ${e.message}`);
    } finally {
      cmdState.isSending = false;
    }
    return;
  }

  // Remote execution via GitHub Actions workflow_dispatch
  const dispatchAtMs = Date.now();
  setReceiptBanner("pending", `⏳ Invio '${command}' a GitHub Actions (apply_command.yml)...`);
  try {
    const url = `https://api.github.com/repos/${state.repo}/actions/workflows/apply_command.yml/dispatches`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": `token ${state.githubToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          command,
          payload_json: JSON.stringify(params || {}),
        },
      }),
    });

    if (res.status !== 204) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(`HTTP ${res.status}: ${errJson.message || "Verifica token (permesso Actions/Workflow)"}`);
    }

    showToast("🚀 Comando inviato al cloud! Attendo conferma dall'impianto (~25s)...");
    setReceiptBanner("pending", `🚀 Ordine '${command}' preso in carico dal runner GitHub. Attendo esito...`);

    const receipt = await pollCommandReceipt(dispatchAtMs);
    if (receipt) {
      if (receipt.success) {
        clearDirtyFlag(dirtyKey);
        setReceiptBanner("ok", `✅ [${formatReceiptTime(receipt.timestamp_utc)}] ${receipt.message}`);
        showToast("✅ Impianto aggiornato con successo!");
      } else {
        setReceiptBanner("err", `❌ [${formatReceiptTime(receipt.timestamp_utc)}] ${receipt.message}`);
        showToast(`⚠️ Comando non riuscito: ${receipt.message}`);
      }
      await syncWithGitHub(false);
      await refreshAutopilotStatus();
    } else {
      setReceiptBanner("pending", "ℹ️ Il runner sta ancora completando l'operazione. Premi 🔄 tra qualche secondo.");
    }
  } catch (e) {
    setReceiptBanner("err", `❌ Invio fallito: ${e.message}`);
    showToast(`❌ ${e.message}`);
  } finally {
    cmdState.isSending = false;
  }
}

async function fetchDataJson(filename) {
  try {
    if (state.backendConnected) {
      const res = await fetch(`./data/${filename}?t=${Date.now()}`);
      if (res.ok) return await res.json();
    } else if (state.githubToken) {
      const apiUrl = `https://api.github.com/repos/${state.repo}/contents/data/${filename}?ref=main&t=${Date.now()}`;
      const res = await fetch(apiUrl, {
        headers: {
          "Authorization": `token ${state.githubToken}`,
          "Accept": "application/vnd.github.v3.raw",
        },
      });
      if (res.ok) return await res.json();
    } else {
      const rawUrl = `https://raw.githubusercontent.com/${state.repo}/main/data/${filename}?t=${Date.now()}`;
      const res = await fetch(rawUrl);
      if (res.ok) return await res.json();
    }
  } catch (e) {
    // File may not exist yet
  }
  return null;
}

async function fetchLastCommandReceipt() {
  return fetchDataJson("last_command.json");
}

function readAutopilotFormValues() {
  return {
    t_min_c: parseFloat(document.getElementById("apTMin").value),
    t_max_c: parseFloat(document.getElementById("apTMax").value),
    t_emergency_c: parseFloat(document.getElementById("apTEmergency").value),
    target_lwt_delta_k: parseFloat(document.getElementById("apDeltaLwt").value),
    max_cycle_minutes: parseInt(document.getElementById("apMaxCycle").value, 10),
    puffer_drain_minutes: parseInt(document.getElementById("apDrainMin").value, 10),
    cop_window_start: document.getElementById("apWinStart").value || "11:00",
    cop_window_end: document.getElementById("apWinEnd").value || "16:00",
    dynamic_cron_enabled: Boolean(document.getElementById("apDynamicCron").checked),
  };
}

function bindAutopilotButtons() {
  const synBanner = document.getElementById("autopilotSynopticBanner");
  if (synBanner) {
    synBanner.addEventListener("click", () => {
      const cmdTabBtn = document.querySelector('.nav-item[data-tab="tab-commands"]');
      if (cmdTabBtn) cmdTabBtn.click();
    });
  }

  const btnAway = document.getElementById("btnActivateFullAutoAway");
  if (btnAway) {
    btnAway.addEventListener("click", () => {
      const vals = readAutopilotFormValues();
      if (isNaN(vals.t_min_c) || isNaN(vals.t_max_c) || vals.t_max_c <= vals.t_min_c) {
        showToast("⚠️ T_max deve essere maggiore di T_min.");
        return;
      }
      const promptMsg = cmdState.autopilotEnabled
        ? `L'Autopilota è già attivo (${cmdState.autopilotState}). Ri-applicare i fail-safe hardware e i parametri attuali (fascia ${vals.cop_window_start}–${vals.cop_window_end}, avvio ≤ ${vals.t_min_c.toFixed(1)} °C)?`
        : `Attivare CUSTODIA AUTOMATICA MONTAGNA (Full-Auto)?\nMetterà subito la PdC in Standby (fascia sicurezza ${vals.cop_window_start}–${vals.cop_window_end}), BTicino in Antigelo (7.0 °C) e gestirà automaticamente cicli lunghi se T casa scende sotto ${vals.t_min_c.toFixed(1)} °C.`;
      requestCommandConfirm("autopilot_activate_away", vals, promptMsg, null);
    });
  }

  const btnDisable = document.getElementById("btnDisableAutopilot");
  if (btnDisable) {
    btnDisable.addEventListener("click", () => {
      if (!cmdState.autopilotEnabled) {
        showToast("ℹ️ L'Autopilota è già disattivato (controllo manuale).");
        return;
      }
      requestCommandConfirm(
        "autopilot_configure",
        { enabled: false },
        "Disattivare l'Autopilota Full-Auto e tornare al controllo manuale?",
        null
      );
    });
  }

  const btnSave = document.getElementById("btnSaveAutopilotConfig");
  if (btnSave) {
    btnSave.addEventListener("click", () => {
      const vals = readAutopilotFormValues();
      if (isNaN(vals.t_min_c) || isNaN(vals.t_max_c) || vals.t_max_c <= vals.t_min_c) {
        showToast("⚠️ T_max deve essere maggiore di T_min.");
        return;
      }
      requestCommandConfirm(
        "autopilot_configure",
        vals,
        `Salvare i nuovi parametri dell'Autopilota (Avvio ${vals.t_min_c}°C → Stacco ${vals.t_max_c}°C, Emergenza ${vals.t_emergency_c}°C, ΔT LWT +${vals.target_lwt_delta_k}K)?`,
        null
      );
    });
  }

  const btnTestCron = document.getElementById("btnTestCronjob");
  if (btnTestCron) {
    btnTestCron.addEventListener("click", () => {
      requestCommandConfirm(
        "cronjob_test",
        { roundtrip_2m: false },
        "Verificare in sola lettura su GitHub Actions che i secrets CRONJOB_API_KEY e CRONJOB_ID funzionino su cron-job.org? (Nessuna modifica a PdC, BTicino o orari.)",
        null
      );
    });
  }

  const btnTestCron2m = document.getElementById("btnTestCronjobRoundtrip");
  if (btnTestCron2m) {
    btnTestCron2m.addEventListener("click", () => {
      requestCommandConfirm(
        "cronjob_test",
        { roundtrip_2m: true },
        "Eseguire il test completo di scrittura timer 2 min su cron-job.org?\nScriverà temporaneamente [0,2,4...58] (30 slot/ora), rileggerà per conferma e ripristinerà subito lo schedule precedente. Nessuna modifica a PdC o BTicino.",
        null
      );
    });
  }
}

async function refreshAutopilotStatus() {
  let cfg = null;
  let st = null;
  if (state.backendConnected) {
    try {
      const res = await fetch("./api/autopilot");
      const data = await res.json();
      if (data && data.success) {
        cfg = data.config;
        st = data.state;
      }
    } catch (e) {}
  }
  if (!cfg) cfg = await fetchDataJson("autopilot_config.json");
  if (!st) st = await fetchDataJson("autopilot_state.json");
  if (cfg || st) {
    renderAutopilotUI(cfg || {}, st || {});
  }
}

function renderAutopilotUI(cfg, st) {
  const enabled = Boolean(cfg.enabled);
  const stateCode = enabled ? (st.state || "IDLE") : "DISABLED";
  cmdState.autopilotEnabled = enabled;
  cmdState.autopilotState = stateCode;

  const tMin = cfg.t_min_c != null ? Number(cfg.t_min_c).toFixed(1) : "7.5";

  const badge = document.getElementById("autopilotStatusBadge");
  if (badge) {
    badge.textContent = stateCode;
    badge.classList.remove("synced", "pending", "state-heating", "state-drain");
    if (stateCode === "HEATING_SYNC") badge.classList.add("state-heating");
    else if (stateCode === "PUFFER_DRAIN") badge.classList.add("state-drain");
    else if (stateCode === "ARMED") badge.classList.add("pending");
    else if (enabled) badge.classList.add("synced");
  }

  const btnAway = document.getElementById("btnActivateFullAutoAway");
  if (btnAway) {
    btnAway.classList.toggle("is-active", enabled);
    if (!enabled) {
      btnAway.textContent = `🛡️ ATTIVA ASSENZA MONTAGNA (Full-Auto ${tMin} °C)`;
    } else if (stateCode === "ARMED") {
      btnAway.textContent = "🟠 ASSENZA ATTIVA — ARMATO (Attesa COP)";
    } else if (stateCode === "HEATING_SYNC") {
      btnAway.textContent = "🔥 ASSENZA ATTIVA — RISCALDAMENTO IN CORSO";
    } else if (stateCode === "PUFFER_DRAIN") {
      btnAway.textContent = "💧 ASSENZA ATTIVA — SCARICO PUFFER";
    } else {
      btnAway.textContent = `✅ ASSENZA ATTIVA (Standby · Avvio ≤ ${tMin} °C)`;
    }
  }

  const btnDisable = document.getElementById("btnDisableAutopilot");
  if (btnDisable) {
    btnDisable.disabled = !enabled;
    btnDisable.style.opacity = enabled ? "1" : "0.55";
    btnDisable.textContent = enabled ? "✋ Disattiva (Torna Manuale)" : "✋ Già in Manuale";
    btnDisable.classList.toggle("btn-danger", enabled);
    btnDisable.classList.toggle("btn-secondary", !enabled);
  }

  const reasonEl = document.getElementById("autopilotStateReason");
  if (reasonEl && st.last_action_reason) {
    reasonEl.textContent = st.last_action_reason;
  }

  const slopeEl = document.getElementById("apMetricSlope");
  const lwtEl = document.getElementById("apMetricLwt");
  const cronEl = document.getElementById("apMetricCron");
  if (slopeEl) {
    const slp = st.indoor_slope_c_per_h != null ? Number(st.indoor_slope_c_per_h).toFixed(2) : "--";
    slopeEl.textContent = `Pendenza: ${Number(slp) >= 0 ? "+" : ""}${slp} °C/h`;
  }
  if (lwtEl) {
    lwtEl.textContent = st.calculated_target_lwt_c != null
      ? `Target LWT Auto: ${Number(st.calculated_target_lwt_c).toFixed(1)} °C`
      : "Target LWT Auto: -- °C";
  }
  if (cronEl) {
    cronEl.textContent = st.current_cron_interval_min != null
      ? `Polling: ${st.current_cron_interval_min} min`
      : "Polling: -- min";
  }

  const synBanner = document.getElementById("autopilotSynopticBanner");
  const synText = document.getElementById("autopilotSynopticText");
  if (synBanner && synText) {
    synBanner.classList.toggle("active", enabled);
    synBanner.classList.toggle("inactive", !enabled);
    if (enabled) {
      synText.textContent = `🛡️ AUTOPILOTA FULL-AUTO: ATTIVO (${stateCode} • Avvio ≤ ${tMin} °C)`;
    } else {
      synText.textContent = "🤖 AUTOPILOTA: DISATTIVATO (Tocca per attivare Custodia Montagna)";
    }
  }

  // Hydrate tuning drawer unless user is currently focused inside it
  const activeEl = document.activeElement;
  const isEditingAp = activeEl && activeEl.id && activeEl.id.startsWith("ap");
  if (!isEditingAp) {
    const mapVals = {
      apTMin: cfg.t_min_c,
      apTMax: cfg.t_max_c,
      apTEmergency: cfg.t_emergency_c,
      apDeltaLwt: cfg.target_lwt_delta_k,
      apMaxCycle: cfg.max_cycle_minutes,
      apDrainMin: cfg.puffer_drain_minutes,
      apWinStart: cfg.cop_window_start,
      apWinEnd: cfg.cop_window_end,
    };
    for (const [elId, val] of Object.entries(mapVals)) {
      const el = document.getElementById(elId);
      if (el && val != null) el.value = val;
    }
    const chk = document.getElementById("apDynamicCron");
    if (chk && cfg.dynamic_cron_enabled != null) chk.checked = Boolean(cfg.dynamic_cron_enabled);
  }
}

async function pollCommandReceipt(sinceMs) {
  for (let attempt = 0; attempt < 11; attempt++) {
    await new Promise(r => setTimeout(r, attempt === 0 ? 10000 : 6000));
    const receipt = await fetchLastCommandReceipt();
    if (receipt && receipt.timestamp_utc) {
      const rTs = new Date(receipt.timestamp_utc).getTime();
      if (!isNaN(rTs) && rTs >= (sinceMs - 5000)) {
        return receipt;
      }
    }
  }
  return null;
}

async function refreshLastCommandReceipt() {
  updateCommandsTransportUI();
  const receipt = await fetchLastCommandReceipt();
  if (!receipt) return;
  const cls = receipt.success ? "ok" : "err";
  const icon = receipt.success ? "✅" : "❌";
  setReceiptBanner(cls, `${icon} Ultimo (${formatReceiptTime(receipt.timestamp_utc)} · ${receipt.command}): ${receipt.message}`);
}

function formatReceiptTime(tsIso) {
  if (!tsIso) return "--:--";
  const d = new Date(tsIso);
  if (isNaN(d.getTime())) return "--:--";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}
