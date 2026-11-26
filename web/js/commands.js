/**
 * Bidirectional Remote Control Controller for Vitocal 111-S & BTicino Smarther.
 * Routes commands to local Flask API when on LAN Wi-Fi, or securely via
 * GitHub Actions workflow_dispatch (apply_command.yml) when running over 4G/5G.
 */

const CUSTOM_PROFILES_KEY = "vitocal_custom_profiles";
const SAVED_SCHEDULES_KEY = "vitocal_saved_schedules";
const GH_CLIENT_CALLS_KEY = "vitocal_gh_client_calls";

const BUILTIN_PROFILES = {
  standby_hg: {
    summary: "Mettere Vitocal in STANDBY, BTicino in ANTIGELO (Grundfos spenta) e mettere in pausa l'Autopilota?",
    params: {
      profile_name: "Tutto Standby / Antigelo",
      autopilot_enabled: false,
      pdc_mode: "standby",
      bticino_mode: "hg",
    },
  },
  cop_day: {
    summary: "Attivare Carica Diurna Alto COP: PdC 11:00–16:00 (14°C, Risc+ACS) e BTicino 18.0°C per 5h (Grundfos accesa)?",
    params: {
      profile_name: "Carica Diurna Alto COP",
      autopilot_enabled: false,
      pdc_mode: "dhwAndHeating",
      pdc_reduced: 14,
      pdc_normal: 14,
      pdc_schedule: { days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start: "11:00", end: "16:00", mode: "reduced", clear: false },
      bticino_mode: "manual",
      bticino_temp: 18.0,
      bticino_duration_minutes: 300,
    },
  },
  preheat_arrival: {
    summary: "Avviare Pre-Riscaldamento Arrivo: PdC 07:00–22:00 (18°C, ACS 45°C) e BTicino 20.0°C per 4h (Grundfos attiva)?",
    params: {
      profile_name: "Pre-Riscaldamento Arrivo",
      autopilot_enabled: false,
      pdc_mode: "dhwAndHeating",
      pdc_normal: 18,
      pdc_reduced: 18,
      pdc_dhw: 45,
      pdc_schedule: { days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start: "07:00", end: "22:00", mode: "normal", clear: false },
      bticino_mode: "manual",
      bticino_temp: 20.0,
      bticino_duration_minutes: 240,
    },
  },
  comfort_modulate: {
    summary: "Attivare Comfort Modulante Anti-ON/OFF: PdC 07:00–22:00 (20°/17°C, ACS 45°C) e consenso Grundfos attivo 12h (22.0°C)?",
    params: {
      profile_name: "Comfort Modulante Anti-ON/OFF",
      autopilot_enabled: false,
      pdc_mode: "dhwAndHeating",
      pdc_normal: 20,
      pdc_reduced: 17,
      pdc_dhw: 45,
      pdc_schedule: { days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start: "07:00", end: "22:00", mode: "normal", clear: false },
      bticino_mode: "manual",
      bticino_temp: 22.0,
      bticino_duration_minutes: 720,
    },
  },
};

function trackClientGithubCall(count = 1) {
  try {
    const now = Date.now();
    const cutoff = now - 24 * 3600 * 1000;
    const raw = JSON.parse(localStorage.getItem(GH_CLIENT_CALLS_KEY) || "[]");
    const list = Array.isArray(raw) ? raw.filter(ts => typeof ts === "number" && ts >= cutoff) : [];
    for (let i = 0; i < count; i++) list.push(now);
    localStorage.setItem(GH_CLIENT_CALLS_KEY, JSON.stringify(list.slice(-1000)));
  } catch (e) {}
}
window.trackClientGithubCall = trackClientGithubCall;

const cmdState = {
  initialized: false,
  hydratedOnce: false,
  isSending: false,
  autopilotEnabled: false,
  autopilotState: "DISABLED",
  lastAutopilotConfig: null,
  lastAutopilotState: null,
  pendingAction: null,
  saveModalMode: null,
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
  bindSchedulePlannerUI();
  bindProfileButtons();
  bindSaveProfileModal();
  bindCommandButtons();
  bindAutopilotButtons();
  bindConfirmModal();
  updateCommandsTransportUI();
  updateCronQuotaPreview();
  renderApiQuotaMonitor();
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

  const gfLiveBadge = document.getElementById("bticinoGrundfosLiveBadge");
  if (gfLiveBadge) {
    const gfOn = sample.grundfos_pump_active === 1;
    gfLiveBadge.textContent = gfOn ? "💧 Grundfos: ACCESA (Consenso attivo)" : "⏸ Grundfos: SPENTA (Standby)";
    gfLiveBadge.style.color = gfOn ? "#6ee7b7" : "#94a3b8";
  }

  cmdState.hydratedOnce = true;
  updateCurvePreview();
  updateCommandLeds();
  renderApiQuotaMonitor();
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

function getSelectedScheduleDays() {
  const chips = document.querySelectorAll("#schedDayPills .sched-day-chip.active");
  const out = [];
  chips.forEach(c => {
    if (c.dataset.day) out.push(c.dataset.day);
  });
  return out;
}

function setSelectedScheduleDays(days) {
  const allow = new Set(days || []);
  document.querySelectorAll("#schedDayPills .sched-day-chip").forEach(c => {
    c.classList.toggle("active", allow.has(c.dataset.day));
  });
}

function hhmmToMinutes(hhmm) {
  const parts = String(hhmm || "00:00").split(":");
  return (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
}

function updateScheduleTimelineUI() {
  const startEl = document.getElementById("cmdSchedStart");
  const endEl = document.getElementById("cmdSchedEnd");
  const modeEl = document.getElementById("cmdSchedMode");
  const blockEl = document.getElementById("pdcScheduleBlock");
  const sumEl = document.getElementById("pdcScheduleSummaryText");
  if (!startEl || !endEl || !blockEl) return;

  const start = startEl.value || "11:00";
  const end = endEl.value || "16:00";
  const mode = modeEl ? modeEl.value : "reduced";
  const m1 = hhmmToMinutes(start);
  const m2 = hhmmToMinutes(end);
  const days = getSelectedScheduleDays();

  if (m2 <= m1) {
    blockEl.style.left = "0%";
    blockEl.style.width = "0%";
    blockEl.textContent = "";
    if (sumEl) sumEl.textContent = "⚠️ Orario fine deve seguire l'inizio.";
    return;
  }

  const leftPct = (m1 / 1440) * 100;
  const widthPct = ((m2 - m1) / 1440) * 100;
  blockEl.style.left = `${leftPct.toFixed(2)}%`;
  blockEl.style.width = `${widthPct.toFixed(2)}%`;
  blockEl.textContent = widthPct >= 14 ? `${start}–${end}` : "";
  blockEl.classList.toggle("is-normal", mode === "normal");

  if (sumEl) {
    const durH = ((m2 - m1) / 60).toFixed(1).replace(/\.0$/, "");
    const modeLabel = mode === "normal" ? "Normale" : "Ridotta";
    const daysLabel = days.length === 7 ? "Tutti i giorni" : `${days.length} gg (${days.join(", ")})`;
    sumEl.textContent = `${daysLabel} · ${start}–${end} (${durH}h, ${modeLabel}) · Fuori fascia: Standby`;
  }
}

function bindSchedulePlannerUI() {
  document.querySelectorAll("#schedDayPills .sched-day-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("active");
      updateScheduleTimelineUI();
    });
  });

  for (const id of ["cmdSchedStart", "cmdSchedEnd", "cmdSchedMode"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", updateScheduleTimelineUI);
  }

  document.querySelectorAll(".sched-quick-tpl").forEach(btn => {
    btn.addEventListener("click", () => {
      const sEl = document.getElementById("cmdSchedStart");
      const eEl = document.getElementById("cmdSchedEnd");
      const mEl = document.getElementById("cmdSchedMode");
      if (sEl && btn.dataset.start) sEl.value = btn.dataset.start;
      if (eEl && btn.dataset.end) eEl.value = btn.dataset.end;
      if (mEl && btn.dataset.mode) mEl.value = btn.dataset.mode;
      updateScheduleTimelineUI();
    });
  });

  const btnSaveSched = document.getElementById("btnSaveSchedulePreset");
  if (btnSaveSched) {
    btnSaveSched.addEventListener("click", () => openSaveProfileModal("schedule"));
  }

  renderSavedSchedulePresets();
  updateScheduleTimelineUI();
}

