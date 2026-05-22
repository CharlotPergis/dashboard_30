// Breaker Monitoring Dashboard JS
const SIMULATION_MODE = true;
let simulationInterval = null;

let timeLabels = [], tempData = [], currentData = [], hotspotData = [], overloadData = [];
const MAX_HISTORY = 20;
let historyData = [];
let combinedCtx;

function initCombinedChart() {
    const canvas = document.getElementById("combinedChart");
    if (!canvas) return;
    combinedCtx = canvas.getContext("2d");
    const resizeCanvas = () => {
        const container = canvas.parentElement;
        canvas.width = container.clientWidth;
        canvas.height = 160;
        drawCombinedChart();
    };
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);
    drawCombinedChart();
}

function drawCombinedChart() {
    if (!combinedCtx) return;
    const width = combinedCtx.canvas.width;
    const height = combinedCtx.canvas.height;
    combinedCtx.clearRect(0, 0, width, height);
    
    if (tempData.length < 2) {
        combinedCtx.font = "12px Inter";
        combinedCtx.fillStyle = "#94a3b8";
        combinedCtx.textAlign = "center";
        combinedCtx.fillText("Waiting for data...", width / 2, height / 2);
        return;
    }
    
    combinedCtx.beginPath();
    combinedCtx.strokeStyle = "#1e293b";
    combinedCtx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
        const y = (i / 4) * height;
        combinedCtx.beginPath();
        combinedCtx.moveTo(0, y);
        combinedCtx.lineTo(width, y);
        combinedCtx.stroke();
    }
    
    const normalize = (value, min, max) => (max === min) ? 0.5 : (value - min) / (max - min);
    drawLine(tempData, (val) => normalize(val, 0, 100), "#0ea5e9", 2, width, height);
    drawLine(currentData, (val) => normalize(val, 0, 50), "#facc15", 2, width, height);
    drawLine(hotspotData, (val) => normalize(val, 0, 1), "#ef4444", 2, width, height);
    drawLine(overloadData, (val) => normalize(val, 0, 1), "#a855f7", 2, width, height);
}

