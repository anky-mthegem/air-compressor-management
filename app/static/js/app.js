/**
 * Air Compressor Management - SCADA Dashboard Controller
 * Handles WebSocket telemetry, real-time Canvas strip-charts, OEE gauges, and alarms.
 */

// Global State
const state = {
  telemetryHistory: [], // Recent 60 data points for live strip-chart
  maxHistoryPoints: 60,
  ws: null,
  reconnectAttempts: 0,
  hourlyOeeData: [],
  isTabVisible: true
};

// Initialize Dashboard
document.addEventListener("DOMContentLoaded", () => {
  initSystemStatus();
  initWebSocket();
  initOEEStats();
  initHourlyChart();
  initEventsFeed();
  initAnomalyControls();
  setupVisibilityHandling();
  startPeriodicRefresh();
});

// 1. Fetch System Meta (DB dialect, PLC mode)
async function initSystemStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    document.getElementById("dbDialectText").textContent = data.active_db || "MSSQL";
    document.getElementById("plcSourceText").textContent = 
      data.plc_mode === "PHYSICAL_S7_1200" ? "S7-1200 LIVE" : "S7-1200 SIM";
  } catch (err) {
    console.error("Failed to load system status:", err);
  }
}

// 2. WebSocket Connection for Live Telemetry
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    console.log("Connected to live telemetry WebSocket.");
    state.reconnectAttempts = 0;
  };

  state.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      updateDashboardTelemetry(data);
    } catch (e) {
      console.error("Error parsing telemetry packet:", e);
    }
  };

  state.ws.onclose = () => {
    console.warn("Telemetry WebSocket disconnected. Reconnecting in 3s...");
    state.reconnectAttempts++;
    setTimeout(initWebSocket, Math.min(10000, 3000 * state.reconnectAttempts));
  };

  state.ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// 3. Update DOM Elements with Fresh Telemetry
