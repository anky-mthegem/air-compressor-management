/**
 * Air Compressor Management - SQL Database Viewer Controller
 * Handles table switching, querying, dynamic sorting, pagination, and CSV exports.
 */

(function () {
  'use strict';

  // State
  const state = {
    currentTable: 'telemetry',
    currentPage: 1,
    pageSize: 50,
    timeFilter: 'all',
    startDate: '',
    endDate: '',
    searchQuery: '',
    eventSeverity: 'ALL',
    motorState: 'ALL',
    sortCol: null,
    sortDir: 'desc',
    autoRefreshSec: 0,
    refreshIntervalId: null,
    columnsMeta: []
  };

  // Friendly column labels and unit suffixes
  const COLUMN_LABELS = {
    id: 'ID',
    timestamp: 'Timestamp',
    hour_timestamp: 'Hour',
    created_at: 'Registered At',
    tag: 'Compressor Tag',
    name: 'Machine Name',
    rated_power_kw: 'Rated Power (kW)',
    rated_flow_cfm: 'Rated Flow (CFM)',
    nominal_pressure_bar: 'Nominal Press (bar)',
    motor_running: 'Motor',
    loaded: 'Loaded',
    standby: 'Standby',
    fault: 'Fault',
    fault_code: 'Fault Code',
    discharge_pressure_bar: 'Discharge P (bar)',
    header_pressure_bar: 'Header P (bar)',
    airend_temp_c: 'Airend Temp (°C)',
    oil_temp_c: 'Oil Temp (°C)',
    oil_pressure_bar: 'Oil Press (bar)',
    ambient_temp_c: 'Ambient Temp (°C)',
    separator_dp_bar: 'Separator ΔP (bar)',
    air_filter_dp_mbar: 'Air Filter ΔP (mbar)',
    oil_filter_dp_bar: 'Oil Filter ΔP (bar)',
    active_power_kw: 'Active Power (kW)',
    current_a: 'Current (A)',
    voltage_v: 'Voltage (V)',
    power_factor: 'P.F.',
    cumulative_energy_kwh: 'Energy (kWh)',
    air_flow_cfm: 'Air Flow (CFM)',
    dew_point_c: 'Dew Point (°C)',
    run_hours: 'Run Hours',
    loaded_hours: 'Loaded Hours',
    event_type: 'Event Type',
    severity: 'Severity',
    description: 'Description',
    old_state: 'Previous State',
    new_state: 'New State',
    planned_minutes: 'Planned (min)',
    operating_minutes: 'Operating (min)',
    loaded_minutes: 'Loaded (min)',
    unloaded_minutes: 'Unloaded (min)',
    down_minutes: 'Down (min)',
    total_energy_kwh: 'Total Energy (kWh)',
    total_air_m3: 'Total Air (m³)',
    specific_energy_kwh_m3: 'SEC (kWh/m³)',
    availability_pct: 'Availability %',
    performance_pct: 'Performance %',
    quality_pct: 'Quality %',
    oee_pct: 'Overall OEE %'
  };

  // DOM Elements
  const els = {
    viewerTimezone: document.getElementById('viewerTimezone'),
    dbDialectBadge: document.getElementById('viewerDbDialect'),
    dbDot: document.getElementById('viewerDbDot'),
    totalRowsText: document.getElementById('viewerTotalRows'),
    kpiGrid: document.getElementById('kpiSummaryGrid'),
    tableTabs: document.querySelectorAll('.table-tab-btn'),
    timePills: document.querySelectorAll('.time-pill-btn'),
    searchInput: document.getElementById('tableSearchInput'),
    pageSizeSelect: document.getElementById('pageSizeSelect'),
    contextFilterSelect: document.getElementById('contextFilterSelect'),
    contextFilterLabel: document.getElementById('contextFilterLabel'),
    autoRefreshSelect: document.getElementById('autoRefreshSelect'),
    btnRefresh: document.getElementById('btnViewerRefresh'),
    btnExportCsv: document.getElementById('btnExportCsv'),
    tableHead: document.getElementById('scadaTableHead'),
    tableBody: document.getElementById('scadaTableBody'),
    paginationFooter: document.getElementById('tablePaginationFooter'),
    recordsCountText: document.getElementById('paginationInfoText'),
    paginationControls: document.getElementById('paginationControls')
  };

  /**
   * Initializes application and attaches event listeners.
   */
  async function init() {
    setupEventListeners();
    await loadDatabaseOverview();
    await loadTableData();
  }

  /**
   * Sets up UI event bindings.
   */
  function setupEventListeners() {
    // 1. Table switcher tabs
    els.tableTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const targetTable = tab.getAttribute('data-table');
        if (targetTable === state.currentTable) return;

        els.tableTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        state.currentTable = targetTable;
        state.currentPage = 1;
        state.sortCol = null;
        state.sortDir = 'desc';
        state.searchQuery = '';
        if (els.searchInput) els.searchInput.value = '';

        updateContextFilterOptions();
        loadTableData();
      });
    });

    // 2. Time range pills
    els.timePills.forEach(pill => {
      pill.addEventListener('click', () => {
        const filterVal = pill.getAttribute('data-time');
        els.timePills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');

        state.timeFilter = filterVal;
        state.currentPage = 1;
        loadTableData();
      });
    });

    // 3. Search debounce
    let searchDebounceTimer = null;
    if (els.searchInput) {
      els.searchInput.addEventListener('input', (e) => {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
          state.searchQuery = e.target.value.trim();
          state.currentPage = 1;
          loadTableData();
        }, 300);
      });
    }

    // 4. Page size selector
    if (els.pageSizeSelect) {
      els.pageSizeSelect.addEventListener('change', (e) => {
        state.pageSize = parseInt(e.target.value, 10);
        state.currentPage = 1;
        loadTableData();
      });
    }

    // 5. Contextual filter (Severity / Motor State)
    if (els.contextFilterSelect) {
      els.contextFilterSelect.addEventListener('change', (e) => {
        const val = e.target.value;
        if (state.currentTable === 'events') {
          state.eventSeverity = val;
        } else if (state.currentTable === 'telemetry') {
          state.motorState = val;
        }
        state.currentPage = 1;
        loadTableData();
      });
    }

    // 6. Manual refresh button
    if (els.btnRefresh) {
      els.btnRefresh.addEventListener('click', () => {
        loadDatabaseOverview();
        loadTableData();
      });
    }

    // 7. CSV Export button
    if (els.btnExportCsv) {
      els.btnExportCsv.addEventListener('click', handleCsvExport);
    }

    // 8. Auto-refresh dropdown
    if (els.autoRefreshSelect) {
      els.autoRefreshSelect.addEventListener('change', (e) => {
        const sec = parseInt(e.target.value, 10);
        state.autoRefreshSec = sec;
        clearInterval(state.refreshIntervalId);

        if (sec > 0) {
          state.refreshIntervalId = setInterval(() => {
            loadDatabaseOverview();
            loadTableData(true);
          }, sec * 1000);
        }
      });
    }
  }

  /**
   * Adjusts contextual filter dropdown based on active table.
   */
  function updateContextFilterOptions() {
    if (!els.contextFilterSelect || !els.contextFilterLabel) return;

    if (state.currentTable === 'events') {
      els.contextFilterLabel.textContent = 'Severity:';
      els.contextFilterSelect.style.display = 'inline-block';
      els.contextFilterLabel.style.display = 'inline-block';
      els.contextFilterSelect.innerHTML = `
        <option value="ALL">All Severities</option>
        <option value="CRITICAL">Critical Alarms</option>
        <option value="WARNING">Warnings</option>
        <option value="INFO">Informational</option>
      `;
      els.contextFilterSelect.value = state.eventSeverity;
    } else if (state.currentTable === 'telemetry') {
      els.contextFilterLabel.textContent = 'State:';
      els.contextFilterSelect.style.display = 'inline-block';
      els.contextFilterLabel.style.display = 'inline-block';
      els.contextFilterSelect.innerHTML = `
        <option value="ALL">All States</option>
        <option value="running">Running Only</option>
        <option value="loaded">Loaded Only</option>
        <option value="standby">Standby Only</option>
        <option value="fault">Faulted Only</option>
      `;
      els.contextFilterSelect.value = state.motorState;
    } else {
      els.contextFilterSelect.style.display = 'none';
      els.contextFilterLabel.style.display = 'none';
    }
  }

  /**
   * Fetches database overview and counts.
   */
  async function loadDatabaseOverview() {
    try {
      const resp = await fetch('/api/data/overview');
      if (!resp.ok) return;
      const data = await resp.json();

      if (els.viewerTimezone && data.timezone_label) {
        els.viewerTimezone.textContent = data.timezone_label;
      }
      if (els.dbDialectBadge) {
        els.dbDialectBadge.textContent = data.active_db || 'SQLite';
      }
      if (els.totalRowsText) {
        els.totalRowsText.textContent = data.total_rows.toLocaleString() + ' logged rows';
      }

      // Update badge counts on table tabs
      if (data.tables) {
        Object.keys(data.tables).forEach(key => {
          const tab = document.querySelector(`.table-tab-btn[data-table="${key}"]`);
          if (tab) {
            const badge = tab.querySelector('.table-count-badge');
            if (badge) {
              badge.textContent = (data.tables[key].row_count || 0).toLocaleString();
            }
          }
        });
      }
    } catch (err) {
      console.warn('Failed to load database overview:', err);
    }
  }

  /**
   * Fetches paginated records and updates UI.
   */
  async function loadTableData(isSilent = false) {
    if (!isSilent) {
      showLoadingState();
    }

    try {
      const params = new URLSearchParams({
        table: state.currentTable,
        page: state.currentPage,
        limit: state.pageSize,
        sort_dir: state.sortDir,
        time_filter: state.timeFilter
      });

      if (state.sortCol) params.append('sort_col', state.sortCol);
      if (state.searchQuery) params.append('search', state.searchQuery);
      if (state.startDate) params.append('start_date', state.startDate);
      if (state.endDate) params.append('end_date', state.endDate);

      if (state.currentTable === 'events' && state.eventSeverity !== 'ALL') {
        params.append('event_severity', state.eventSeverity);
      }
      if (state.currentTable === 'telemetry' && state.motorState !== 'ALL') {
        params.append('motor_state', state.motorState);
      }

      const resp = await fetch(`/api/data/records?${params.toString()}`);
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const data = await resp.json();
      renderKpiCards(data.table, data.metrics, data.total_records);
      renderTableHeaders(data.columns);
      renderTableRows(data.rows, data.columns);
      renderPagination(data.page, data.total_pages, data.total_records, data.limit);
    } catch (err) {
      console.error('Error loading table data:', err);
      showErrorState(err.message);
    }
  }

  /**
   * Renders the top summary KPI cards depending on the active table.
   */
  function renderKpiCards(tableKey, metrics, totalRecords) {
    if (!els.kpiGrid) return;

    let html = '';
    if (tableKey === 'telemetry') {
      const avgP = metrics.avg_discharge_pressure_bar ?? 0;
      const maxP = metrics.max_discharge_pressure_bar ?? 0;
      const avgKw = metrics.avg_power_kw ?? 0;
      const avgT = metrics.avg_airend_temp_c ?? 0;

      html = `
        <div class="kpi-card">
          <span class="kpi-label">Logged Records</span>
          <div class="kpi-value">${totalRecords.toLocaleString()}</div>
          <span class="kpi-subtext">Active telemetry samples</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Avg Discharge Pressure</span>
          <div class="kpi-value">${avgP} <span class="kpi-unit">bar</span></div>
          <span class="kpi-subtext">Peak: ${maxP} bar</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Avg Active Power</span>
          <div class="kpi-value">${avgKw} <span class="kpi-unit">kW</span></div>
          <span class="kpi-subtext">GA-75 VSD Inverter</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Avg Airend Temperature</span>
          <div class="kpi-value">${avgT} <span class="kpi-unit">°C</span></div>
          <span class="kpi-subtext">Warning threshold: 95.0°C</span>
        </div>
      `;
    } else if (tableKey === 'events') {
      const crit = metrics.critical_events ?? 0;
      const warn = metrics.warning_events ?? 0;
      const info = metrics.info_events ?? 0;

      html = `
        <div class="kpi-card">
          <span class="kpi-label">Total Events Logged</span>
          <div class="kpi-value">${totalRecords.toLocaleString()}</div>
          <span class="kpi-subtext">Alarms, trips & state shifts</span>
        </div>
        <div class="kpi-card" style="border-color: rgba(239, 68, 68, 0.3);">
          <span class="kpi-label" style="color: #f87171;">Critical Emergency Trips</span>
          <div class="kpi-value" style="color: #f87171;">${crit}</div>
          <span class="kpi-subtext">Requires operator reset</span>
        </div>
        <div class="kpi-card" style="border-color: rgba(245, 158, 11, 0.3);">
          <span class="kpi-label" style="color: #fbbf24;">Warning Events</span>
          <div class="kpi-value" style="color: #fbbf24;">${warn}</div>
          <span class="kpi-subtext">High temp / filter DP alerts</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Informational Logs</span>
          <div class="kpi-value">${info}</div>
          <span class="kpi-subtext">Operational transitions</span>
        </div>
      `;
    } else if (tableKey === 'oee') {
      const avgOee = metrics.avg_oee_pct ?? 0;
      const energy = (metrics.sum_energy_kwh ?? 0).toLocaleString();
      const air = (metrics.sum_air_m3 ?? 0).toLocaleString();
      const hours = metrics.total_hours ?? 0;

      html = `
        <div class="kpi-card">
          <span class="kpi-label">Logged Shift Hours</span>
          <div class="kpi-value">${totalRecords.toLocaleString()} <span class="kpi-unit">hrs</span></div>
          <span class="kpi-subtext">Hourly batch aggregates</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Average OEE</span>
          <div class="kpi-value" style="color: #34d399;">${avgOee} <span class="kpi-unit">%</span></div>
          <span class="kpi-subtext">Target: 85.0% (World Class)</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Cumulative Energy</span>
          <div class="kpi-value">${energy} <span class="kpi-unit">kWh</span></div>
          <span class="kpi-subtext">Active electrical power</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Air Volume Output</span>
          <div class="kpi-value">${air} <span class="kpi-unit">m³</span></div>
          <span class="kpi-subtext">Delivered to main plant header</span>
        </div>
      `;
    } else if (tableKey === 'master') {
      html = `
        <div class="kpi-card">
          <span class="kpi-label">Configured Compressors</span>
          <div class="kpi-value">${totalRecords}</div>
          <span class="kpi-subtext">GA-75 VSD Fleet Master</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Motor Rating</span>
          <div class="kpi-value">75.0 <span class="kpi-unit">kW</span></div>
          <span class="kpi-subtext">Variable Speed Drive</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Nominal Delivery</span>
          <div class="kpi-value">480.0 <span class="kpi-unit">CFM</span></div>
          <span class="kpi-subtext">At 7.0 bar operating pressure</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Storage Engine</span>
          <div class="kpi-value" style="font-size: 1.25rem;">SQL Server / SQLite</div>
          <span class="kpi-subtext">Automatic dual-mode persistence</span>
        </div>
      `;
    }

    els.kpiGrid.innerHTML = html;
  }

  /**
   * Renders the table column header row with clickable sorting.
   */
  function renderTableHeaders(columns) {
    if (!els.tableHead) return;

    let tr = document.createElement('tr');
    columns.forEach(col => {
      const th = document.createElement('th');
      th.setAttribute('data-col', col);

      const label = COLUMN_LABELS[col] || col;
      let sortIndicator = '⇅';
      if (state.sortCol === col) {
        th.classList.add('sorted');
        sortIndicator = state.sortDir === 'asc' ? '▲' : '▼';
      }

      th.innerHTML = `${label} <span class="sort-icon">${sortIndicator}</span>`;
      th.addEventListener('click', () => {
        if (state.sortCol === col) {
          state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          state.sortCol = col;
          state.sortDir = 'desc';
        }
        state.currentPage = 1;
        loadTableData();
      });

      tr.appendChild(th);
    });

    els.tableHead.innerHTML = '';
    els.tableHead.appendChild(tr);
  }

  /**
   * Formats a cell value based on column name and data type.
   */
  function formatCellValue(col, val) {
    if (val === null || val === undefined) {
      return '<span style="color: var(--text-muted);">-</span>';
    }

    // Boolean formatting
    if (typeof val === 'boolean') {
      if (col === 'fault') {
        return val 
          ? '<span class="badge-bool fault-true">TRIP</span>'
          : '<span class="badge-bool false">OK</span>';
      }
      return val
        ? `<span class="badge-bool true">${COLUMN_LABELS[col] || 'YES'}</span>`
        : `<span class="badge-bool false">NO</span>`;
    }

    // Severity formatting
    if (col === 'severity') {
      const sev = String(val).toUpperCase();
      let cls = 'info';
      if (sev === 'CRITICAL') cls = 'critical';
      else if (sev === 'WARNING') cls = 'warning';
      return `<span class="badge-severity ${cls}">${sev}</span>`;
    }

    // Timestamp formatting
    if (col === 'timestamp' || col === 'hour_timestamp' || col === 'created_at') {
      return `<span class="cell-timestamp">${val}</span>`;
    }

    // ID formatting
    if (col === 'id' || col === 'compressor_id' || col === 'fault_code') {
      return `<span class="cell-id">${val}</span>`;
    }

    // Number formatting
    if (typeof val === 'number') {
      return `<span class="cell-number">${val.toLocaleString(undefined, { minimumFractionDigits: (val % 1 !== 0 ? 1 : 0), maximumFractionDigits: 2 })}</span>`;
    }

    return String(val);
  }

  /**
   * Renders rows into the table body.
   */
  function renderTableRows(rows, columns) {
    if (!els.tableBody) return;

    if (!rows || rows.length === 0) {
      els.tableBody.innerHTML = `
        <tr>
          <td colspan="${columns.length}" class="table-empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">No matching records found</div>
            <div class="empty-state-desc">Try adjusting your time window or filter criteria.</div>
          </td>
        </tr>
      `;
      return;
    }

    const fragment = document.createDocumentFragment();
    rows.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        td.innerHTML = formatCellValue(col, row[col]);
        tr.appendChild(td);
      });
      fragment.appendChild(tr);
    });

    els.tableBody.innerHTML = '';
    els.tableBody.appendChild(fragment);
  }

  /**
   * Renders the pagination footer controls.
   */
  function renderPagination(currentPage, totalPages, totalRecords, limit) {
    if (!els.recordsCountText || !els.paginationControls) return;

    const start = totalRecords === 0 ? 0 : (currentPage - 1) * limit + 1;
    const end = Math.min(currentPage * limit, totalRecords);

    els.recordsCountText.textContent = `Showing ${start.toLocaleString()} - ${end.toLocaleString()} of ${totalRecords.toLocaleString()} rows`;

    let html = `
      <button class="page-btn" id="btnPageFirst" ${currentPage <= 1 ? 'disabled' : ''} title="First Page">«</button>
      <button class="page-btn" id="btnPagePrev" ${currentPage <= 1 ? 'disabled' : ''} title="Previous Page">‹</button>
    `;

    // Page window
    let startPage = Math.max(1, currentPage - 2);
    let endPage = Math.min(totalPages, startPage + 4);
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4);
    }

    for (let p = startPage; p <= endPage; p++) {
      html += `<button class="page-btn ${p === currentPage ? 'active' : ''}" data-page="${p}">${p}</button>`;
    }

    html += `
      <button class="page-btn" id="btnPageNext" ${currentPage >= totalPages ? 'disabled' : ''} title="Next Page">›</button>
      <button class="page-btn" id="btnPageLast" ${currentPage >= totalPages ? 'disabled' : ''} title="Last Page">»</button>
    `;

    els.paginationControls.innerHTML = html;

    // Attach pagination button listeners
    const firstBtn = document.getElementById('btnPageFirst');
    const prevBtn = document.getElementById('btnPagePrev');
    const nextBtn = document.getElementById('btnPageNext');
    const lastBtn = document.getElementById('btnPageLast');

    if (firstBtn) firstBtn.addEventListener('click', () => goToPage(1));
    if (prevBtn) prevBtn.addEventListener('click', () => goToPage(currentPage - 1));
    if (nextBtn) nextBtn.addEventListener('click', () => goToPage(currentPage + 1));
    if (lastBtn) lastBtn.addEventListener('click', () => goToPage(totalPages));

    els.paginationControls.querySelectorAll('.page-btn[data-page]').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = parseInt(btn.getAttribute('data-page'), 10);
        goToPage(p);
      });
    });
  }

  function goToPage(p) {
    state.currentPage = p;
    loadTableData();
  }

  /**
   * Handles direct CSV file download.
   */
  function handleCsvExport() {
    const params = new URLSearchParams({
      table: state.currentTable,
      time_filter: state.timeFilter,
      max_records: 10000
    });

    if (state.searchQuery) params.append('search', state.searchQuery);
    if (state.startDate) params.append('start_date', state.startDate);
    if (state.endDate) params.append('end_date', state.endDate);

    if (state.currentTable === 'events' && state.eventSeverity !== 'ALL') {
      params.append('event_severity', state.eventSeverity);
    }
    if (state.currentTable === 'telemetry' && state.motorState !== 'ALL') {
      params.append('motor_state', state.motorState);
    }

    const exportUrl = `/api/data/export/csv?${params.toString()}`;
    window.location.href = exportUrl;
  }

  function showLoadingState() {
    if (!els.tableBody) return;
    els.tableBody.innerHTML = `
      <tr>
        <td colspan="15" class="table-loading-state">
          <div class="loading-spinner"></div>
          <div>Loading table records from SQL database...</div>
        </td>
      </tr>
    `;
  }

  function showErrorState(msg) {
    if (!els.tableBody) return;
    els.tableBody.innerHTML = `
      <tr>
        <td colspan="15" class="table-empty-state" style="color: var(--accent-rose);">
          <div class="empty-state-icon">⚠️</div>
          <div class="empty-state-title">Query Error</div>
          <div class="empty-state-desc">${msg}</div>
        </td>
      </tr>
    `;
  }

  // Bootstrap when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
