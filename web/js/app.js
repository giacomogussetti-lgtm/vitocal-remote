/**
 * Vitocal Remote - Mobile App Controller
 * Manages GitHub Sync, Direct API requests, PWA lifecycle, and UI navigation.
 */

const APP_CONFIG = {
  defaultRepo: "giacomogussetti-lgtm/vitocal-remote",
  pollIntervalSec: 120, // Check for new GitHub data every 2 minutes
};

// Application State
const state = {
  repo: localStorage.getItem("vitocal_repo") || APP_CONFIG.defaultRepo,
  githubToken: localStorage.getItem("vitocal_token") || "",
  samples: [],
  latestSample: null,
  isSyncing: false,
  autoPollTimer: null,
  lastSyncTime: null,
  backendConnected: false,
  analyticsHours: 24,
};

// DOM Initialization
document.addEventListener("DOMContentLoaded", () => {
  initPWA();
  initNavigation();
  initSettingsForm();
  initActionButtons();
  initAnalyticsListeners();
  if (typeof initChartControls === "function") {
    initChartControls();
  }
  if (typeof initCommandsUI === "function") {
    initCommandsUI();
  }
  if (typeof initHelpSystem === "function") {
    initHelpSystem();
  }
  initLandscapeChromeToggle();

  // Initial Sync
  loadCachedSamples();
  checkBackendConnection().then(() => {
    if (typeof updateCommandsTransportUI === "function") updateCommandsTransportUI();
    if (typeof refreshAutopilotStatus === "function") refreshAutopilotStatus();
    syncWithGitHub();
  });

  // Start Auto-Polling
  startAutoPoll();
});

// PWA Service Worker Registration
function initPWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js")
      .then(reg => console.log("Service Worker registrato con successo:", reg.scope))
      .catch(err => console.warn("Registrazione Service Worker fallita:", err));
  }
}

// Navigation between tabs
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  const tabContents = document.querySelectorAll(".tab-content");

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const tabId = item.dataset.tab;
      navItems.forEach(n => n.classList.remove("active"));
      tabContents.forEach(t => t.classList.remove("active"));

      item.classList.add("active");
      const targetTab = document.getElementById(tabId);
      if (targetTab) {
        targetTab.classList.add("active");
        if (document.body.classList.contains("landscape-chrome-open")) {
          document.body.classList.remove("landscape-chrome-open");
          const fab = document.getElementById("btnLandscapeNavToggle");
          if (fab) fab.textContent = "☰";
        }
        if (tabId === "tab-charts") {
          setTimeout(() => {
            updateChartData(state.samples);
            if (typeof telemetryChart !== "undefined" && telemetryChart) telemetryChart.resize();
          }, 50);
        } else if (tabId === "tab-analytics") {
          updateAnalyticsUI(state.analyticsHours);
        } else if (tabId === "tab-commands") {
          if (typeof updateCommandsTransportUI === "function") updateCommandsTransportUI();
          if (typeof refreshLastCommandReceipt === "function") refreshLastCommandReceipt();
          if (typeof refreshAutopilotStatus === "function") refreshAutopilotStatus();
          if (typeof renderApiQuotaMonitor === "function") renderApiQuotaMonitor();
        } else if (tabId === "tab-settings") {
          if (typeof renderApiQuotaMonitor === "function") renderApiQuotaMonitor();
        } else if (tabId === "tab-synoptic" && state.latestSample) {
          renderSynoptic(state.latestSample);
        }
      }
    });
  });

  // Chart timeframe filter buttons (strictly scoped to chart tab)
  document.querySelectorAll("#chartTimeframeButtons .btn-filter").forEach(btn => {
    btn.addEventListener("click", () => {
      const hours = parseInt(btn.dataset.hours, 10);
      setChartTimeframe(hours);
    });
  });
}

