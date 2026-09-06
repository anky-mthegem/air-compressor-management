/**
 * Air Compressor Management - Siemens S7-1200 PLC Diagnostics Controller
 * Handles live Data Block register table, animated watchdog heartbeat, socket probing, and fault alarms.
 */

const plcState = {
  status: "CONNECTED",
  datapoints: [],
  lastCounter: 0,
  heartbeatHistory: [],
  maxHeartbeatPoints: 80,
  simulatedDisconnectActive: false,
  pollTimer: null
};

document.addEventListener("DOMContentLoaded", () => {
  initPlcPage();
  initHeartbeatCanvas();
  initActionButtons();
  initSearchFilter();
  startPlcPolling();
});

// 1. Initial Page Load
async function initPlcPage() {
  await fetchPlcStatus();
  await fetchDatapoints();
}

// 2. Fetch PLC Connection Status & Watchdog Metrics
async function fetchPlcStatus() {
  try {
    const res = await fetch("/api/plc/status");
    const data = await res.json();
    plcState.status = data.status;

    // Header State Indicator
    const indicator = document.getElementById("plcStateIndicator");
    const stateText = document.getElementById("plcStateText");
    const bannerBadge = document.getElementById("bannerBadge");
    const bannerTitle = document.getElementById("bannerStatusTitle");
    const bannerSub = document.getElementById("bannerStatusSub");

    if (data.status === "CONNECTED") {
      indicator.style.background = "rgba(16, 185, 129, 0.12)";
      indicator.style.borderColor = "rgba(16, 185, 129, 0.3)";
      indicator.style.color = "var(--accent-emerald)";
      stateText.textContent = "S7-1200 ONLINE";

      bannerBadge.className = "banner-status-badge connected";
      bannerTitle.textContent = "PLC LINK CONNECTED";
      bannerSub.textContent = `ISO-on-TCP (Port 102) Active Communication with ${data.ip_address}`;
    } else if (data.status === "WATCHDOG_TIMEOUT") {
      indicator.style.background = "rgba(239, 68, 68, 0.15)";
      indicator.style.borderColor = "rgba(239, 68, 68, 0.4)";
      indicator.style.color = "var(--accent-rose)";
      stateText.textContent = "WATCHDOG TIMEOUT";

      bannerBadge.className = "banner-status-badge watchdog_timeout";
      bannerTitle.textContent = "COMMUNICATION WATCHDOG TIMEOUT";
      bannerSub.textContent = data.error_reason || "Heartbeat counter stopped updating.";
    } else {
      indicator.style.background = "rgba(239, 68, 68, 0.15)";
      indicator.style.borderColor = "rgba(239, 68, 68, 0.4)";
      indicator.style.color = "var(--accent-rose)";
      stateText.textContent = "PLC DISCONNECTED";

      bannerBadge.className = "banner-status-badge disconnected";
      bannerTitle.textContent = "PLC LINK DISCONNECTED";
      bannerSub.textContent = data.error_reason || "Cannot establish connection to S7-1200 CPU.";
    }

    // Network stats
    document.getElementById("valLatency").textContent = `${data.latency_ms} ms`;
    document.getElementById("valPackets").textContent = `${data.packets_received} / ${data.packets_sent}`;
    document.getElementById("valLoss").textContent = `${data.packet_loss_pct}%`;
    document.getElementById("valLastPoll").textContent = `${data.last_poll_seconds_ago}s ago`;

    // Watchdog Counters & Bar
    document.getElementById("valPlcCounter").textContent = data.handshake.plc_counter;
    document.getElementById("valEchoCounter").textContent = data.handshake.app_echo_counter;

    // Push pulse to heartbeat waveform
    const counterChanged = data.handshake.plc_counter !== plcState.lastCounter;
    plcState.lastCounter = data.handshake.plc_counter;
    pushHeartbeatPoint(counterChanged && data.status === "CONNECTED");

    // Watchdog countdown bar
    const timeoutThreshold = data.handshake.timeout_sec || 5.0;
    const elapsed = data.handshake.seconds_since_heartbeat || 0;
    const remainingPct = Math.max(0, 100 - (elapsed / timeoutThreshold) * 100);
    const timerFill = document.getElementById("watchdogTimerFill");
    timerFill.style.width = `${remainingPct}%`;

    if (remainingPct < 30) {
      timerFill.style.background = "var(--accent-rose)";
    } else if (remainingPct < 60) {
      timerFill.style.background = "var(--accent-amber)";
    } else {
      timerFill.style.background = "linear-gradient(90deg, #10b981, #06b6d4)";
    }

    // Handshake form state
    document.getElementById("chkHandshakeEnabled").checked = data.handshake.enabled;
    document.getElementById("rngWatchdogTimeout").value = data.handshake.timeout_sec;
    document.getElementById("valWatchdogTimeoutDisplay").textContent = `${data.handshake.timeout_sec.toFixed(1)} seconds`;
    document.getElementById("lblTimeoutThreshold").textContent = `Watchdog Limit: ${data.handshake.timeout_sec.toFixed(1)}s`;

  } catch (err) {
    console.error("Failed to fetch PLC status:", err);
  }
}