function loadJsonList(storageKey) {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch (e) {
    return [];
  }
}

function saveJsonList(storageKey, arr) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(arr));
  } catch (e) {}
}

function renderSavedSchedulePresets() {
  const wrap = document.getElementById("savedSchedulePresets");
  if (!wrap) return;
  const list = loadJsonList(SAVED_SCHEDULES_KEY);
  if (!list.length) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = list.map((item, idx) => `
    <span class="saved-chip-item">
      <button type="button" class="saved-chip-apply" data-sched-idx="${idx}">🗓️ ${item.name} (${item.start}–${item.end})</button>
      <button type="button" class="saved-chip-del" data-sched-del="${idx}" title="Elimina">×</button>
    </span>
  `).join("");

  wrap.querySelectorAll("[data-sched-idx]").forEach(btn => {
    btn.addEventListener("click", () => {
      const item = loadJsonList(SAVED_SCHEDULES_KEY)[parseInt(btn.dataset.schedIdx, 10)];
      if (!item) return;
      setSelectedScheduleDays(item.days || ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);
      const sEl = document.getElementById("cmdSchedStart");
      const eEl = document.getElementById("cmdSchedEnd");
      const mEl = document.getElementById("cmdSchedMode");
      const syncEl = document.getElementById("cmdSchedSyncGrundfos");
      if (sEl) sEl.value = item.start;
      if (eEl) eEl.value = item.end;
      if (mEl) mEl.value = item.mode || "reduced";
      if (syncEl && item.syncGrundfos != null) syncEl.checked = Boolean(item.syncGrundfos);
      updateScheduleTimelineUI();
      showToast(`🗓️ Caricato orario "${item.name}"`);
    });
  });

  wrap.querySelectorAll("[data-sched-del]").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.schedDel, 10);
      const cur = loadJsonList(SAVED_SCHEDULES_KEY);
      cur.splice(idx, 1);
      saveJsonList(SAVED_SCHEDULES_KEY, cur);
      renderSavedSchedulePresets();
    });
  });
}

function bindProfileButtons() {
  document.querySelectorAll("[data-builtin-profile]").forEach(btn => {
    btn.addEventListener("click", () => {
      const prof = BUILTIN_PROFILES[btn.dataset.builtinProfile];
      if (!prof) return;
      requestCommandConfirm("apply_full_profile", prof.params, prof.summary, "all");
    });
  });

  const btnSaveProf = document.getElementById("btnSaveCustomProfile");
  if (btnSaveProf) {
    btnSaveProf.addEventListener("click", () => openSaveProfileModal("profile"));
  }

  const btnQuickArrival = document.getElementById("btnQuickPreheatArrival");
  if (btnQuickArrival) {
    btnQuickArrival.addEventListener("click", () => {
      const prof = BUILTIN_PROFILES.preheat_arrival;
      if (prof) requestCommandConfirm("apply_full_profile", prof.params, prof.summary, "all");
    });
  }

  renderCustomProfiles();
}

function renderCustomProfiles() {
  const wrap = document.getElementById("customProfilesList");
  if (!wrap) return;
  const list = loadJsonList(CUSTOM_PROFILES_KEY);
  if (!list.length) {
    wrap.innerHTML = '<span class="cmd-muted-note">Nessun profilo personalizzato salvato.</span>';
    return;
  }
  wrap.innerHTML = list.map((p, idx) => `
    <span class="saved-chip-item">
      <button type="button" class="saved-chip-apply" data-prof-idx="${idx}">⭐ ${p.name}</button>
      <button type="button" class="saved-chip-del" data-prof-del="${idx}" title="Elimina">×</button>
    </span>
  `).join("");

  wrap.querySelectorAll("[data-prof-idx]").forEach(btn => {
    btn.addEventListener("click", () => {
      const item = loadJsonList(CUSTOM_PROFILES_KEY)[parseInt(btn.dataset.profIdx, 10)];
      if (!item || !item.params) return;
      const summary = `Applicare profilo salvato "${item.name}" (PdC ${item.params.pdc_mode}, T=${item.params.pdc_normal}/${item.params.pdc_reduced}°C, BTicino ${item.params.bticino_temp || item.params.bticino_mode})?`;
      requestCommandConfirm("apply_full_profile", item.params, summary, "all");
    });
  });

  wrap.querySelectorAll("[data-prof-del]").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.profDel, 10);
      const cur = loadJsonList(CUSTOM_PROFILES_KEY);
      cur.splice(idx, 1);
      saveJsonList(CUSTOM_PROFILES_KEY, cur);
      renderCustomProfiles();
    });
  });
}

function openSaveProfileModal(mode) {
  cmdState.saveModalMode = mode;
  const modal = document.getElementById("saveProfileModal");
  const titleEl = document.getElementById("saveProfileModalTitle");
  const hintEl = document.getElementById("saveProfileModalHint");
  const inp = document.getElementById("inputSaveProfileName");
  if (!modal) return;
  if (mode === "schedule") {
    if (titleEl) titleEl.textContent = "🗓️ Salva Preset Fascia Oraria";
    if (hintEl) hintEl.textContent = "Salva giorni, orario inizio/fine e coordinazione pompa Grundfos per richiamarli in 1 tocco.";
    if (inp) inp.value = "";
  } else {
    if (titleEl) titleEl.textContent = "⭐ Salva Profilo Impianto Completo";
    if (hintEl) hintEl.textContent = "Salva curva, temperature PdC, fascia oraria e consenso pompa BTicino attualmente impostati a video.";
    if (inp) inp.value = "";
  }
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  if (inp) setTimeout(() => inp.focus(), 40);
}