function initLandscapeChromeToggle() {
  const fab = document.getElementById("btnLandscapeNavToggle");
  if (fab && fab.dataset.bound !== "1") {
    fab.dataset.bound = "1";
    fab.addEventListener("click", () => {
      const isOpen = document.body.classList.toggle("landscape-chrome-open");
      fab.textContent = isOpen ? "✕" : "☰";
    });
  }

  let resizeTimer = null;
  const handleLayoutChange = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (document.body.classList.contains("landscape-chrome-open") && window.innerHeight > 540) {
        document.body.classList.remove("landscape-chrome-open");
        if (fab) fab.textContent = "☰";
      }
      if (typeof telemetryChart !== "undefined" && telemetryChart) {
        telemetryChart.resize();
      }
    }, 150);
  };
  window.addEventListener("resize", handleLayoutChange);
  window.addEventListener("orientationchange", handleLayoutChange);
}

// Action Buttons
function initActionButtons() {
  // Header Quick Refresh
  const btnHeaderRefresh = document.getElementById("btnHeaderRefresh");
  if (btnHeaderRefresh) {
    btnHeaderRefresh.addEventListener("click", () => syncWithGitHub(true));
  }

  // Settings Tab Sync Buttons
  const btnSyncGithub = document.getElementById("btnSyncGithub");
  if (btnSyncGithub) {
    btnSyncGithub.addEventListener("click", () => syncWithGitHub(true));
  }

  const btnTriggerAction = document.getElementById("btnTriggerAction");
  if (btnTriggerAction) {
    btnTriggerAction.addEventListener("click", triggerGitHubWorkflow);
  }

  const btnDirectApi = document.getElementById("btnDirectApi");
  if (btnDirectApi) {
    btnDirectApi.addEventListener("click", refreshDirectApi);
  }
}

// Analytics Listeners (X-Hours Period)
function initAnalyticsListeners() {
  const container = document.getElementById("analyticsFilterButtons");
  if (container) {
    container.querySelectorAll(".btn-filter").forEach(btn => {
      btn.addEventListener("click", () => {
        container.querySelectorAll(".btn-filter").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const hours = parseFloat(btn.dataset.hours);
        state.analyticsHours = hours;
        const customInput = document.getElementById("customAnalyticsHours");
        if (customInput) customInput.value = hours;
        updateAnalyticsUI(hours);
      });
    });
  }

  const btnApplyCustom = document.getElementById("btnApplyCustomHours");
  if (btnApplyCustom) {
    btnApplyCustom.addEventListener("click", () => {
      const customInput = document.getElementById("customAnalyticsHours");
      if (customInput) {
        const val = parseFloat(customInput.value);
        if (!isNaN(val) && val > 0) {
          state.analyticsHours = val;
          if (container) {
            container.querySelectorAll(".btn-filter").forEach(b => {
              b.classList.toggle("active", parseFloat(b.dataset.hours) === val);
            });
          }
          updateAnalyticsUI(val);
          showToast(`Statistiche calcolate per le ultime ${val} ore.`);
        }
      }
    });
  }
}

