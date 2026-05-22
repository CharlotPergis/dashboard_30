(function () {
  // DOM Elements
  const fullLogBody = document.getElementById("full-log-body");
  const totalCountSpan = document.getElementById("total-count");
  const filteredCountSpan = document.getElementById("filtered-count");

  const startDateInput = document.getElementById("startDate");
  const endDateInput = document.getElementById("endDate");
  const startTimeInput = document.getElementById("startTime");
  const endTimeInput = document.getElementById("endTime");

  const statusFilter = document.getElementById("statusFilter");
  const searchInput = document.getElementById("searchInput");
  const dateRangePreset = document.getElementById("dateRangePreset");

  const applyFiltersBtn = document.getElementById("applyFiltersBtn");
  const clearFiltersBtn = document.getElementById("clearFiltersBtn");
  const downloadCsvBtn = document.getElementById("downloadCsvBtn");

  const quick1h = document.getElementById("quick1h");
  const quick24h = document.getElementById("quick24h");
  const quick7d = document.getElementById("quick7d");

  let allLogs = [];
  let currentFilteredLogs = [];

  // -----------------------------
  // SAFE PARSER
  // -----------------------------
  function parseTimestamp(ts) {
    if (!ts) return null;
    const d = new Date(ts);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatDate(d) {
    if (!d) return "Invalid Date";
    return d.toLocaleString();
  }

  function toDate(date, time) {
    if (!date) return null;
    return new Date(`${date}T${time || "00:00"}:00`);
  }

  // -----------------------------
  // FILTER ENGINE (SAFE)
  // -----------------------------
  function applyFilters() {
    let filtered = [...allLogs];

    const start = toDate(startDateInput?.value, startTimeInput?.value);
    const end = toDate(endDateInput?.value, endTimeInput?.value);

    if (start) {
      filtered = filtered.filter(l => {
        const t = parseTimestamp(l.timestamp);
        return t && t >= start;
      });
    }

    if (end) {
      filtered = filtered.filter(l => {
        const t = parseTimestamp(l.timestamp);
        return t && t <= end;
      });
    }

    const status = statusFilter?.value;
    if (status && status !== "all") {
      filtered = filtered.filter(l => {
        const s = l.breakerState || "";
        return (
          (status === "normal" && s === "Normal") ||
          (status === "warning" && s === "Potential Overload") ||
          (status === "overload" && s === "Overload") ||
          (status === "danger" && s === "Overheating")
        );
      });
    }

    const search = (searchInput?.value || "").toLowerCase().trim();
    if (search) {
      filtered = filtered.filter(l => {
        return (
          String(l.breakerState || "").toLowerCase().includes(search) ||
          String(l.systemStatus || "").toLowerCase().includes(search) ||
          String(l.temperature || "").includes(search) ||
          String(l.current || "").includes(search)
        );
      });
    }

    currentFilteredLogs = filtered;
    render();
    updateStats();
  }

  // -----------------------------
  // LOAD DATA (FIXED)
  // -----------------------------
  function loadData() {
    try {
      const stored =
        localStorage.getItem("breakerFullHistory") ||
        localStorage.getItem("breakerLogs") ||
        localStorage.getItem("historyLogs");

      const raw = stored ? JSON.parse(stored) : [];

      allLogs = raw
        .map(l => ({
          timestamp: l.timestamp,
          temperature: Number(l.temperature || 0),
          current: Number(l.current || 0),
          breakerState: l.breakerState || "Unknown",
          systemStatus: l.systemStatus || "—"
        }))
        .filter(l => l.timestamp);

      allLogs.sort((a, b) =>
        new Date(b.timestamp) - new Date(a.timestamp)
      );

      currentFilteredLogs = [...allLogs];

      render();
      updateStats();
    } catch (e) {
      console.error("Load error:", e);
      allLogs = [];
      currentFilteredLogs = [];
      render();
    }
  }

  // -----------------------------
  // RENDER (SAFE)
  // -----------------------------
  function render() {
    if (!fullLogBody) return;

    fullLogBody.innerHTML = "";

    if (!currentFilteredLogs.length) {
      fullLogBody.innerHTML =
        `<tr><td colspan="5" style="text-align:center;padding:40px;">
        No logs found
        </td></tr>`;
      return;
    }

    const frag = document.createDocumentFragment();

    currentFilteredLogs.forEach(l => {
      const d = parseTimestamp(l.timestamp);

      const row = document.createElement("tr");

      row.innerHTML = `
        <td>${formatDate(d)}</td>
        <td>${Number(l.temperature).toFixed(1)}°C</td>
        <td>${Number(l.current).toFixed(1)}A</td>
        <td>${l.breakerState}</td>
        <td>${l.systemStatus}</td>
      `;

      frag.appendChild(row);
    });

    fullLogBody.appendChild(frag);
  }

  // -----------------------------
  // STATS
  // -----------------------------
  function updateStats() {
    if (totalCountSpan)
      totalCountSpan.textContent = allLogs.length;

    if (filteredCountSpan)
      filteredCountSpan.textContent = currentFilteredLogs.length;
  }

  // -----------------------------
  // CLEAR FILTERS
  // -----------------------------
  function clearFilters() {
    if (startDateInput) startDateInput.value = "";
    if (endDateInput) endDateInput.value = "";
    if (startTimeInput) startTimeInput.value = "";
    if (endTimeInput) endTimeInput.value = "";
    if (statusFilter) statusFilter.value = "all";
    if (searchInput) searchInput.value = "";

    currentFilteredLogs = [...allLogs];
    render();
    updateStats();
  }

  // -----------------------------
  // CSV DOWNLOAD
  // -----------------------------
  function downloadCSV() {
    if (!currentFilteredLogs.length) return;

    const rows = [
      ["Date", "Temp", "Current", "State", "Status"]
    ];

    currentFilteredLogs.forEach(l => {
      rows.push([
        l.timestamp,
        l.temperature,
        l.current,
        l.breakerState,
        l.systemStatus
      ]);
    });

    const csv = rows.map(r => r.join(",")).join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "history.csv";
    a.click();

    URL.revokeObjectURL(url);
  }

  // -----------------------------
  // EVENTS
  // -----------------------------
  applyFiltersBtn?.addEventListener("click", applyFilters);
  clearFiltersBtn?.addEventListener("click", clearFilters);
  downloadCsvBtn?.addEventListener("click", downloadCSV);

  searchInput?.addEventListener("input", applyFilters);
  statusFilter?.addEventListener("change", applyFilters);

  startDateInput?.addEventListener("change", applyFilters);
  endDateInput?.addEventListener("change", applyFilters);
  startTimeInput?.addEventListener("change", applyFilters);
  endTimeInput?.addEventListener("change", applyFilters);

  quick1h?.addEventListener("click", () => {
    const d = new Date(Date.now() - 3600000);
    startDateInput.value = d.toISOString().split("T")[0];
    applyFilters();
  });

  quick24h?.addEventListener("click", () => {
    const d = new Date(Date.now() - 86400000);
    startDateInput.value = d.toISOString().split("T")[0];
    applyFilters();
  });

  quick7d?.addEventListener("click", () => {
    const d = new Date(Date.now() - 7 * 86400000);
    startDateInput.value = d.toISOString().split("T")[0];
    applyFilters();
  });

  // -----------------------------
  // INIT
  // -----------------------------
  document.addEventListener("DOMContentLoaded", () => {
    loadData();
  });

})();