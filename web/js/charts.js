/**
 * Telemetry Charts for Vitocal Remote Mobile App.
 * Uses Chart.js with responsive dark mode styling, multi-axis support,
 * and continuous TimeScale (date-fns adapter) for physically proportional timelines.
 */

let telemetryChart = null;
let currentSamples = [];
let activeTimeframeHours = 24; // Default 24h

const CHANNEL_DEFS = [
  { key: "external_temp_c", label: "T Esterna Sonda PdC", unit: "°C", color: "#38bdf8", yAxis: "yTemp", active: true },
  { key: "buffer_temp_c", label: "T Accumulo Puffer 200L", unit: "°C", color: "#f59e0b", yAxis: "yTemp", active: true },
  { key: "pdc_supply_temp_c", label: "T Mandata PdC", unit: "°C", color: "#ef4444", yAxis: "yTemp", active: true },
  { key: "pdc_return_temp_c", label: "T Ritorno PdC", unit: "°C", color: "#f43f5e", yAxis: "yTemp", active: false },
  { key: "indoor_temp_bticino_c", label: "T Interna Corridoio", unit: "°C", color: "#10b981", yAxis: "yTemp", active: true },
  { key: "indoor_setpoint_bticino_c", label: "Setpoint BTicino", unit: "°C", color: "#eab308", yAxis: "yTemp", borderDash: [5, 5], active: true },
  { key: "dhw_storage_temp_c", label: "T Bollitore ACS", unit: "°C", color: "#a855f7", yAxis: "yTemp", active: false },
  { key: "compressor_modulation_percent", label: "Modulazione Inverter (%)", unit: "%", color: "#facc15", yAxis: "yOther", active: true },
  { key: "hot_gas_pressure_bar", label: "Pressione Gas Caldo (bar)", unit: "bar", color: "#ec4899", yAxis: "yOther", active: false },
  { key: "cop_heating", label: "COP Riscaldamento", unit: "COP", color: "#34d399", yAxis: "yOther", active: false },
  { key: "humidity_percent", label: "Umidità Ambiente (%)", unit: "%", color: "#60a5fa", yAxis: "yOther", borderDash: [3, 3], active: false },
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

  // Determine latest valid timestamp from samples to prevent empty views on historic replays
  let latestMs = Date.now();
  for (let i = samples.length - 1; i >= 0; i--) {
    if (samples[i] && samples[i].timestamp_utc) {
      const parsed = new Date(samples[i].timestamp_utc).getTime();
      if (!isNaN(parsed) && parsed > 0) {
        latestMs = Math.max(latestMs, parsed);
        break;
      }
    }
  }

  const cutoff = latestMs - hours * 60 * 60 * 1000;
  
  const filtered = samples.filter(s => {
    if (!s || !s.timestamp_utc) return false;
    const d = new Date(s.timestamp_utc).getTime();
    return !isNaN(d) && d >= cutoff;
  });

  return filtered.length > 0 ? filtered : samples.slice(-Math.min(50, samples.length));
}

function getDatasets(samples) {
  return CHANNEL_DEFS.filter(ch => ch.active).map(ch => {
    const points = samples
      .filter(s => s && s.timestamp_utc)
      .map(s => {
        const val = s[ch.key];
        const num = (val !== null && val !== undefined && val !== "") ? Number(val) : null;
        return {
          x: new Date(s.timestamp_utc).getTime(),
          y: (num !== null && !isNaN(num)) ? num : null
        };
      })
      .filter(pt => !isNaN(pt.x));

    return {
      label: ch.label,
      data: points,
      borderColor: ch.color,
      backgroundColor: ch.color + "22",
      borderWidth: 2,
      pointRadius: points.length > 60 ? 0 : 3,
      pointHoverRadius: 6,
      tension: 0.2,
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

  if (telemetryChart) {
    telemetryChart.destroy();
  }

  const ctx = canvas.getContext("2d");
  telemetryChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: getDatasets(filtered)
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
          display: false, // Custom pills legend below
        },
        tooltip: {
          backgroundColor: "rgba(15, 23, 42, 0.95)",
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
              const day = String(d.getDate()).padStart(2, '0');
              const mon = String(d.getMonth() + 1).padStart(2, '0');
              const h = String(d.getHours()).padStart(2, '0');
              const m = String(d.getMinutes()).padStart(2, '0');
              const s = String(d.getSeconds()).padStart(2, '0');
              return `${day}/${mon} ${h}:${m}:${s}`;
            },
            label: function(context) {
              const chDef = CHANNEL_DEFS.find(ch => ch.label === context.dataset.label);
              const unit = chDef ? chDef.unit : "";
              const val = context.parsed.y;
              const formattedVal = (val !== null && val !== undefined)
                ? (typeof val === 'number' ? val.toLocaleString('it-IT', { maximumFractionDigits: 1 }) : val)
                : "--";
              return ` ${context.dataset.label}: ${formattedVal} ${unit}`.trim();
            }
          }
        }
      },
      scales: {
        x: {
          type: "time",
          time: {
            displayFormats: {
              millisecond: "HH:mm:ss",
              second: "HH:mm:ss",
              minute: "HH:mm",
              hour: "HH:mm",
              day: "dd/MM",
              month: "MM/yyyy",
              year: "yyyy"
            },
            tooltipFormat: "dd/MM/yyyy HH:mm:ss"
          },
          grid: { color: "rgba(51, 65, 85, 0.3)" },
          ticks: {
            color: "#94a3b8",
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 7,
            font: { size: 10 }
          }
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