function updateDashboardTelemetry(t) {
  // Machine State Indicator
  const stateIndicator = document.getElementById("stateIndicator");
  const stateText = document.getElementById("stateText");
  const cyclePill = document.getElementById("cyclePill");

  if (t.fault) {
    stateIndicator.style.background = "rgba(239, 68, 68, 0.15)";
    stateIndicator.style.borderColor = "rgba(239, 68, 68, 0.4)";
    stateIndicator.style.color = "var(--accent-rose)";
    stateText.textContent = `TRIPPED (CODE ${t.fault_code || 'E-01'})`;
    cyclePill.textContent = "TRIPPED";
    cyclePill.style.background = "rgba(239, 68, 68, 0.2)";
    cyclePill.style.color = "var(--accent-rose)";
  } else if (t.loaded) {
    stateIndicator.style.background = "rgba(16, 185, 129, 0.12)";
    stateIndicator.style.borderColor = "rgba(16, 185, 129, 0.3)";
    stateIndicator.style.color = "var(--accent-emerald)";
    stateText.textContent = "RUNNING LOADED";
    cyclePill.textContent = "LOADED";
    cyclePill.style.background = "rgba(16, 185, 129, 0.15)";
    cyclePill.style.color = "var(--accent-emerald)";
  } else if (t.motor_running) {
    stateIndicator.style.background = "rgba(245, 158, 11, 0.12)";
    stateIndicator.style.borderColor = "rgba(245, 158, 11, 0.3)";
    stateIndicator.style.color = "var(--accent-amber)";
    stateText.textContent = "IDLING (UNLOADED)";
    cyclePill.textContent = "IDLING";
    cyclePill.style.background = "rgba(245, 158, 11, 0.15)";
    cyclePill.style.color = "var(--accent-amber)";
  } else {
    stateIndicator.style.background = "rgba(156, 163, 175, 0.12)";
    stateIndicator.style.borderColor = "rgba(156, 163, 175, 0.3)";
    stateIndicator.style.color = "var(--text-muted)";
    stateText.textContent = "STANDBY / STOPPED";
    cyclePill.textContent = "STANDBY";
  }

  // Pressures
  document.getElementById("valDischargePressure").textContent = t.discharge_pressure_bar.toFixed(2);
  document.getElementById("valHeaderPressure").textContent = t.header_pressure_bar.toFixed(2);
  const pPct = Math.min(100, Math.max(0, (t.discharge_pressure_bar / 10.0) * 100));
  document.getElementById("needlePressure").style.left = `${pPct}%`;

  // Temperatures
  const tempVal = document.getElementById("valAirendTemp");
  tempVal.textContent = t.airend_temp_c.toFixed(1);
  if (t.airend_temp_c >= 98.0) {
    tempVal.style.color = "var(--accent-rose)";
  } else if (t.airend_temp_c >= 92.0) {
    tempVal.style.color = "var(--accent-amber)";
  } else {
    tempVal.style.color = "#ffffff";
  }
  document.getElementById("valOilTemp").textContent = t.oil_temp_c.toFixed(1);
  const tPct = Math.min(100, Math.max(0, ((t.airend_temp_c - 40) / (110 - 40)) * 100));
  document.getElementById("needleTemp").style.left = `${tPct}%`;

  // Power, Current, Flow
  document.getElementById("valActivePower").textContent = t.active_power_kw.toFixed(1);
  document.getElementById("valCurrent").textContent = t.current_a.toFixed(1);
  document.getElementById("valPF").textContent = t.power_factor.toFixed(2);
  document.getElementById("valAirFlow").textContent = `${t.air_flow_cfm.toFixed(0)} CFM`;
  document.getElementById("valDewPoint").textContent = `${t.dew_point_c.toFixed(1)} °C`;

  // Separator & Air Filter Delta P
  const sepDP = document.getElementById("valSeparatorDP");
  sepDP.textContent = t.separator_dp_bar.toFixed(2);
  if (t.separator_dp_bar >= 0.8) {
    sepDP.style.color = "var(--accent-rose)";
  } else {
    sepDP.style.color = "#ffffff";
  }
  document.getElementById("valAirFilterDP").textContent = t.air_filter_dp_mbar.toFixed(0);

  // Schematic Nodes Callouts
  document.getElementById("nodeAirFilterDP").textContent = `ΔP ${t.air_filter_dp_mbar.toFixed(0)} mbar`;
  document.getElementById("nodeAirendTemp").textContent = `${t.airend_temp_c.toFixed(1)}°C`;
  document.getElementById("nodeSeparatorDP").textContent = `ΔP ${t.separator_dp_bar.toFixed(2)} bar`;
  document.getElementById("nodeDischargeP").textContent = `${t.discharge_pressure_bar.toFixed(2)} bar`;

  // Running Hours
  document.getElementById("valRunHours").textContent = `${t.run_hours.toFixed(1)} h`;
  document.getElementById("valLoadedHours").textContent = `${t.loaded_hours.toFixed(1)} h`;
  const duty = t.run_hours > 0 ? (t.loaded_hours / t.run_hours) * 100 : 75;
  document.getElementById("valDutyRatio").textContent = `${duty.toFixed(1)}%`;

  // Add point to Live Strip Chart History
  pushStripPoint(t);
}

// 4. Live Canvas Strip-Chart (60-second scrolling waveform)
function pushStripPoint(t) {
  state.telemetryHistory.push({
    time: new Date(),
    p: t.discharge_pressure_bar,
    kw: t.active_power_kw
  });

  if (state.telemetryHistory.length > state.maxHistoryPoints) {
    state.telemetryHistory.shift();
  }

  if (state.isTabVisible) {
    renderLiveStripChart();
  }
}