function updateAnalyticsUI(hours) {
  if (typeof computePeriodAnalytics !== "function") return;
  const res = computePeriodAnalytics(state.samples, hours);

  // Effective period info
  const span = document.getElementById("analyticsEffectiveSpan");
  if (span) span.textContent = `Analisi su ${res.effectiveHours}h (${res.samplesCount} campioni)`;

  // Anti-frost Safety Banner
  const safetyBanner = document.getElementById("safetyBanner");
  const verdictText = document.getElementById("safetyVerdictText");
  const marginBadge = document.getElementById("safetyMarginBadge");
  const adviceText = document.getElementById("safetyAdviceText");

  if (verdictText) verdictText.textContent = res.safetyVerdict;
  if (marginBadge) marginBadge.textContent = `+${res.safetyMargin} °C`;
  if (adviceText) adviceText.textContent = res.safetyAdvice;

  if (safetyBanner) {
    safetyBanner.className = `pump-banner ${res.safetyStatus === 'safe' ? 'active' : (res.safetyStatus === 'caution' ? 'inactive' : 'danger')}`;
    if (res.safetyStatus === 'safe') {
      safetyBanner.style.backgroundColor = "rgba(16, 185, 129, 0.15)";
      safetyBanner.style.borderColor = "rgba(16, 185, 129, 0.4)";
    } else if (res.safetyStatus === 'caution') {
      safetyBanner.style.backgroundColor = "rgba(245, 158, 11, 0.15)";
      safetyBanner.style.borderColor = "rgba(245, 158, 11, 0.4)";
    } else {
      safetyBanner.style.backgroundColor = "rgba(239, 68, 68, 0.2)";
      safetyBanner.style.borderColor = "rgba(239, 68, 68, 0.5)";
    }
  }

  // Starts & Cycle Durations KPIs
  const elStarts = document.getElementById("kpiStarts");
  const elDuty = document.getElementById("kpiDutyCycle");
  const elDurAvg = document.getElementById("kpiDurAvg");
  const elDurMinMax = document.getElementById("kpiDurMinMax");
  const elRunHours = document.getElementById("kpiRunHours");
  const elStandbyHours = document.getElementById("kpiStandbyHours");
  const elCostEur = document.getElementById("kpiCostEur");
  const elDailyProj = document.getElementById("kpiDailyProjected");
  const elElecKwh = document.getElementById("kpiElecKwh");
  const elAvgKw = document.getElementById("kpiAvgKw");

  if (elStarts) elStarts.textContent = res.totalStarts;
  if (elDuty) elDuty.textContent = `Duty Cycle: ${res.dutyCyclePct}%`;
  if (elDurAvg) elDurAvg.innerHTML = `${res.durAvg} <small style="font-size: 0.8rem;">min</small>`;
  if (elDurMinMax) elDurMinMax.textContent = `Min: ${res.durMin}m | Max: ${res.durMax}m`;
  if (elRunHours) elRunHours.innerHTML = `${res.totalRunHours} <small style="font-size: 0.8rem;">h</small>`;
  if (elStandbyHours) elStandbyHours.textContent = `Standby: ${res.standbyHours}h`;
  if (elCostEur) elCostEur.innerHTML = `${res.estimatedCostEur.toFixed(2)} <small style="font-size: 0.8rem;">€</small>`;
  if (elDailyProj) elDailyProj.textContent = `Proiezione: ${res.projectedDailyCost.toFixed(2)} €/giorno`;
  if (elElecKwh) elElecKwh.innerHTML = `${res.totalElecKwh} <small>kWh</small>`;
  if (elAvgKw) elAvgKw.innerHTML = `${res.avgPowerKw} <small>kW</small>`;

  // Modulation Quality
  const modScoreBadge = document.getElementById("modScoreBadge");
  const modVerdict = document.getElementById("modVerdictText");
  const modDiag = document.getElementById("modDiagnosisText");

  if (modScoreBadge) {
    modScoreBadge.textContent = `Score ${res.score}/100`;
    modScoreBadge.style.color = res.score >= 80 ? "#10b981" : (res.score >= 50 ? "#facc15" : "#f87171");
  }
  if (modVerdict) modVerdict.textContent = res.verdict;
  if (modDiag) modDiag.textContent = res.diagnosis;

  // Load Distribution Bars
  const barLow = document.getElementById("barLowLoad");
  const barMid = document.getElementById("barMidLoad");
  const barHigh = document.getElementById("barHighLoad");
  const txtLow = document.getElementById("txtLowLoad");
  const txtMid = document.getElementById("txtMidLoad");
  const txtHigh = document.getElementById("txtHighLoad");

  if (barLow) barLow.style.width = `${res.lowPct}%`;
  if (barMid) barMid.style.width = `${res.midPct}%`;
  if (barHigh) barHigh.style.width = `${res.highPct}%`;

  if (txtLow) txtLow.textContent = `${res.lowPct}%`;
  if (txtMid) txtMid.textContent = `${res.midPct}%`;
  if (txtHigh) txtHigh.textContent = `${res.highPct}%`;
}