// 3. Fetch Full Data Block Register Exchange
async function fetchDatapoints() {
  try {
    const res = await fetch("/api/plc/datapoints");
    plcState.datapoints = await res.json();
    renderDatapointsTable();
  } catch (err) {
    console.error("Failed to fetch datapoints:", err);
  }
}

// 4. Render Data Points Table
function renderDatapointsTable() {
  const tbody = document.getElementById("datapointsTableBody");
  if (!tbody) return;

  const filter = (document.getElementById("searchDataPoints")?.value || "").toLowerCase();
  const rows = plcState.datapoints.filter(dp => 
    dp.offset.toLowerCase().includes(filter) ||
    dp.name.toLowerCase().includes(filter) ||
    dp.type.toLowerCase().includes(filter)
  );

  document.getElementById("datapointsCount").textContent = `${rows.length} Points Mapped`;

  let html = "";
  rows.forEach(dp => {
    let valFormatted = dp.val;
    if (dp.type === "BOOL") {
      valFormatted = dp.val 
        ? '<span class="bool-true">TRUE (1)</span>' 
        : '<span class="bool-false">FALSE (0)</span>';
    } else if (typeof dp.val === "number") {
      valFormatted = Number.isInteger(dp.val) ? dp.val : dp.val.toFixed(2);
    }

    html += `
      <tr>
        <td><span class="db-offset-badge">${dp.offset}</span></td>
        <td><strong>${dp.name}</strong></td>
        <td><span class="type-pill">${dp.type}</span></td>
        <td><span class="dir-pill">${dp.dir}</span></td>
        <td class="live-val-cell">${valFormatted}</td>
        <td>${dp.unit}</td>
        <td><span class="quality-badge ${dp.quality}">${dp.quality}</span></td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// 5. Animated EKG Heartbeat Waveform Canvas
function initHeartbeatCanvas() {
  for (let i = 0; i < plcState.maxHeartbeatPoints; i++) {
    plcState.heartbeatHistory.push(0);
  }
  requestAnimationFrame(drawHeartbeatLoop);
}

function pushHeartbeatPoint(hasPulse) {
  if (hasPulse) {
    // Inject realistic EKG QRS spike
    plcState.heartbeatHistory.push(-0.2);
    plcState.heartbeatHistory.push(1.0);
    plcState.heartbeatHistory.push(-0.4);
    plcState.heartbeatHistory.push(0.1);
  } else {
    plcState.heartbeatHistory.push(0);
  }

  while (plcState.heartbeatHistory.length > plcState.maxHeartbeatPoints) {
    plcState.heartbeatHistory.shift();
  }
}

function drawHeartbeatLoop() {
  const canvas = document.getElementById("heartbeatCanvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
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
    const midY = h / 2;

    ctx.clearRect(0, 0, w, h);

    // Baseline grid
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(w, midY);
    ctx.stroke();

    const history = plcState.heartbeatHistory;
    const stepX = w / (plcState.maxHeartbeatPoints - 1);

    ctx.beginPath();
    ctx.strokeStyle = plcState.status === "CONNECTED" ? "#06b6d4" : "#ef4444";
    ctx.lineWidth = 2;
    ctx.shadowColor = plcState.status === "CONNECTED" ? "rgba(6, 182, 212, 0.6)" : "rgba(239, 68, 68, 0.6)";
    ctx.shadowBlur = 8;

    for (let i = 0; i < history.length; i++) {
      const x = i * stepX;
      const y = midY - history[i] * (h * 0.38);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  requestAnimationFrame(drawHeartbeatLoop);
}

// 6. Action Buttons & Diagnostics
function initActionButtons() {
  // Socket Probe (Port 102)
  const btnProbe = document.getElementById("btnProbeSocket");
  btnProbe.addEventListener("click", async () => {
    btnProbe.disabled = true;
    btnProbe.textContent = "Probing Port 102...";
    logTerminal("info", "Probing Siemens S7 ISO-on-TCP Port 102 socket...");

    try {
      const res = await fetch("/api/plc/probe", { method: "POST" });
      const result = await res.json();
      if (result.port_102_open) {
        logTerminal("success", `[PROBE SUCCESS] ${result.diagnostic_message}`);
      } else {
        logTerminal("error", `[PROBE FAILED] ${result.diagnostic_message}`);
      }
    } catch (e) {
      logTerminal("error", `[PROBE ERROR] ${e.message}`);
    } finally {
      btnProbe.disabled = false;
      btnProbe.textContent = "🔍 Probe Socket (Port 102)";
    }
  });

  // Reconnect Driver
  const btnReconnect = document.getElementById("btnReconnect");
  btnReconnect.addEventListener("click", async () => {
    btnReconnect.disabled = true;
    btnReconnect.textContent = "Reconnecting...";
    logTerminal("info", "Restarting S7comm connection session...");

    try {
      const res = await fetch("/api/plc/reconnect", { method: "POST" });
      const data = await res.json();
      logTerminal("success", `[RECONNECT] ${data.message}`);
      plcState.simulatedDisconnectActive = false;
      document.getElementById("btnSimulateDisconnect").textContent = "⚡ Simulate Disconnect";
      await fetchPlcStatus();
    } catch (e) {
      logTerminal("error", `[RECONNECT ERROR] ${e.message}`);
    } finally {
      btnReconnect.disabled = false;
      btnReconnect.textContent = "🔄 Reconnect Driver";
    }
  });

  // Simulate Disconnect Toggle
  const btnSim = document.getElementById("btnSimulateDisconnect");
  btnSim.addEventListener("click", async () => {
    plcState.simulatedDisconnectActive = !plcState.simulatedDisconnectActive;
    btnSim.textContent = plcState.simulatedDisconnectActive ? "🔌 Restore Connection" : "⚡ Simulate Disconnect";
    logTerminal("warn", `[SIMULATOR] Force disconnect toggled: ${plcState.simulatedDisconnectActive}`);

    try {
      await fetch("/api/plc/simulate_disconnect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ simulate_disconnect: plcState.simulatedDisconnectActive })
      });
      await fetchPlcStatus();
    } catch (e) {
      logTerminal("error", `Error: ${e.message}`);
    }
  });

  // Handshake Form Submit
  const form = document.getElementById("handshakeForm");
  const rngTimeout = document.getElementById("rngWatchdogTimeout");
  const valDisplay = document.getElementById("valWatchdogTimeoutDisplay");

  rngTimeout.addEventListener("input", (e) => {
    valDisplay.textContent = `${parseFloat(e.target.value).toFixed(1)} seconds`;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const enabled = document.getElementById("chkHandshakeEnabled").checked;
    const timeout = parseFloat(rngTimeout.value);

    try {
      const res = await fetch("/api/plc/handshake/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled, timeout_sec: timeout })
      });
      const data = await res.json();
      logTerminal("success", `[HANDSHAKE] Settings saved: Watchdog=${enabled ? 'ON' : 'OFF'}, Timeout=${timeout}s`);
    } catch (err) {
      logTerminal("error", `Failed to save handshake settings: ${err.message}`);
    }
  });

  // Clear Terminal
  document.getElementById("btnClearLog").addEventListener("click", () => {
    document.getElementById("terminalLog").innerHTML = "";
  });
}

// 7. Search & Filter Data Points
function initSearchFilter() {
  const searchInput = document.getElementById("searchDataPoints");
  searchInput.addEventListener("input", () => {
    renderDatapointsTable();
  });
}

function logTerminal(level, text) {
  const term = document.getElementById("terminalLog");
  if (!term) return;
  const time = new Date().toLocaleTimeString();
  const div = document.createElement("div");
  div.className = `terminal-line ${level}`;
  div.textContent = `[${time}] ${text}`;
  term.appendChild(div);
  term.scrollTop = term.scrollHeight;
}

// 8. Cyclic Polling
function startPlcPolling() {
  setInterval(async () => {
    if (!document.hidden) {
      await fetchPlcStatus();
      await fetchDatapoints();
    }
  }, 1500);
}