function drawLine(data, normalizeFn, color, lineWidth, width, height) {
    if (data.length < 2) return;
    const step = width / (data.length - 1);
    const ctx = combinedCtx;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    for (let i = 0; i < data.length; i++) {
        const x = i * step;
        const y = height - (Math.max(0, Math.min(1, normalizeFn(data[i]))) * height);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
}

function generateMockData() {
    let temp = 20 + Math.random() * 30;
    let current = 10 + Math.random() * 25;
    const randomEvent = Math.random();
    if (randomEvent < 0.05) { temp = 80 + Math.random() * 15; current = 42 + Math.random() * 10; }
    else if (randomEvent < 0.12) { temp = 68 + Math.random() * 12; current = 36 + Math.random() * 8; }
    else if (randomEvent < 0.20) { temp = 55 + Math.random() * 10; current = 30 + Math.random() * 6; }
    
    let state = "Normal", status = "✅ System normal";
    if (temp > 80 || current > 45) { state = "Overheating"; status = "🔥 CRITICAL!"; }
    else if (temp > 70 || current > 38) { state = "Overload"; status = "🔴 Overload detected"; }
    else if (temp > 60 || current > 32) { state = "Potential Overload"; status = "⚠️ Warning"; }
    
    const hotspotProb = Math.min(0.95, Math.max(0.05, (temp - 50) / 40));
    const overloadProb = Math.min(0.95, Math.max(0.05, (current - 25) / 25));
    
    return { temperature: Math.round(temp * 10) / 10, current: Math.round(current * 100) / 100, breakerState: state, status: status, ml: { hotspot_prob: Math.round(hotspotProb * 1000) / 1000, overload_prob: Math.round(overloadProb * 1000) / 1000 } };
}

function saveToLocalStorage() {
    if (timeLabels.length === 0) return;
    try {
        let fullHistory = JSON.parse(localStorage.getItem("breakerFullHistory") || "[]");
        fullHistory.unshift({ timestamp: new Date().toISOString(), timeDisplay: timeLabels[timeLabels.length - 1], temperature: tempData[tempData.length - 1], current: currentData[currentData.length - 1], breakerState: getBreakerStateFromData(tempData[tempData.length - 1], currentData[currentData.length - 1]), hotspot_probability: hotspotData[hotspotData.length - 1], overload_probability: overloadData[overloadData.length - 1] });
        if (fullHistory.length > 1000) fullHistory = fullHistory.slice(0, 1000);
        localStorage.setItem("breakerFullHistory", JSON.stringify(fullHistory));
    } catch (err) { console.error("Save error:", err); }
}

function getBreakerStateFromData(temp, current) {
    if (temp > 85 || current > 45) return "Overheating";
    if (temp > 75 || current > 40) return "Overload";
    if (temp > 60 || current > 35) return "Potential Overload";
    return "Normal";
}

function renderHistoryTable() {
    const logBody = document.getElementById("log-body");
    if (!logBody) return;
    if (historyData.length === 0) { 
        logBody.innerHTML = `<tr><td colspan="7" class="empty-state">Waiting for data...</td></tr>`; 
        return; 
    }
    
    // FIXED: Show ALL rows with NO limit
    logBody.innerHTML = historyData.map(entry => {
        let statusText = "", statusClass = "";
        if (entry.breakerState === "Normal") { statusText = "✅ Normal"; statusClass = "status-normal"; }
        else if (entry.breakerState === "Potential Overload") { statusText = "⚠️ Warning"; statusClass = "status-warning"; }
        else if (entry.breakerState === "Overload") { statusText = "🔴 Overload"; statusClass = "status-overload"; }
        else { statusText = "🔥 Critical"; statusClass = "status-danger"; }
        return `<tr>
                    <td>${entry.time}</td>
                    <td>${entry.temperature.toFixed(1)}°C</td>
                    <td>${entry.current.toFixed(1)}A</td>
                    <td>${(entry.hotspotProb * 100).toFixed(0)}%</td>
                    <td>${(entry.overloadProb * 100).toFixed(0)}%</td>
                    <td>${entry.breakerState}</td>
                    <td class="${statusClass}">${statusText}</td>
                </tr>`;
    }).join('');
    
    // Force all rows to be visible
    const rows = logBody.querySelectorAll('tr');
    rows.forEach(row => {
        row.style.display = 'table-row';
    });
}

function addToHistory(data) {
    // FIXED: Remove the limit - keep ALL rows (no pop)
    historyData.unshift({ 
        time: new Date().toLocaleTimeString(), 
        temperature: data.temperature, 
        current: data.current, 
        breakerState: data.breakerState, 
        hotspotProb: data.ml?.hotspot_prob || 0, 
        overloadProb: data.ml?.overload_prob || 0 
    });
    
    // REMOVED THE 8-ROW LIMIT - Now keeping ALL rows
    // Old code: if (historyData.length > 8) historyData.pop();
    // New: Keep all rows, no limit
    
    renderHistoryTable();
    saveToLocalStorage();
}

function updateDashboard(data) {
    if (!data) return;
    const timeLabel = new Date().toLocaleTimeString();
    timeLabels.push(timeLabel);
    tempData.push(data.temperature);
    currentData.push(data.current);
    
    let hotspotProb = data.ml?.hotspot_prob || Math.min(1, Math.max(0, (data.temperature - 60) / 40));
    let overloadProb = data.ml?.overload_prob || Math.min(1, Math.max(0, (data.current - 30) / 20));
    hotspotData.push(hotspotProb);
    overloadData.push(overloadProb);
    
    const percentHotspot = (hotspotProb * 100).toFixed(0);
    const percentOverload = (overloadProb * 100).toFixed(0);
    document.getElementById("hotspot-value").textContent = percentHotspot + "%";
    document.getElementById("hotspot-bar").style.width = percentHotspot + "%";
    document.getElementById("overload-value").textContent = percentOverload + "%";
    document.getElementById("overload-bar").style.width = percentOverload + "%";
    document.getElementById("temperature-value").textContent = data.temperature.toFixed(1);
    document.getElementById("current-value").textContent = data.current.toFixed(1);
    document.getElementById("breaker-state").textContent = data.breakerState;
    document.getElementById("breaker-state").className = `breaker-state-text ${data.breakerState}`;
    
    const suggestionMain = document.getElementById("suggestion-main");
    const actionText = document.getElementById("action-text");
    const riskBadge = document.getElementById("risk-badge-container");
    if (data.breakerState === "Overheating") {
        suggestionMain.innerHTML = "🔥 CRITICAL: IMMEDIATE SHUTDOWN REQUIRED!";
        actionText.textContent = "EMERGENCY: Isolate circuit NOW!";
        riskBadge.innerHTML = '<span class="risk-badge critical">⚠️ CRITICAL RISK</span>';
    } else if (data.breakerState === "Overload") {
        suggestionMain.innerHTML = "⚠️ OVERLOAD DETECTED - Reduce load immediately!";
        actionText.textContent = "Reduce connected load by 30-40%";
        riskBadge.innerHTML = '<span class="risk-badge high">🔴 HIGH RISK</span>';
    } else if (data.breakerState === "Potential Overload") {
        suggestionMain.innerHTML = "⚡ Potential overload developing - Take preventive action";
        actionText.textContent = "Reduce load by 15-20%";
        riskBadge.innerHTML = '<span class="risk-badge medium">🟡 MODERATE RISK</span>';
    } else {
        suggestionMain.innerHTML = "✅ System operating normally - No action required";
        actionText.textContent = "Standby - Monitoring";
        riskBadge.innerHTML = '<span class="risk-badge low">🟢 LOW RISK</span>';
    }
    
    if (timeLabels.length > MAX_HISTORY) { timeLabels.shift(); tempData.shift(); currentData.shift(); hotspotData.shift(); overloadData.shift(); }
    drawCombinedChart();
    addToHistory(data);
}

function startSimulation() {
    updateDashboard(generateMockData());
    simulationInterval = setInterval(() => updateDashboard(generateMockData()), 2000);
}

window.addEventListener("load", () => {
    initCombinedChart();
    startSimulation();
});