// Settings form
function initSettingsForm() {
  const repoInput = document.getElementById("settingRepo");
  const tokenInput = document.getElementById("settingToken");
  const btnSave = document.getElementById("btnSaveSettings");

  if (repoInput) repoInput.value = state.repo;
  if (tokenInput) tokenInput.value = state.githubToken;

  if (btnSave) {
    btnSave.addEventListener("click", () => {
      state.repo = repoInput.value.trim() || APP_CONFIG.defaultRepo;
      state.githubToken = tokenInput.value.trim();
      localStorage.setItem("vitocal_repo", state.repo);
      localStorage.setItem("vitocal_token", state.githubToken);
      if (typeof updateCommandsTransportUI === "function") updateCommandsTransportUI();
      showToast("Impostazioni salvate con successo!");
      syncWithGitHub(true);
    });
  }
}

// Check if running alongside local Python backend (Flask server)
async function checkBackendConnection() {
  try {
    const res = await fetch("./api/status", { method: "GET", cache: "no-cache" });
    if (res.ok) {
      state.backendConnected = true;
      document.getElementById("backendStatusBadge").textContent = "Connesso (Server Locale)";
      document.getElementById("backendStatusBadge").style.color = "#10b981";
      document.getElementById("btnDirectApi").disabled = false;
      return true;
    }
  } catch (e) {
    state.backendConnected = false;
    document.getElementById("backendStatusBadge").textContent = "Offline (Modalità Cloud GitHub)";
    document.getElementById("backendStatusBadge").style.color = "#38bdf8";
  }
  return false;
}

// -------------------------------------------------------------
// GITHUB TELEMETRY SYNC
// -------------------------------------------------------------
async function syncWithGitHub(showNotification = false) {
  if (state.isSyncing) return;
  setSyncIndicator(true);

  // 1. If connected to local Python backend, use server-side proxy
  if (state.backendConnected) {
    try {
      const res = await fetch("./api/sync-github", { method: "POST" });
      const data = await res.json();
      if (data && data.success && data.samples && data.samples.length > 0) {
        state.samples = data.samples;
        state.latestSample = data.samples[data.samples.length - 1];
        localStorage.setItem("cached_telemetry", JSON.stringify(state.samples.slice(-100)));
        state.lastSyncTime = new Date();
        updateUI();
        if (typeof refreshAutopilotStatus === "function") refreshAutopilotStatus();
        if (showNotification) {
          showToast(`✅ Sincronizzati ${data.total_lines} campioni da GitHub (${data.imported} nuovi)!`);
        }
        setSyncIndicator(false);
        return;
      }
    } catch (backendErr) {
      console.warn("Server-side sync fallback to direct:", backendErr);
    }
  }

  // 2. Direct fetch (for standalone PWA / GitHub Pages without backend)
  try {
    let text = "";
    // If token provided (e.g. private repo), use GitHub API (handles CORS)
    if (state.githubToken) {
      const apiUrl = `https://api.github.com/repos/${state.repo}/contents/data/cloud_telemetry.jsonl?ref=main`;
      if (typeof trackClientGithubCall === "function") trackClientGithubCall(1);
      const apiRes = await fetch(apiUrl, {
        headers: {
          "Authorization": `token ${state.githubToken}`,
          "Accept": "application/vnd.github.v3.raw"
        }
      });
      if (!apiRes.ok) throw new Error(`HTTP ${apiRes.status} da GitHub API`);
      text = await apiRes.text();
    } else {
      // Public repo direct raw fetch (Must NOT use custom headers to avoid CORS preflight 403)
      const rawUrl = `https://raw.githubusercontent.com/${state.repo}/main/data/cloud_telemetry.jsonl?t=${Date.now()}`;
      const rawRes = await fetch(rawUrl);
      if (!rawRes.ok) throw new Error(`HTTP ${rawRes.status} da GitHub`);
      text = await rawRes.text();
    }

    const parsedSamples = parseJsonl(text);

    if (parsedSamples.length > 0) {
      state.samples = parsedSamples;
      state.latestSample = parsedSamples[parsedSamples.length - 1];
      localStorage.setItem("cached_telemetry", JSON.stringify(state.samples.slice(-100)));
      state.lastSyncTime = new Date();

      updateUI();
      if (typeof refreshAutopilotStatus === "function") refreshAutopilotStatus();
      if (showNotification) {
        showToast(`✅ Sincronizzati ${parsedSamples.length} campioni da GitHub!`);
      }
    } else {
      if (showNotification) showToast("File cloud vuoto o nessun nuovo dato.");
    }
  } catch (error) {
    console.warn("Errore sync GitHub:", error);
    if (state.backendConnected) {
      await fallbackLocalFetch();
    } else if (showNotification) {
      showToast(`⚠️ Sincronizzazione fallita: ${error.message}`);
    }
  } finally {
    setSyncIndicator(false);
  }
}

