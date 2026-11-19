/**
 * Telemetry Charts for Vitocal Remote Mobile App.
 * Uses Chart.js with responsive dark mode styling and multi-axis support.
 */

let telemetryChart = null;
let currentSamples = [];
let activeTimeframeHours = 24; // Default 24h

const CHANNEL_DEFS = [
  { key: "external_temp_c", label: "T Esterna Sonda PdC", unit: "°C", color: "#38bdf8", yAxis: "yTemp", active: true },
  { key: "buffer_temp_c", label: "T Accumulo Puffer 200L", unit: "°C", color: "#f59e0b", yAxis: "yTemp", active: true },
  { key: "pdc_supply_temp_c", label: "T Mandata PdC", unit: "°C", color: "#ef4444", yAxis: "yTemp", active: true },
  { key: "indoor_temp_bticino_c", label: "T Interna Corridoio", unit: "°C", color: "#10b981", yAxis: "yTemp", active: true },
  { key: "indoor_setpoint_bticino_c", label: "Setpoint BTicino", unit: "°C", color: "#eab308", yAxis: "yTemp", borderDash: [5, 5], active: true },
  { key: "compressor_modulation_percent", label: "Modulazione Inverter (%)", unit: "%", color: "#facc15", yAxis: "yOther", active: true },
  { key: "hot_gas_pressure_bar", label: "Pressione Gas Caldo (bar)", unit: "bar", color: "#ec4899", yAxis: "yOther", active: false },
  { key: "cop_heating", label: "COP Riscaldamento", unit: "COP", color: "#34d399", yAxis: "yOther", active: false },
];

function initCharts(samples) {
  currentSamples = samples || [];
  renderChannelPills();
  buildChart();
}

function updateChartData(samples) {
  currentSamples = samples || [];
  if (!telemetryChart) {
    buildChart();
    return;
  }
  
  const filtered = filterSamplesByTime(currentSamples, activeTimeframeHours);
  const labels = filtered.map(s => formatTimestamp(s.timestamp_utc));
  
  telemetryChart.data.labels = labels;
  telemetryChart.data.datasets = getDatasets(filtered);
  telemetryChart.update();
}

function setChartTimeframe(hours) {
  activeTimeframeHours = hours;
  document.querySelectorAll(".btn-filter").forEach(btn => {
    btn.classList.toggle("active", parseInt(btn.dataset.hours) === hours);
  });
  updateChartData(currentSamples);
}

function filterSamplesByTime(samples, hours) {
  if (!samples || samples.length === 0) return [];
  if (hours <= 0) return samples; // All data

  const now = new Date();
  const cutoff = new Date(now.getTime() - hours * 60 * 60 * 1000);
  
  const filtered = samples.filter(s => {
    if (!s.timestamp_utc) return false;
    const d = new Date(s.timestamp_utc);
    return d >= cutoff;
  });

  return filtered.length > 0 ? filtered : samples.slice(-Math.min(50, samples.length));
}

function formatTimestamp(tsStr) {
  if (!tsStr) return "";
  const d = new Date(tsStr);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const mon = String(d.getMonth() + 1).padStart(2, '0');
  
  if (activeTimeframeHours <= 24) {
    return `${h}:${m}`;
  }
  return `${day}/${mon} ${h}:${m}`;
}

function getDatasets(samples) {
  return CHANNEL_DEFS.filter(ch => ch.active).map(ch => {
    return {
      label: ch.label,
      data: samples.map(s => s[ch.key]),
      borderColor: ch.color,
      backgroundColor: ch.color + "22",
      borderWidth: 2,
      pointRadius: samples.length > 50 ? 0 : 2.5,
      pointHoverRadius: 6,
      tension: 0.25,
      borderDash: ch.borderDash || [],
      yAxisID: ch.yAxis,
      spanGaps: true,
    };
  });
}

function buildChart() {
  const canvas = document.getElementById("telemetryChartCanvas");
  if (!canvas) return;

  const filtered = filterSamplesByTime(currentSamples, activeTimeframeHours);
  const labels = filtered.map(s => formatTimestamp(s.timestamp_utc));

  if (telemetryChart) {
    telemetryChart.destroy();
  }

  const ctx = canvas.getContext("2d");
  telemetryChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: getDatasets(filtered)
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          display: false, // Custom legend using pills below
        },
        tooltip: {
          backgroundColor: "rgba(15, 23, 42, 0.95)",
          titleColor: "#38bdf8",
          bodyColor: "#f8fafc",
          borderColor: "#334155",
          borderWidth: 1,
          padding: 10,
          cornerRadius: 8,
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(51, 65, 85, 0.3)" },
          ticks: { color: "#94a3b8", maxRotation: 0, font: { size: 10 } }
        },
        yTemp: {
          type: "linear",
          position: "left",
          title: { display: true, text: "Temperatura (°C)", color: "#94a3b8", font: { size: 10 } },
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#cbd5e1", font: { size: 10 } }
        },
        yOther: {
          type: "linear",
          position: "right",
          title: { display: true, text: "% / bar / COP", color: "#94a3b8", font: { size: 10 } },
          grid: { drawOnChartArea: false },
          ticks: { color: "#cbd5e1", font: { size: 10 } }
        }
      }
    }
  });
}

function renderChannelPills() {
  const container = document.getElementById("channelPillsContainer");
  if (!container) return;

  container.innerHTML = CHANNEL_DEFS.map((ch, idx) => `
    <button class="channel-pill ${ch.active ? 'active' : ''}" data-idx="${idx}" style="color: ${ch.color}">
      <span class="channel-dot" style="background-color: ${ch.color}"></span>
      ${ch.label}
    </button>
  `).join("");

  container.querySelectorAll(".channel-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx);
      CHANNEL_DEFS[idx].active = !CHANNEL_DEFS[idx].active;
      btn.classList.toggle("active", CHANNEL_DEFS[idx].active);
      updateChartData(currentSamples);
    });
  });
}