function renderLiveStripChart() {
  const canvas = document.getElementById("liveStripCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  // Handle high-DPI crispness
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
  }
  ctx.resetTransform();
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const padding = { top: 20, right: 40, bottom: 25, left: 45 };
  const graphW = w - padding.left - padding.right;
  const graphH = h - padding.top - padding.bottom;

  // Clear background
  ctx.clearRect(0, 0, w, h);

  // Draw Grid Lines (Horizontal)
  ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#6b7280";
  ctx.font = "10px 'JetBrains Mono', monospace";
  ctx.textAlign = "right";

  const numGridLines = 4;
  for (let i = 0; i <= numGridLines; i++) {
    const y = padding.top + (graphH / numGridLines) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(padding.left + graphW, y);
    ctx.stroke();

    // Pressure Y-Axis Label (Left, 0 - 10 bar)
    const pVal = (10 - (10 / numGridLines) * i).toFixed(1);
    ctx.fillText(`${pVal} bar`, padding.left - 6, y + 3);

    // Power Y-Axis Label (Right, 0 - 100 kW)
    const kwVal = (100 - (100 / numGridLines) * i).toFixed(0);
    ctx.textAlign = "left";
    ctx.fillText(`${kwVal} kW`, padding.left + graphW + 6, y + 3);
    ctx.textAlign = "right";
  }

  // Draw Target Pressure Band Highlight (6.5 - 7.5 bar)
  const yBandTop = padding.top + graphH * (1 - 7.5 / 10.0);
  const yBandBottom = padding.top + graphH * (1 - 6.5 / 10.0);
  ctx.fillStyle = "rgba(6, 182, 212, 0.08)";
  ctx.fillRect(padding.left, yBandTop, graphW, yBandBottom - yBandTop);

  const history = state.telemetryHistory;
  if (history.length < 2) return;

  const stepX = graphW / (state.maxHistoryPoints - 1);

  // Helper mapping
  const getX = (idx) => padding.left + (state.maxHistoryPoints - history.length + idx) * stepX;
  const getYP = (val) => padding.top + graphH * (1 - Math.min(10, Math.max(0, val)) / 10.0);
  const getYKW = (val) => padding.top + graphH * (1 - Math.min(100, Math.max(0, val)) / 100.0);

  // Trace 1: Active Power kW (Purple)
  ctx.beginPath();
  ctx.strokeStyle = "#8b5cf6";
  ctx.lineWidth = 2;
  for (let i = 0; i < history.length; i++) {
    const x = getX(i);
    const y = getYKW(history[i].kw);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Trace 2: Discharge Pressure bar (Cyan)
  ctx.beginPath();
  ctx.strokeStyle = "#06b6d4";
  ctx.lineWidth = 2.5;
  for (let i = 0; i < history.length; i++) {
    const x = getX(i);
    const y = getYP(history[i].p);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Glow on the latest point
  const lastX = getX(history.length - 1);
  const lastYP = getYP(history[history.length - 1].p);
  ctx.beginPath();
  ctx.arc(lastX, lastYP, 4, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.shadowColor = "#06b6d4";
  ctx.shadowBlur = 8;
  ctx.fill();
  ctx.shadowBlur = 0;
}

// 5. OEE Summary Metrics Calculation
async function initOEEStats() {
  try {
    const res = await fetch("/api/oee/summary?hours=24");
    const data = await res.json();

    // Overall OEE
    const oeeVal = data.oee_pct || 85.0;
    document.getElementById("valOEE").textContent = `${oeeVal.toFixed(1)}%`;
    
    // Radial SVG animation (circumference = 2 * PI * 50 = ~314.15)
    const circle = document.getElementById("oeeRadialFill");
    const offset = 314 - (314 * (oeeVal / 100.0));
    circle.style.strokeDashoffset = offset;

    // Pillars
    document.getElementById("valAvail").textContent = `${data.availability_pct.toFixed(1)}%`;
    document.getElementById("barAvail").style.width = `${data.availability_pct}%`;

    document.getElementById("valPerf").textContent = `${data.performance_pct.toFixed(1)}%`;
    document.getElementById("barPerf").style.width = `${data.performance_pct}%`;

    document.getElementById("valQual").textContent = `${data.quality_pct.toFixed(1)}%`;
    document.getElementById("barQual").style.width = `${data.quality_pct}%`;

    // SEC
    document.getElementById("valSEC").textContent = data.sec_kwh_per_m3.toFixed(3);
    const secTag = document.getElementById("valSECStatus");
    if (data.sec_kwh_per_m3 <= 0.12) {
      secTag.textContent = "OPTIMAL";
      secTag.style.background = "rgba(16, 185, 129, 0.2)";
      secTag.style.color = "var(--accent-emerald)";
    } else {
      secTag.textContent = "ELEVATED";
      secTag.style.background = "rgba(245, 158, 11, 0.2)";
      secTag.style.color = "var(--accent-amber)";
    }

  } catch (err) {
    console.error("Failed to load OEE summary:", err);
  }
}

// 6. 24-Hour OEE Profile Canvas Chart
async function initHourlyChart() {
  try {
    const res = await fetch("/api/oee/hourly?limit=24");
    state.hourlyOeeData = await res.json();
    renderHourlyOeeChart();
  } catch (err) {
    console.error("Failed to load hourly OEE trend:", err);
  }
}

function renderHourlyOeeChart() {
  const canvas = document.getElementById("hourlyOeeCanvas");
  if (!canvas || !state.hourlyOeeData.length) return;
  const ctx = canvas.getContext("2d");

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.resetTransform();
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const padding = { top: 15, right: 20, bottom: 25, left: 35 };
  const graphW = w - padding.left - padding.right;
  const graphH = h - padding.top - padding.bottom;

  ctx.clearRect(0, 0, w, h);

  // Target Reference Line (85%)
  const y85 = padding.top + graphH * (1 - 85 / 100.0);
  ctx.beginPath();
  ctx.strokeStyle = "rgba(245, 158, 11, 0.4)";
  ctx.setLineDash([4, 4]);
  ctx.moveTo(padding.left, y85);
  ctx.lineTo(padding.left + graphW, y85);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "rgba(245, 158, 11, 0.8)";
  ctx.font = "9px 'JetBrains Mono', monospace";
  ctx.fillText("Target: 85%", padding.left + 6, y85 - 4);

  // Draw Bars
  const count = state.hourlyOeeData.length;
  const barWidth = Math.max(8, (graphW / count) - 6);

  state.hourlyOeeData.forEach((d, idx) => {
    const x = padding.left + idx * (graphW / count) + 3;
    const barH = (d.oee / 100.0) * graphH;
    const y = padding.top + (graphH - barH);

    // Bar Color Gradient
    const grad = ctx.createLinearGradient(0, y, 0, y + barH);
    if (d.oee >= 85) {
      grad.addColorStop(0, "#06b6d4");
      grad.addColorStop(1, "rgba(6, 182, 212, 0.3)");
    } else {
      grad.addColorStop(0, "#f59e0b");
      grad.addColorStop(1, "rgba(245, 158, 11, 0.3)");
    }

    ctx.fillStyle = grad;
    ctx.fillRect(x, y, barWidth, barH);

    // Hour Label every 3 bars
    if (idx % 3 === 0 || idx === count - 1) {
      ctx.fillStyle = "#6b7280";
      ctx.font = "9px 'Inter', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(d.time, x + barWidth / 2, h - 6);
    }
  });
}

// 7. System Events Feed
async function initEventsFeed() {
  try {
    const res = await fetch("/api/events?limit=8");
    const events = await res.json();
    const tbody = document.getElementById("eventsTableBody");
    tbody.innerHTML = "";

    document.getElementById("eventsCount").textContent = `${events.length} Events`;

    events.forEach(ev => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-size: 0.72rem;">${ev.timestamp.split(" ")[1]}</td>
        <td><span class="badge-severity ${ev.severity}">${ev.severity}</span></td>
        <td style="font-size: 0.72rem; color: var(--text-muted);">${ev.event_type}</td>
        <td>${ev.description}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load events feed:", err);
  }
}

// 8. Anomaly Injection Controls
function initAnomalyControls() {
  const btn = document.getElementById("btnInjectAnomaly");
  const select = document.getElementById("anomalySelect");

  btn.addEventListener("click", async () => {
    const choice = select.value;
    try {
      btn.disabled = true;
      btn.textContent = "Applying...";
      const res = await fetch("/api/simulator/anomaly", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anomaly_type: choice })
      });
      const data = await res.json();
      console.log(data.message);
      // Refresh events immediately
      setTimeout(initEventsFeed, 1000);
    } catch (e) {
      console.error("Failed to inject anomaly:", e);
    } finally {
      btn.disabled = false;
      btn.textContent = "Inject";
    }
  });
}

// 9. Performance & Battery Optimization (content-visibility & tab visibility)
function setupVisibilityHandling() {
  document.addEventListener("visibilitychange", () => {
    state.isTabVisible = !document.hidden;
    if (state.isTabVisible) {
      renderLiveStripChart();
    }
  });

  // Re-render canvases on window resize
  window.addEventListener("resize", () => {
    renderLiveStripChart();
    renderHourlyOeeChart();
  });
}

// 10. Periodic Background Sync
function startPeriodicRefresh() {
  setInterval(() => {
    if (state.isTabVisible) {
      initOEEStats();
      initEventsFeed();
    }
  }, 15000);
}