function parseJsonl(text) {
  const lines = text.split("\n");
  const samples = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const obj = JSON.parse(trimmed);
      samples.push(obj);
    } catch (e) {
      // Skip corrupted line
    }
  }
  return samples;
}

// -------------------------------------------------------------
// ON-DEMAND REFRESH (API DIRETTA O GITHUB ACTION DISPATCH)
// -------------------------------------------------------------

// Trigger GitHub Actions Workflow via API
async function triggerGitHubWorkflow() {
  const btn = document.getElementById("btnTriggerAction");
  if (!state.githubToken) {
    showToast("⚠️ Inserisci un GitHub Personal Access Token nelle Impostazioni per avviare il workflow!");
    return;
  }

  btn.disabled = true;
  btn.textContent = "⏳ Invio ordine a GitHub Actions...";

  try {
    const url = `https://api.github.com/repos/${state.repo}/actions/workflows/telemetry_logger.yml/dispatches`;
    if (typeof trackClientGithubCall === "function") trackClientGithubCall(1);
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": `token ${state.githubToken}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ ref: "main" })
    });

    if (res.status === 204) {
      showToast("🚀 Workflow GitHub avviato! Il nuovo campione sarà pronto tra 20-30s.");
      // Auto re-check in 25 seconds
      setTimeout(() => syncWithGitHub(true), 25000);
    } else {
      const errJson = await res.json().catch(() => ({}));
      showToast(`Errore GitHub (${res.status}): ${errJson.message || 'Controlla token e permessi'}`);
    }
  } catch (e) {
    showToast(`Errore di rete: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ Campiona Ora (GitHub Action)";
  }
}

// Direct local API refresh (when using Flask web_server.py)
async function refreshDirectApi() {
  const btn = document.getElementById("btnDirectApi");
  if (!state.backendConnected) {
    showToast("⚠️ Il server Python locale non è attivo. Usa il Sync da GitHub!");
    return;
  }

  btn.disabled = true;
  btn.textContent = "⏳ Interrogazione diretta Vitocal & BTicino...";

  try {
    const res = await fetch("./api/refresh-direct", { method: "POST" });
    const data = await res.json();
    if (data.success && data.sample) {
      state.samples.push(data.sample);
      state.latestSample = data.sample;
      updateUI();
      showToast("✅ Campionamento diretto eseguito con successo!");
    } else {
      showToast(`Errore API: ${data.error || 'Risposta non valida'}`);
    }
  } catch (e) {
    showToast(`Errore connessione server locale: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "🔌 Interrogazione Diretta (API Live)";
  }
}