function closeSaveProfileModal() {
  const modal = document.getElementById("saveProfileModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  cmdState.saveModalMode = null;
}

function bindSaveProfileModal() {
  const modal = document.getElementById("saveProfileModal");
  if (!modal || modal.dataset.bound === "1") return;
  modal.dataset.bound = "1";

  const closeBtn = document.getElementById("btnCloseSaveProfileModal");
  const cancelBtn = document.getElementById("btnCancelSaveProfile");
  const confirmBtn = document.getElementById("btnConfirmSaveProfile");
  if (closeBtn) closeBtn.addEventListener("click", closeSaveProfileModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeSaveProfileModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeSaveProfileModal();
  });

  if (confirmBtn) {
    confirmBtn.addEventListener("click", () => {
      const nameEl = document.getElementById("inputSaveProfileName");
      const name = (nameEl ? nameEl.value : "").trim();
      if (!name) {
        showToast("⚠️ Inserisci un nome per il preset.");
        return;
      }

      if (cmdState.saveModalMode === "schedule") {
        const days = getSelectedScheduleDays();
        const start = document.getElementById("cmdSchedStart").value;
        const end = document.getElementById("cmdSchedEnd").value;
        const mode = document.getElementById("cmdSchedMode").value;
        const syncGrundfos = Boolean(document.getElementById("cmdSchedSyncGrundfos").checked);
        const list = loadJsonList(SAVED_SCHEDULES_KEY);
        list.push({ name, days, start, end, mode, syncGrundfos });
        saveJsonList(SAVED_SCHEDULES_KEY, list);
        renderSavedSchedulePresets();
        showToast(`✅ Orario "${name}" salvato!`);
      } else {
        const days = getSelectedScheduleDays();
        const start = document.getElementById("cmdSchedStart").value;
        const end = document.getElementById("cmdSchedEnd").value;
        const schedMode = document.getElementById("cmdSchedMode").value;
        const btTemp = Number(parseFloat(document.getElementById("cmdBticinoTemp").value).toFixed(1));
        const btDur = parseInt(document.getElementById("cmdBticinoDuration").value, 10) || 180;
        const params = {
          profile_name: name,
          autopilot_enabled: false,
          pdc_mode: document.getElementById("cmdPdcModeSelect").value,
          curve_slope: Number(parseFloat(document.getElementById("cmdSlopeInput").value).toFixed(1)),
          curve_shift: parseInt(document.getElementById("cmdShiftInput").value, 10),
          pdc_normal: parseInt(document.getElementById("cmdTempNormal").value, 10),
          pdc_reduced: parseInt(document.getElementById("cmdTempReduced").value, 10),
          pdc_dhw: parseInt(document.getElementById("cmdTempDhw").value, 10),
          pdc_schedule: { days: days.length ? days : ["mon","tue","wed","thu","fri","sat","sun"], start, end, mode: schedMode, clear: false },
          bticino_mode: btTemp <= 7.0 ? "hg" : "manual",
          ...(btTemp > 7.0 ? { bticino_temp: btTemp, bticino_duration_minutes: btDur } : {}),
        };
        const list = loadJsonList(CUSTOM_PROFILES_KEY);
        list.push({ name, params });
        saveJsonList(CUSTOM_PROFILES_KEY, list);
        renderCustomProfiles();
        showToast(`✅ Profilo "${name}" salvato!`);
      }
      closeSaveProfileModal();
    });
  }
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

  // Viessmann Schedule (Visual 24h Planner + Optional Grundfos Interlock)
  const btnSched = document.getElementById("btnSendPdcSchedule");
  if (btnSched) {
    btnSched.addEventListener("click", () => {
      const days = getSelectedScheduleDays();
      if (!days.length) {
        showToast("⚠️ Seleziona almeno un giorno della settimana.");
        return;
      }
      const start = document.getElementById("cmdSchedStart").value;
      const end = document.getElementById("cmdSchedEnd").value;
      const mode = document.getElementById("cmdSchedMode").value;
      if (start >= end) {
        showToast("⚠️ L'orario di fine deve essere successivo all'inizio.");
        return;
      }
      const syncGf = Boolean(document.getElementById("cmdSchedSyncGrundfos") && document.getElementById("cmdSchedSyncGrundfos").checked);
      if (syncGf) {
        const durMin = Math.max(60, Math.min(720, hhmmToMinutes(end) - hhmmToMinutes(start)));
        const btTarget = Math.max(18.0, parseFloat(document.getElementById("cmdBticinoTemp").value) || 18.0);
        requestCommandConfirm(
          "apply_full_profile",
          {
            profile_name: `Fascia ${start}–${end} + Grundfos`,
            pdc_mode: "dhwAndHeating",
            pdc_schedule: { days, start, end, mode, clear: false },
            bticino_mode: "manual",
            bticino_temp: btTarget,
            bticino_duration_minutes: durMin,
          },
          `Applicare fascia PdC (${days.join(", ")}) ${start}–${end} (${mode}) E attivare il consenso pompa BTicino (${btTarget.toFixed(1)} °C per ${durMin} min) per modulare senza tagli?`,
          "all"
        );
      } else {
        requestCommandConfirm(
          "viessmann_schedule",
          { days, start, end, mode, clear: false },
          `Impostare fascia oraria PdC (${days.join(", ")}) dalle ${start} alle ${end} in modalità "${mode}"?`,
          null
        );
      }
    });
  }

  const btnClearSched = document.getElementById("btnClearPdcSchedule");
  if (btnClearSched) {
    btnClearSched.addEventListener("click", () => {
      const days = getSelectedScheduleDays();
      if (!days.length) {
        showToast("⚠️ Seleziona almeno un giorno della settimana.");
        return;
      }
      requestCommandConfirm(
        "viessmann_schedule",
        { days, clear: true },
        `Svuotare le fasce orarie PdC per (${days.join(", ")}) lasciando il circuito in Standby?`,
        null
      );
    });
  }

  // Quick Grundfos Force Pump ON
  const btnForcePump = document.getElementById("btnBtForcePumpOn");
  if (btnForcePump) {
    btnForcePump.addEventListener("click", () => {
      requestCommandConfirm(
        "bticino_setpoint",
        { mode: "manual", temp: 20.0, duration_minutes: 240 },
        "Forzare il consenso pompa Grundfos ACCESA (BTicino manuale 20.0 °C per 4 ore) affinché la PdC moduli liberamente?",
        "bticino"
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
    trackClientGithubCall(1);
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
      trackClientGithubCall(1);
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

function clampInt(val, min, max, fallback) {
  const n = parseInt(val, 10);
  if (isNaN(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function readAutopilotFormValues() {
  return {
    t_min_c: parseFloat(document.getElementById("apTMin").value),
    t_max_c: parseFloat(document.getElementById("apTMax").value),
    t_emergency_c: parseFloat(document.getElementById("apTEmergency").value),
    target_lwt_delta_k: parseFloat(document.getElementById("apDeltaLwt").value),
    min_target_lwt_c: parseFloat(document.getElementById("apMinLwt")?.value || "22.5"),
    max_target_lwt_c: parseFloat(document.getElementById("apMaxLwt")?.value || "26.5"),
    max_cycle_minutes: parseInt(document.getElementById("apMaxCycle").value, 10),
    puffer_drain_minutes: parseInt(document.getElementById("apDrainMin").value, 10),
    cop_window_start: document.getElementById("apWinStart").value || "11:00",
    cop_window_end: document.getElementById("apWinEnd").value || "16:00",
    soft_start_enabled: Boolean(document.getElementById("apSoftStartEnabled")?.checked),
    soft_start_step_minutes: clampInt(document.getElementById("apSoftStartStep")?.value, 10, 60, 25),
    soft_start_min_lwt_c: parseFloat(document.getElementById("apSoftStartMinLwt")?.value || "21.8"),
    defrost_guard_enabled: Boolean(document.getElementById("apDefrostGuardEnabled")?.checked),
    defrost_trim_threshold_count: clampInt(document.getElementById("apDefrostThresh")?.value, 1, 5, 2),
    defrost_guard_oat_max_c: parseFloat(document.getElementById("apDefrostOatMax")?.value || "5.5"),
    defrost_min_safe_lwt_c: parseFloat(document.getElementById("apDefrostMinSafeLwt")?.value || "22.0"),
    defrost_min_delta_k: parseFloat(document.getElementById("apDefrostMinDeltaK")?.value || "13.5"),
    inverter_min_mod_pct: clampInt(document.getElementById("apInverterMinMod")?.value, 20, 55, 38),
    anti_seize_days: clampInt(document.getElementById("apAntiSeizeDays")?.value, 0, 30, 4),
    dynamic_cron_enabled: Boolean(document.getElementById("apDynamicCron").checked),
    cron_idle_minutes: clampInt(document.getElementById("apCronIdle")?.value, 1, 60, 15),
    cron_armed_minutes: clampInt(document.getElementById("apCronArmed")?.value, 1, 30, 5),
    cron_active_minutes: clampInt(document.getElementById("apCronActive")?.value, 1, 15, 1),
    soft_curve_tuning_enabled: Boolean(document.getElementById("apSoftCurveTuning")?.checked),
    adaptive_model_enabled: Boolean(document.getElementById("apAdaptiveModelEnabled")?.checked),
    adaptive_model_apply_targets: Boolean(document.getElementById("apAdaptiveModelApply")?.checked),
    weather_planner_enabled: Boolean(document.getElementById("apWeatherPlannerEnabled")?.checked),
    weather_dynamic_window_enabled: Boolean(document.getElementById("apWeatherDynamicWindow")?.checked),
    anti_short_cycle_enabled: Boolean(document.getElementById("apAntiShortCycleEnabled")?.checked),
    predictive_prearm_enabled: Boolean(document.getElementById("apPredictivePrearmEnabled")?.checked),
    weather_defer_enabled: Boolean(document.getElementById("apWeatherDeferEnabled")?.checked),
    weather_search_start: document.getElementById("apWeatherSearchStart")?.value || "09:00",
    weather_search_end: document.getElementById("apWeatherSearchEnd")?.value || "18:00",
    weather_window_hours: clampInt(document.getElementById("apWeatherWindowHours")?.value, 2, 9, 5),
    min_cycle_minutes: clampInt(document.getElementById("apMinCycleMin")?.value, 45, 240, 120),
    max_window_extension_minutes: clampInt(document.getElementById("apMaxWinExtMin")?.value, 0, 240, 120),
    prearm_max_above_tmin_c: parseFloat(document.getElementById("apPrearmMaxAbove")?.value || "0.6"),
    prearm_emergency_margin_c: parseFloat(document.getElementById("apPrearmEmergMargin")?.value || "0.4"),
    weather_arbitrage_cop_delta: parseFloat(document.getElementById("apWeatherArbDelta")?.value || "0.25"),
    weather_min_cop_gain: parseFloat(document.getElementById("apWeatherMinGain")?.value || "0.08"),
    weather_refresh_hours: clampInt(document.getElementById("apWeatherRefreshH")?.value, 1, 12, 3),
    min_cycle_end_temp_c: parseFloat(document.getElementById("apMinEndTemp")?.value || "8.2"),
    window_lock_before_start_minutes: clampInt(document.getElementById("apWinLockMin")?.value, 15, 240, 90),
  };
}

function updateCronQuotaPreview() {
  const el = document.getElementById("apCronQuotaPreview");
  if (!el) return;
  const idleMin = clampInt(document.getElementById("apCronIdle")?.value, 1, 60, 15);
  const actMin = clampInt(document.getElementById("apCronActive")?.value, 1, 15, 2);
  const idleCalls24 = Math.round((1440 / idleMin) * 2);
  const actCalls24 = Math.round((1440 / actMin) * 2);
  const pctIdle = ((idleCalls24 / 1450) * 100).toFixed(0);
  const warn = idleCalls24 > 1100;
  el.textContent = `Stima polling Viessmann: ~${idleCalls24}/24h in IDLE (${pctIdle}% quota) · max ~${actCalls24}/24h se attivo h24 (limite 1.450/24h)`;
  el.style.color = warn ? "#fbbf24" : "#bae6fd";
}

function bindAutopilotButtons() {
  const synHeader = document.getElementById("autopilotSynopticHeader") || document.getElementById("autopilotSynopticBanner");
  if (synHeader) {
    synHeader.addEventListener("click", () => {
      const cmdTabBtn = document.querySelector('.nav-item[data-tab="tab-commands"]');
      if (cmdTabBtn) cmdTabBtn.click();
    });
  }

  const btnSynWx = document.getElementById("btnSynWxOpenCommands");
  if (btnSynWx) {
    btnSynWx.addEventListener("click", () => {
      const cmdTabBtn = document.querySelector('.nav-item[data-tab="tab-commands"]');
      if (cmdTabBtn) cmdTabBtn.click();
      const brainDrawer = document.getElementById("apPredictiveBrainDrawer");
      if (brainDrawer) brainDrawer.open = true;
    });
  }

  for (const id of ["apCronIdle", "apCronArmed", "apCronActive"]) {
    const inp = document.getElementById(id);
    if (inp) inp.addEventListener("input", updateCronQuotaPreview);
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
        ? `L'Autopilota è già attivo (${cmdState.autopilotState}). Ri-applicare i fail-safe hardware e i parametri attuali (fascia ${vals.cop_window_start}–${vals.cop_window_end}, polling ${vals.cron_idle_minutes}/${vals.cron_armed_minutes}/${vals.cron_active_minutes}m)?`
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
        `Salvare parametri Autopilota (Avvio ${vals.t_min_c}°C → Stacco ${vals.t_max_c}°C, Polling ${vals.cron_idle_minutes}/${vals.cron_armed_minutes}/${vals.cron_active_minutes}m${vals.soft_curve_tuning_enabled ? ", Self-Tuning Soft ON" : ""})?`,
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
  const tm = await fetchDataJson("thermal_model.json");
  if (tm) cmdState.lastThermalModel = tm;
  const wf = await fetchDataJson("weather_forecast.json");
  if (wf) cmdState.lastWeatherForecast = wf;
  if (cfg || st) {
    renderAutopilotUI(cfg || {}, st || {});
  } else {
    renderApiQuotaMonitor();
  }
}

function renderAutopilotUI(cfg, st) {
  cmdState.lastAutopilotConfig = cfg;
  cmdState.lastAutopilotState = st;

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
  const winEl = document.getElementById("apMetricWindow");
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
  if (winEl) {
    const wp = st.weather_plan || (cmdState.lastWeatherForecast && cmdState.lastWeatherForecast.plan) || null;
    const wStart = st.active_window_start_local || (wp && wp.effective_window_start) || cfg.cop_window_start || "11:00";
    const wEnd = st.active_window_end_local || (wp && wp.effective_window_end) || cfg.cop_window_end || "16:00";
    winEl.textContent = `Finestra: ${wStart}–${wEnd}`;
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
      apMinLwt: cfg.min_target_lwt_c,
      apMaxLwt: cfg.max_target_lwt_c,
      apMaxCycle: cfg.max_cycle_minutes,
      apDrainMin: cfg.puffer_drain_minutes,
      apWinStart: cfg.cop_window_start,
      apWinEnd: cfg.cop_window_end,
      apSoftStartStep: cfg.soft_start_step_minutes,
      apSoftStartMinLwt: cfg.soft_start_min_lwt_c,
      apDefrostThresh: cfg.defrost_trim_threshold_count,
      apDefrostOatMax: cfg.defrost_guard_oat_max_c,
      apDefrostMinSafeLwt: cfg.defrost_min_safe_lwt_c,
      apDefrostMinDeltaK: cfg.defrost_min_delta_k,
      apInverterMinMod: cfg.inverter_min_mod_pct,
      apAntiSeizeDays: cfg.anti_seize_days,
      apCronIdle: cfg.cron_idle_minutes,
      apCronArmed: cfg.cron_armed_minutes,
      apCronActive: cfg.cron_active_minutes,
      apWeatherSearchStart: cfg.weather_search_start,
      apWeatherSearchEnd: cfg.weather_search_end,
      apWeatherWindowHours: cfg.weather_window_hours,
      apMinCycleMin: cfg.min_cycle_minutes,
      apMaxWinExtMin: cfg.max_window_extension_minutes,
      apPrearmMaxAbove: cfg.prearm_max_above_tmin_c,
      apPrearmEmergMargin: cfg.prearm_emergency_margin_c,
      apWeatherArbDelta: cfg.weather_arbitrage_cop_delta,
      apWeatherMinGain: cfg.weather_min_cop_gain,
      apWeatherRefreshH: cfg.weather_refresh_hours,
      apMinEndTemp: cfg.min_cycle_end_temp_c,
      apWinLockMin: cfg.window_lock_before_start_minutes,
    };
    for (const [elId, val] of Object.entries(mapVals)) {
      const el = document.getElementById(elId);
      if (el && val != null) el.value = val;
    }
    const chk = document.getElementById("apDynamicCron");
    if (chk && cfg.dynamic_cron_enabled != null) chk.checked = Boolean(cfg.dynamic_cron_enabled);
    const chkSs = document.getElementById("apSoftStartEnabled");
    if (chkSs && cfg.soft_start_enabled != null) chkSs.checked = Boolean(cfg.soft_start_enabled);
    const chkDg = document.getElementById("apDefrostGuardEnabled");
    if (chkDg && cfg.defrost_guard_enabled != null) chkDg.checked = Boolean(cfg.defrost_guard_enabled);
    const chkSoft = document.getElementById("apSoftCurveTuning");
    if (chkSoft && cfg.soft_curve_tuning_enabled != null) chkSoft.checked = Boolean(cfg.soft_curve_tuning_enabled);
    const chkAm = document.getElementById("apAdaptiveModelEnabled");
    if (chkAm && cfg.adaptive_model_enabled != null) chkAm.checked = Boolean(cfg.adaptive_model_enabled);
    const chkAmApply = document.getElementById("apAdaptiveModelApply");
    if (chkAmApply && cfg.adaptive_model_apply_targets != null) chkAmApply.checked = Boolean(cfg.adaptive_model_apply_targets);
    const chkWp = document.getElementById("apWeatherPlannerEnabled");
    if (chkWp && cfg.weather_planner_enabled != null) chkWp.checked = Boolean(cfg.weather_planner_enabled);
    const chkWdw = document.getElementById("apWeatherDynamicWindow");
    if (chkWdw && cfg.weather_dynamic_window_enabled != null) chkWdw.checked = Boolean(cfg.weather_dynamic_window_enabled);
    const chkAsc = document.getElementById("apAntiShortCycleEnabled");
    if (chkAsc && cfg.anti_short_cycle_enabled != null) chkAsc.checked = Boolean(cfg.anti_short_cycle_enabled);
    const chkPpa = document.getElementById("apPredictivePrearmEnabled");
    if (chkPpa && cfg.predictive_prearm_enabled != null) chkPpa.checked = Boolean(cfg.predictive_prearm_enabled);
    const chkWdf = document.getElementById("apWeatherDeferEnabled");
    if (chkWdf && cfg.weather_defer_enabled != null) chkWdf.checked = Boolean(cfg.weather_defer_enabled);
    updateCronQuotaPreview();
  }

  renderWeatherBrainUI(cfg, st, cmdState.lastWeatherForecast);
  renderSelfTuningAuditUI(st, cmdState.lastThermalModel, cmdState.lastWeatherForecast);
  renderSynopticWeatherDrawer(cfg, st, cmdState.lastWeatherForecast);

  // Render live converging physical model summary
  const tmEl = document.getElementById("apThermalModelSummary");
  if (tmEl) {
    const tm = st.thermal_model || cmdState.lastThermalModel;
    if (tm && tm.k_rad_kw_per_k != null) {
      const conf = tm.confidence_pct != null ? `${tm.confidence_pct}%` : "--";
      const cyc = tm.cycles_observed != null ? tm.cycles_observed : "--";
      const krad = Number(tm.k_rad_kw_per_k).toFixed(3);
      const flr = tm.inverter_min_mod_pct != null ? `${Number(tm.inverter_min_mod_pct).toFixed(0)}%` : "38%";
      const dDef = tm.defrost_lwt_drop_p90_k != null ? `-${Number(tm.defrost_lwt_drop_p90_k).toFixed(1)}K` : "--";
      const ua = tm.ua_building_c_24h_per_k != null ? Number(tm.ua_building_c_24h_per_k).toFixed(3) : "--";
      const recT = tm.recommended_target_lwt_c != null ? `${Number(tm.recommended_target_lwt_c).toFixed(1)} °C` : "--";
      const autH = tm.pred_autonomy_hours != null ? `~${Math.round(Number(tm.pred_autonomy_hours))}h` : "--";
      const modeLbl = cfg.adaptive_model_apply_targets ? "ATTIVO (guida target)" : "OSSERVAZIONE (stima live)";
      tmEl.textContent = `🧠 Modello [${modeLbl} · ${cyc} cicli · conf. ${conf}]: k_rad=${krad} kW/K · Floor=${flr} · ΔBPHE Defrost=${dDef} · UA=${ua} · Target stimato=${recT} (autonomia ${autH})`;
      tmEl.style.color = cfg.adaptive_model_apply_targets ? "#6ee7b7" : "#bae6fd";
    } else {
      tmEl.textContent = "🧠 Modello Fisico: k_rad≈0.344 kW/K · Floor≈38% · ΔBPHE≈-9.8K · in convergenza sui prossimi cicli.";
    }
  }

  // Refresh Synoptic & Sonde so Real Water Target / Real Room Target & WO1C logbook reflect live Autopilot config/state
  if (typeof state !== "undefined" && state.latestSample) {
    if (typeof renderSynoptic === "function") renderSynoptic(state.latestSample);
    if (typeof updateSynopticQuickCards === "function") updateSynopticQuickCards(state.latestSample);
    if (typeof renderDetailedSondeList === "function") renderDetailedSondeList(state.latestSample);
  }
  renderApiQuotaMonitor();
}

function escapeHtmlSafe(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderWeatherBrainUI(cfg, st, wf) {
  const badgeEl = document.getElementById("apWeatherSummaryBadge");
  const verdictEl = document.getElementById("apWeatherVerdict");
  const traceEl = document.getElementById("apWeatherTraceList");
  const compareEl = document.getElementById("apWeatherCompareGrid");
  const stripEl = document.getElementById("apWeatherHourlyStrip");
  const assumpEl = document.getElementById("apWeatherAssumptionsBox");
  if (!verdictEl || !traceEl || !compareEl || !stripEl || !assumpEl) return;

  const wp = (st && st.weather_plan) || (wf && wf.plan) || null;
  const effStart = (st && st.active_window_start_local) || (wp && wp.effective_window_start) || (cfg && cfg.cop_window_start) || "11:00";
  const effEnd = (st && st.active_window_end_local) || (wp && wp.effective_window_end) || (cfg && cfg.cop_window_end) || "16:00";

  if (badgeEl) {
    if (wp && wp.available && wp.today_window) {
      badgeEl.textContent = `${effStart}–${effEnd} · COP ${Number(wp.today_window.avg_cop_net).toFixed(2)}`;
      badgeEl.style.color = wp.today_window.is_dynamic_shifted ? "#6ee7b7" : "#38bdf8";
    } else {
      badgeEl.textContent = `${effStart}–${effEnd} (Statica)`;
      badgeEl.style.color = "#fbbf24";
    }
  }

  if (!wp) {
    verdictEl.textContent = `Finestra statica ${effStart}–${effEnd}. In attesa della prossima valutazione cloud.`;
    traceEl.innerHTML = "<li>Inserisci i GitHub Secrets WEATHER_LAT e WEATHER_LON (e WEATHER_ELEVATION_M) per attivare le previsioni Open-Meteo alpine.</li>";
    compareEl.innerHTML = "";
    stripEl.innerHTML = '<span class="cmd-muted-note">Nessun dato orario meteo disponibile.</span>';
    assumpEl.textContent = "Assunzioni attive: fallback finestra statica, fattore sicurezza UA × 1.15.";
    return;
  }

  verdictEl.textContent = wp.decision_summary || `Finestra attiva ${effStart}–${effEnd}`;
  const traceItems = Array.isArray(wp.decision_trace) ? wp.decision_trace : [];
  traceEl.innerHTML = traceItems.length
    ? traceItems.map(line => `<li>${escapeHtmlSafe(line)}</li>`).join("")
    : `<li>${escapeHtmlSafe(wp.fallback_reason || "Nessun dettaglio aggiuntivo.")}</li>`;

  const cards = [];
  const buildWinCard = (label, win) => {
    if (!win) {
      return `
        <div class="ap-wx-card">
          <div class="ap-wx-card-head"><span>${label}</span><span class="ap-wx-badge">N/D</span></div>
          <div class="ap-wx-card-main">--</div>
          <div class="ap-wx-card-sub">Dati meteo orari non ancora disponibili</div>
        </div>`;
    }
    const riskCls = `risk-${String(win.frost_risk || "basso").toLowerCase()}`;
    const shiftNote = win.is_dynamic_shifted
      ? `Spostata (+${Number(win.cop_gain_vs_static || 0).toFixed(2)} COP vs statica)`
      : `Allineata a statica (${win.static_start_hhmm}–${win.static_end_hhmm})`;
    return `
      <div class="ap-wx-card ${win.is_dynamic_shifted ? "is-shifted" : ""}">
        <div class="ap-wx-card-head">
          <span>${label}</span>
          <span class="ap-wx-badge ${riskCls}">Brina ${escapeHtmlSafe(win.frost_risk || "--")}</span>
        </div>
        <div class="ap-wx-card-main">${escapeHtmlSafe(win.start_hhmm)}–${escapeHtmlSafe(win.end_hhmm)} · COP ${Number(win.avg_cop_net).toFixed(2)}</div>
        <div class="ap-wx-card-sub">
          OAT ${Number(win.avg_temp_c) >= 0 ? "+" : ""}${Number(win.avg_temp_c).toFixed(1)} °C · RH ${win.avg_rh_pct}% · ${shiftNote}
        </div>
      </div>`;
  };
  cards.push(buildWinCard("📅 Oggi", wp.today_window));
  cards.push(buildWinCard("📆 Domani", wp.tomorrow_window));
  compareEl.innerHTML = cards.join("");

  const hourly = (wf && Array.isArray(wf.hourly_preview)) ? wf.hourly_preview : [];
  if (hourly.length) {
    stripEl.innerHTML = hourly.map(h => {
      const tinTxt = h.tin_proj_c != null ? `🏠 ${Number(h.tin_proj_c).toFixed(1)}°` : "";
      const rainTxt = h.precip_mm > 0.1 ? `💧${Number(h.precip_mm).toFixed(1)}` : "";
      return `
        <div class="ap-hour-pill ${h.in_window ? "in-window" : ""}" title="${escapeHtmlSafe(h.day_tag)} ${escapeHtmlSafe(h.hh)} · Brina ${escapeHtmlSafe(h.frost_risk)}">
          <span class="ap-hour-time">${escapeHtmlSafe(h.day_tag)} ${escapeHtmlSafe(h.hh)}</span>
          <span>${escapeHtmlSafe(h.icon || "🌤️")} ${Number(h.temp_c) >= 0 ? "+" : ""}${Number(h.temp_c).toFixed(1)}°</span>
          <span>RH ${h.rh_pct}% ${rainTxt}</span>
          <span class="ap-hour-cop">COP ${Number(h.cop_net).toFixed(2)}</span>
          ${tinTxt ? `<span class="ap-hour-tin">${tinTxt}</span>` : ""}
        </div>`;
    }).join("");
  } else {
    stripEl.innerHTML = `<span class="cmd-muted-note">${escapeHtmlSafe(wp.fallback_reason || "Anteprima oraria non disponibile (modalità fallback).")}</span>`;
  }

  const a = wp.assumptions || {};
  const biasStr = a.oat_bias_c != null ? `${Number(a.oat_bias_c) >= 0 ? "+" : ""}${Number(a.oat_bias_c).toFixed(2)} °C` : "0.00 °C";
  const maeStr = a.oat_mae_c != null ? `${Number(a.oat_mae_c).toFixed(2)} °C (${a.oat_samples_matched || 0}h)` : "in raccolta";
  const tinMaeStr = a.tin_projection_mae_c != null ? `${Number(a.tin_projection_mae_c).toFixed(2)} °C` : "in raccolta";
  const fetchedTxt = wf && wf.fetched_utc ? formatReceiptTime(wf.fetched_utc) : (wp.evaluated_local || "--");
  assumpEl.innerHTML =
    `<strong>Assunzioni &amp; Self-Tuning (${escapeHtmlSafe((wf && wf.model) || "Open-Meteo")})</strong><br>` +
    `• Bias OAT appreso: <strong>${biasStr}</strong> · MAE OAT: <strong>${maeStr}</strong> · MAE proiezione T_casa: <strong>${tinMaeStr}</strong><br>` +
    `• Dispersione usata: UA=${a.ua_raw_c_24h_k ?? "--"} × ${a.ua_safety_factor ?? 1.15} = <strong>${a.ua_effective_c_24h_k ?? "--"} (°C/24h)/K</strong> · ΔEvap: −${a.t_evap_offset_k ?? 7.5} K · Scala brina: ${a.frost_penalty_scale ?? 1.0}×<br>` +
    `• Pavimento notte sicuro: <strong>${a.safe_floor_c ?? "--"} °C</strong> · Ciclo min: <strong>${a.min_cycle_minutes ?? "--"} min</strong> · Arbitraggio ΔCOP: ≥ ${a.arbitrage_cop_delta ?? "--"} · Agg. ${escapeHtmlSafe(fetchedTxt)}`;
}

function renderSelfTuningAuditUI(st, tm, wf) {
  const badgeEl = document.getElementById("apAuditSummaryBadge");
  const convGrid = document.getElementById("apConvergenceGrid");
  const histList = document.getElementById("apSelfTuningHistoryList");
  const oatBox = document.getElementById("apOatVerifyBox");
  if (!convGrid || !histList || !oatBox) return;

  const model = (tm && tm.diagnostics) ? tm : ((st && st.thermal_model) ? st.thermal_model : tm);
  if (badgeEl) {
    const conf = model && model.confidence_pct != null ? `${model.confidence_pct}%` : "--";
    const cyc = model && model.cycles_observed != null ? model.cycles_observed : "--";
    badgeEl.textContent = `Conf. ${conf} · ${cyc} cicli`;
  }

  const diag = (model && model.diagnostics) || null;
  const deltas = (model && model.last_deltas) || {};
  const specs = [
    { key: "k_rad_kw_per_k", label: "k_rad Pavimento", unit: "kW/K", digits: 3 },
    { key: "inverter_min_mod_pct", label: "Floor Inverter", unit: "%", digits: 1 },
    { key: "defrost_lwt_drop_p90_k", label: "ΔBPHE Defrost (p90)", unit: "K", digits: 1 },
    { key: "ua_building_c_24h_per_k", label: "Dispersione UA", unit: "(°C/24h)/K", digits: 3 },
    { key: "alpha_heat_c_h_per_k", label: "Resa Diretta α", unit: "(°C/h)/K", digits: 4 },
  ];

  if (diag) {
    convGrid.innerHTML = specs.map(sp => {
      const d = diag[sp.key] || {};
      const valStr = d.value != null ? Number(d.value).toFixed(sp.digits) : "--";
      const priorStr = d.prior != null ? Number(d.prior).toFixed(sp.digits) : "--";
      const obsStr = d.raw_observed != null ? Number(d.raw_observed).toFixed(sp.digits) : "--";
      const wPct = Math.max(0, Math.min(100, Number(d.data_weight_pct || 0)));
      const dl = Number(deltas[sp.key] || 0);
      const changed = Math.abs(dl) >= 0.0005;
      const dlText = changed ? `${dl >= 0 ? "+" : ""}${dl.toFixed(sp.digits)}` : "invariato";
      const dlCls = changed ? "is-changed" : "";
      const barCol = wPct >= 70 ? "#10b981" : (wPct >= 45 ? "#38bdf8" : "#f59e0b");
      return `
        <div class="ap-conv-card">
          <div class="ap-conv-head">
            <span>${sp.label}</span>
            <span class="ap-delta-chip ${dlCls}">${dlText}</span>
          </div>
          <div class="ap-conv-val">${valStr} <small>${sp.unit}</small></div>
          <div class="ap-conv-bar-bg"><div class="ap-conv-bar-fill" style="width:${Math.max(4, wPct)}%; background:${barCol};"></div></div>
          <div class="ap-conv-meta">
            <span>Prior ${priorStr} · Obs ${obsStr}</span>
            <span>Peso dati ${wPct}% (n=${d.n_obs ?? 0})</span>
          </div>
        </div>`;
    }).join("");
  } else {
    convGrid.innerHTML = '<span class="cmd-muted-note">Diagnostica convergenza disponibile dopo il prossimo update modello.</span>';
  }

  const hist = (model && Array.isArray(model.history)) ? model.history : [];
  if (hist.length) {
    histList.innerHTML = hist.slice(-6).reverse().map(ev => {
      const ts = ev.ts_utc ? formatReceiptTime(ev.ts_utc) : "--";
      const dtStr = ev.ts_utc ? String(ev.ts_utc).slice(5, 10).split("-").reverse().join("/") : "--/--";
      const chgTxt = Array.isArray(ev.changes) ? ev.changes.join(" · ") : "--";
      return `<li><strong>${dtStr} ${ts}</strong> (cicli=${ev.cycles_observed ?? "-"}, standby=${ev.standby_segments_observed ?? "-"}) — ${escapeHtmlSafe(chgTxt)}</li>`;
    }).join("");
  } else {
    histList.innerHTML = "<li>Nessuna revisione storica ancora registrata.</li>";
  }

  const wp = (st && st.weather_plan) || (wf && wf.plan) || null;
  const a = (wp && wp.assumptions) || (wf && wf.calibration) || {};
  const checks = (wf && Array.isArray(wf.recent_oat_checks)) ? wf.recent_oat_checks : [];
  const biasStr = a.oat_bias_c != null ? `${Number(a.oat_bias_c) >= 0 ? "+" : ""}${Number(a.oat_bias_c).toFixed(2)} °C` : "0.00 °C";
  const rawMae = a.oat_raw_mae_c != null ? `${Number(a.oat_raw_mae_c).toFixed(2)} °C` : "--";
  const corrMae = a.oat_mae_c != null ? `${Number(a.oat_mae_c).toFixed(2)} °C` : "--";
  const maxErr = a.oat_max_abs_err_c != null ? `${Number(a.oat_max_abs_err_c).toFixed(2)} °C` : "--";

  let tableHtml = '<span class="cmd-muted-note">In attesa dei primi confronti orari Open-Meteo vs Sonda OAT (si popola automaticamente dal primo fetch meteo).</span>';
  if (checks.length) {
    const rowsHtml = checks.slice(-8).reverse().map(c => {
      const tShort = String(c.time_local || "").slice(5, 16).replace("T", " ");
      const err = Number(c.err_corr_c || 0);
      const errCls = Math.abs(err) <= 1.2 ? "oat-err-ok" : (Math.abs(err) <= 2.5 ? "oat-err-warn" : "oat-err-high");
      return `
        <tr>
          <td>${escapeHtmlSafe(tShort)}</td>
          <td>${Number(c.forecast_raw_c).toFixed(1)}°</td>
          <td>${Number(c.forecast_corr_c).toFixed(1)}°</td>
          <td><strong>${Number(c.actual_oat_c).toFixed(1)}°</strong></td>
          <td><span class="oat-err-pill ${errCls}">${err >= 0 ? "+" : ""}${err.toFixed(1)}K</span></td>
        </tr>`;
    }).join("");
    tableHtml = `
      <div class="ap-oat-table-wrap">
        <table class="ap-oat-table">
          <thead><tr><th>Ora</th><th>Meteo</th><th>Corr.</th><th>Sonda</th><th>Scarto</th></tr></thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>`;
  }

  oatBox.innerHTML = `
    <div class="ap-oat-kpi-strip">
      <span>Bias: <strong>${biasStr}</strong></span>
      <span>MAE: <strong>${rawMae} → ${corrMae}</strong></span>
      <span>Max: <strong>${maxErr}</strong> (${a.oat_samples_matched || 0}h)</span>
    </div>
    ${tableHtml}
  `;
}

function renderSynopticWeatherDrawer(cfg, st, wf) {
  const drawerEl = document.getElementById("synopticWeatherDrawer");
  const sumEl = document.getElementById("synopticWeatherSummaryText");
  const verdictEl = document.getElementById("synWxVerdict");
  const pairEl = document.getElementById("synWxPair");
  const stripEl = document.getElementById("synWxMiniStrip");
  if (!sumEl || !verdictEl || !pairEl || !stripEl) return;

  const isAutoEnabled = Boolean(cfg && cfg.enabled);
  if (drawerEl) {
    drawerEl.style.display = isAutoEnabled ? "" : "none";
  }
  if (!isAutoEnabled) return;

  const wp = (st && st.weather_plan) || (wf && wf.plan) || null;
  const effStart = (st && st.active_window_start_local) || (wp && wp.effective_window_start) || (cfg && cfg.cop_window_start) || "11:00";
  const effEnd = (st && st.active_window_end_local) || (wp && wp.effective_window_end) || (cfg && cfg.cop_window_end) || "16:00";
  const lockIcon = (wp && wp.window_locked) ? " 🔒" : "";
  const tw = wp && wp.today_window;
  const tmw = wp && wp.tomorrow_window;
  const copStr = tw && tw.avg_cop_net != null ? ` · COP ${Number(tw.avg_cop_net).toFixed(2)}` : "";
  const proj = wp && wp.projection_to_tomorrow;
  const minTinStr = proj && proj.min_tin_c != null ? ` · Min attesa ${Number(proj.min_tin_c).toFixed(1)}°C` : "";

  sumEl.textContent = `☀️ Finestra Target: ${effStart}–${effEnd}${lockIcon}${copStr}${minTinStr}`;
  verdictEl.textContent = (wp && wp.decision_summary) || `Finestra statica ${effStart}–${effEnd}`;

  const chips = [];
  if (tw) {
    chips.push(`<div class="syn-wx-chip"><strong>Oggi ${escapeHtmlSafe(effStart)}–${escapeHtmlSafe(effEnd)}${lockIcon}</strong><span>COP ${Number(tw.avg_cop_net).toFixed(2)} · OAT ${Number(tw.avg_temp_c) >= 0 ? "+" : ""}${Number(tw.avg_temp_c).toFixed(1)}°C · RH ${tw.avg_rh_pct}% · Brina ${escapeHtmlSafe(tw.frost_risk)}</span></div>`);
  }
  if (tmw) {
    chips.push(`<div class="syn-wx-chip"><strong>Domani ${escapeHtmlSafe(tmw.start_hhmm)}–${escapeHtmlSafe(tmw.end_hhmm)}</strong><span>COP ${Number(tmw.avg_cop_net).toFixed(2)} · OAT ${Number(tmw.avg_temp_c) >= 0 ? "+" : ""}${Number(tmw.avg_temp_c).toFixed(1)}°C · RH ${tmw.avg_rh_pct}% · Brina ${escapeHtmlSafe(tmw.frost_risk)}</span></div>`);
  }
  pairEl.innerHTML = chips.join("") || '<span class="cmd-muted-note">Previsioni orarie in caricamento...</span>';

  const hourly = (wf && Array.isArray(wf.hourly_preview)) ? wf.hourly_preview.slice(0, 12) : [];
  if (hourly.length) {
    stripEl.innerHTML = hourly.map(h => {
      const tinTxt = h.tin_proj_c != null ? `🏠 ${Number(h.tin_proj_c).toFixed(1)}°` : "";
      return `
        <div class="ap-hour-pill ${h.in_window ? "in-window" : ""}">
          <span class="ap-hour-time">${escapeHtmlSafe(h.day_tag)} ${escapeHtmlSafe(h.hh)}</span>
          <span>${escapeHtmlSafe(h.icon || "🌤️")} ${Number(h.temp_c) >= 0 ? "+" : ""}${Number(h.temp_c).toFixed(1)}°</span>
          <span>RH ${h.rh_pct}%</span>
          <span class="ap-hour-cop">COP ${Number(h.cop_net).toFixed(2)}</span>
          ${tinTxt ? `<span class="ap-hour-tin">${tinTxt}</span>` : ""}
        </div>`;
    }).join("");
  } else {
    stripEl.innerHTML = "";
  }
}

function computeApiQuotaSummary() {
  const nowMs = Date.now();
  const cutoff24 = nowMs - 24 * 3600 * 1000;
  const cutoff1h = nowMs - 3600 * 1000;
  const cutoff10m = nowMs - 10 * 60 * 1000;

  const samples = (typeof state !== "undefined" && Array.isArray(state.samples)) ? state.samples : [];
  let sampleCount24 = 0;
  let sampleCount1h = 0;
  let sampleCount10m = 0;
  const sampleTs24 = [];
  for (const s of samples) {
    if (!s || !s.timestamp_utc) continue;
    const t = new Date(s.timestamp_utc).getTime();
    if (isNaN(t)) continue;
    if (t >= cutoff24) {
      sampleCount24++;
      sampleTs24.push(t);
    }
    if (t >= cutoff1h) sampleCount1h++;
    if (t >= cutoff10m) sampleCount10m++;
  }

  const st = cmdState.lastAutopilotState || {};
  const usage = (st && typeof st.api_usage === "object" && st.api_usage) ? st.api_usage : {};
  const events = Array.isArray(usage.recent_events) ? usage.recent_events : [];

  let evVReads24 = 0, evVWrites24 = 0, evBReads24 = 0, evBWrites24 = 0, evCronPatches24 = 0, evGhRuns24 = 0;
  let evB1h = 0, evV10m = 0;
  const trackedPollTs = [];

  for (const ev of events) {
    if (!ev || !ev.ts) continue;
    const t = new Date(ev.ts).getTime();
    if (isNaN(t) || t < cutoff24) continue;
    const vr = Number(ev.vr || 0);
    const vw = Number(ev.vw || 0);
    const br = Number(ev.br || 0);
    const bw = Number(ev.bw || 0);
    const cp = Number(ev.cp || 0);
    const gh = Number(ev.gh || 0);

    evVReads24 += vr;
    evVWrites24 += vw;
    evBReads24 += br;
    evBWrites24 += bw;
    evCronPatches24 += cp;
    evGhRuns24 += gh;
    if (ev.lbl === "telemetry_poll") trackedPollTs.push(t);
    if (t >= cutoff1h) evB1h += (br + bw);
    if (t >= cutoff10m) evV10m += (vr + vw);
  }

  // Reconcile historical samples taken before backend event tracking was deployed
  let untracked24 = 0;
  let untracked1h = 0;
  let untracked10m = 0;
  for (const ts of sampleTs24) {
    const matched = trackedPollTs.some(pt => Math.abs(pt - ts) <= 120000);
    if (!matched) {
      untracked24++;
      if (ts >= cutoff1h) untracked1h++;
      if (ts >= cutoff10m) untracked10m++;
    }
  }

  const vReads24 = evVReads24 + untracked24 * 2;
  const vWrites24 = evVWrites24;
  const vTotal24 = vReads24 + vWrites24;
  const v10m = evV10m + untracked10m * 2;

  const bReads24 = evBReads24 + untracked24 * 2;
  const bWrites24 = evBWrites24;
  const bTotal1h = evB1h + untracked1h * 2;

  const cronTriggers24 = sampleCount24;
  const cronPatches24 = evCronPatches24;
  const ghRuns24 = Math.max(evGhRuns24 + untracked24, sampleCount24);

  let ghClient1h = 0;
  let ghClient24 = 0;
  try {
    const rawCalls = JSON.parse(localStorage.getItem(GH_CLIENT_CALLS_KEY) || "[]");
    for (const ts of rawCalls) {
      if (typeof ts === "number" && ts >= cutoff24) {
        ghClient24++;
        if (ts >= cutoff1h) ghClient1h++;
      }
    }
  } catch (e) {}

  const curCronMin = Number(st.current_cron_interval_min || (cmdState.lastAutopilotConfig && cmdState.lastAutopilotConfig.cron_idle_minutes) || 5);
  const projectedV24 = Math.round((1440 / Math.max(1, curCronMin)) * 2);

  return {
    vReads24, vWrites24, vTotal24, vLimit24: 1450, v10m, vLimit10m: 120,
    bReads24, bWrites24, bTotal1h, bLimit1h: 500,
    cronTriggers24, cronLimit24: 1440, cronPatches24, cronPatchLimit24: 100,
    ghClient1h, ghClient24, ghLimit1h: 5000, ghRuns24,
    curCronMin, projectedV24,
  };
}

function buildQuotaBarColor(pct) {
  if (pct >= 80) return "#ef4444";
  if (pct >= 50) return "#f59e0b";
  return "#10b981";
}

function renderApiQuotaMonitor() {
  const q = computeApiQuotaSummary();
  const vPct = Math.min(100, (q.vTotal24 / q.vLimit24) * 100);
  const bPct = Math.min(100, (q.bTotal1h / q.bLimit1h) * 100);
  const cPct = Math.min(100, (q.cronTriggers24 / q.cronLimit24) * 100);
  const gPct = Math.min(100, (q.ghClient1h / q.ghLimit1h) * 100);

  const cards = [
    {
      name: "Viessmann ViCare (24h)",
      val: `${q.vTotal24} / ${q.vLimit24}`,
      pct: vPct,
      left: `Letture: ${q.vReads24} · Scritture: ${q.vWrites24}`,
      right: `10m: ${q.v10m}/${q.vLimit10m} · Proj: ~${q.projectedV24}/24h`,
    },
    {
      name: "BTicino / Netatmo (1h)",
      val: `${q.bTotal1h} / ${q.bLimit1h}`,
      pct: bPct,
      left: `24h Letture: ${q.bReads24} · Scritture: ${q.bWrites24}`,
      right: `${bPct.toFixed(1)}% usato ora`,
    },
    {
      name: "cron-job.org (24h)",
      val: `${q.cronTriggers24} / ${q.cronLimit24}`,
      pct: cPct,
      left: `Trigger: ${q.cronTriggers24} · PATCH API: ${q.cronPatches24}/${q.cronPatchLimit24}`,
      right: `Freq: ${q.curCronMin} min`,
    },
    {
      name: "GitHub REST & Actions",
      val: `${q.ghClient1h} / ${q.ghLimit1h} (1h)`,
      pct: gPct,
      left: `Client 24h: ${q.ghClient24} · Runner 24h: ${q.ghRuns24}`,
      right: "Repo pubblico: min ∞",
    },
  ];

  const html = cards.map(c => `
    <div class="api-quota-item">
      <div class="api-quota-head">
        <span>${c.name}</span>
        <span class="api-quota-val" style="color:${buildQuotaBarColor(c.pct)}">${c.val} (${c.pct.toFixed(0)}%)</span>
      </div>
      <div class="api-quota-bar-bg">
        <div class="api-quota-bar-fill" style="width:${Math.max(2, c.pct).toFixed(1)}%; background:${buildQuotaBarColor(c.pct)};"></div>
      </div>
      <div class="api-quota-sub">
        <span>${c.left}</span>
        <span>${c.right}</span>
      </div>
    </div>
  `).join("");

  const compactBody = document.getElementById("apiQuotaCompactBody");
  const detailedBody = document.getElementById("apiQuotaDetailedBody");
  if (compactBody) compactBody.innerHTML = html;
  if (detailedBody) detailedBody.innerHTML = html;

  const badgeText = `Viessmann ${vPct.toFixed(0)}% · Cron ${q.curCronMin}m`;
  const b1 = document.getElementById("apiQuotaBadgeCompact");
  const b2 = document.getElementById("apiQuotaBadgeDetailed");
  if (b1) b1.textContent = badgeText;
  if (b2) b2.textContent = badgeText;
}

window.renderApiQuotaMonitor = renderApiQuotaMonitor;

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