async function fallbackLocalFetch() {
  try {
    const fileRes = await fetch(`./data/cloud_telemetry.jsonl?t=${Date.now()}`);
    if (fileRes.ok) {
      const text = await fileRes.text();
      const parsed = parseJsonl(text);
      if (parsed.length > 0) {
        state.samples = parsed;
        state.latestSample = parsed[parsed.length - 1];
        updateUI();
        return;
      }
    }
  } catch (fe) {}

  try {
    const res = await fetch("./api/history");
    const data = await res.json();
    if (data && data.samples && data.samples.length > 0) {
      state.samples = data.samples;
      state.latestSample = data.samples[data.samples.length - 1];
      updateUI();
    }
  } catch (e) {}
}

// -------------------------------------------------------------
// UI RENDERING & UPDATES
// -------------------------------------------------------------
function updateUI() {
  if (!state.latestSample) return;
  const s = state.latestSample;

  // 1. Render SCADA Synoptic
  renderSynoptic(s);

  // 2. Render Charts
  updateChartData(state.samples);

  // 3. Update Quick Cards
  document.getElementById("cardOat").textContent = s.external_temp_c != null ? `${s.external_temp_c.toFixed(1)} °C` : "--";
  document.getElementById("cardBuffer").textContent = s.buffer_temp_c != null ? `${s.buffer_temp_c.toFixed(1)} °C` : "--";
  document.getElementById("cardSupply").textContent = s.pdc_supply_temp_c != null ? `${s.pdc_supply_temp_c.toFixed(1)} °C` : "--";
  document.getElementById("cardIndoor").textContent = s.indoor_temp_bticino_c != null ? `${s.indoor_temp_bticino_c.toFixed(1)} °C` : "--";
  document.getElementById("cardSetpoint").textContent = s.indoor_setpoint_bticino_c != null ? `${s.indoor_setpoint_bticino_c.toFixed(1)} °C` : "--";
  
  const compActive = (s.compressor_active === 1) || ((s.compressor_modulation_percent || 0) > 0);
  document.getElementById("cardComp").textContent = compActive ? `${(s.compressor_modulation_percent || 0).toFixed(0)} %` : "OFF";
  document.getElementById("cardComp").style.color = compActive ? "#10b981" : "#94a3b8";

  // 4. Update Sonde Details Table
  renderDetailedSondeList(s);

  // 6. Header Status Timestamp
  const lastUpdateSpan = document.getElementById("lastUpdateText");
  if (lastUpdateSpan && s.timestamp_utc) {
    const d = new Date(s.timestamp_utc);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    lastUpdateSpan.textContent = `Ultimo: ${h}:${m}`;
  }

  // 7. Update Analytics (X-Hours Period)
  updateAnalyticsUI(state.analyticsHours || 24);

  // 8. Sync Bidirectional Commands Controls
  if (typeof syncCommandsFromTelemetry === "function") {
    syncCommandsFromTelemetry(s);
  }
  if (typeof renderApiQuotaMonitor === "function") {
    renderApiQuotaMonitor();
  }
}

function renderDetailedSondeList(s) {
  const container = document.getElementById("sondeCardsContainer");
  if (!container) return;

  const items = [
    { label: "Temperatura Esterna (Sonda PdC)", val: s.external_temp_c, unit: "°C", color: "#38bdf8" },
    { label: "Accumulo Puffer 200 Litri", val: s.buffer_temp_c, unit: "°C", color: "#f59e0b" },
    { label: "Mandata Pompa di Calore", val: s.pdc_supply_temp_c, unit: "°C", color: "#ef4444" },
    { label: "Ritorno Pompa di Calore", val: s.pdc_return_temp_c, unit: "°C", color: "#3b82f6" },
    { label: "Bollitore ACS Sanitario 220L", val: s.dhw_storage_temp_c, unit: "°C", color: "#c084fc" },
    { label: "Temperatura Corridoio (BTicino)", val: s.indoor_temp_bticino_c, unit: "°C", color: "#10b981" },
    { label: "Setpoint Corridoio", val: s.indoor_setpoint_bticino_c, unit: "°C", color: "#eab308" },
    { label: "Umidità Relativa Corridoio", val: s.humidity_percent, unit: "%", color: "#60a5fa" },
    { label: "Pressione Gas Caldo Refrigerante", val: s.hot_gas_pressure_bar, unit: "bar", color: "#ec4899" },
    { label: "Temperatura Gas Caldo", val: s.hot_gas_temp_c, unit: "°C", color: "#f87171" },
    { label: "Temperatura Gas Liquido", val: s.liquid_gas_temp_c, unit: "°C", color: "#38bdf8" },
    { label: "Temperatura Gas Aspirazione", val: s.suction_gas_temp_c, unit: "°C", color: "#93c5fd" },
    { label: "Modulazione Compressore Inverter", val: s.compressor_modulation_percent, unit: "%", color: "#facc15" },
    { label: "Ore Funzionamento Compressore", val: s.compressor_hours, unit: "h", color: "#e2e8f0" },
    { label: "Avvii Totali Compressore", val: s.compressor_starts, unit: "avvii", color: "#e2e8f0" },
    { label: "COP Istantaneo Riscaldamento", val: s.cop_heating, unit: "", color: "#10b981" },
    { label: "COP Totale Macchina", val: s.cop_total, unit: "", color: "#6ee7b7" },
    { label: "Circolatore Primario PdC", val: s.primary_pump_rotation_percent, unit: "%", color: "#34d399" },
    { label: "Curva Climatica (Inclinazione / Livello)", val: `${s.heating_curve_slope || 0.6} / ${s.heating_curve_shift || 0}`, unit: "", color: "#60a5fa" },
    { label: "Programma Operativo PdC", val: (s.active_program || "standby").toUpperCase(), unit: "", color: "#a78bfa" },
    { label: "Fase Compressore / Defrost", val: (s.compressor_phase || "off").toUpperCase(), unit: "", color: String(s.compressor_phase || "").includes("defrost") ? "#38bdf8" : "#cbd5e1" },
    { label: "Antigelo Hardware WO1C", val: (s.frost_protection_status || "off").toUpperCase(), unit: "", color: s.frost_protection_status === "on" ? "#f59e0b" : "#94a3b8" },
    { label: "Resistenza Elettrica (S1 / S2)", val: (s.heating_rod_level1_s != null || s.heating_rod_level2_s != null) ? `${(Number(s.heating_rod_level1_s || 0) / 3600).toFixed(1)}h / ${(Number(s.heating_rod_level2_s || 0) / 3600).toFixed(1)}h` : "--", unit: "", color: "#fb7185" },
  ];

  container.innerHTML = items.map(item => `
    <div class="status-card">
      <span class="card-label">${item.label}</span>
      <span class="card-value" style="color: ${item.color}">${item.val != null ? item.val : '--'} <small style="font-size: 0.75rem; color: #94a3b8;">${item.unit}</small></span>
    </div>
  `).join("");
}

function loadCachedSamples() {
  const cached = localStorage.getItem("cached_telemetry");
  if (cached) {
    try {
      state.samples = JSON.parse(cached);
      if (state.samples.length > 0) {
        state.latestSample = state.samples[state.samples.length - 1];
        initCharts(state.samples);
        updateUI();
      }
    } catch (e) {}
  }
}

function startAutoPoll() {
  if (state.autoPollTimer) clearInterval(state.autoPollTimer);
  state.autoPollTimer = setInterval(() => {
    syncWithGitHub(false);
  }, APP_CONFIG.pollIntervalSec * 1000);
}

function setSyncIndicator(isSyncing) {
  state.isSyncing = isSyncing;
  const dot = document.getElementById("statusDot");
  if (dot) {
    dot.className = `status-dot ${isSyncing ? "syncing" : "active"}`;
  }
}

function showToast(msg) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3500);
}
