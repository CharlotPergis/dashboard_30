// Breaker Monitoring Dashboard JS - REAL RPi DATA ONLY (NO SIMULATION)

let timeLabels = [], tempData = [], currentData = [], hotspotData = [], overloadData = [];
const MAX_HISTORY = 20;
let historyData = [];
let combinedCtx;
let fetchInterval = null;

// ✅ ADD THIS FUNCTION - Clears old UTC timestamps from localStorage
function clearOldUTCHistory() {
    try {
        let fullHistory = JSON.parse(localStorage.getItem("breakerFullHistory") || "[]");
        let needsClear = false;
        
        // Check if any stored data has old UTC time (starts with 12:)
        for (let i = 0; i < fullHistory.length; i++) {
            if (fullHistory[i].timeDisplay && fullHistory[i].timeDisplay.startsWith("12:")) {
                needsClear = true;
                break;
            }
            if (fullHistory[i].time && fullHistory[i].time.startsWith("12:")) {
                needsClear = true;
                break;
            }
        }
        
        // Also check current historyData
        if (historyData.length > 0) {
            for (let i = 0; i < historyData.length; i++) {
                if (historyData[i].time && historyData[i].time.startsWith("12:")) {
                    needsClear = true;
                    break;
                }
            }
        }
        
        if (needsClear) {
            console.log("Clearing old UTC timestamps from localStorage...");
            localStorage.removeItem("breakerFullHistory");
            historyData = [];  // Clear current history
            renderHistoryTable();  // Refresh the table
        }
    } catch (err) {
        console.error("Error clearing old history:", err);
    }
}

// Helper function to get Philippines time (UTC+8)
function getPhilippinesTime() {
    return new Date().toLocaleString('en-PH', {
        timeZone: 'Asia/Manila',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

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
        combinedCtx.fillText("Waiting for RPi data...", width / 2, height / 2);
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

function saveToLocalStorage() {
    if (timeLabels.length === 0) return;
    try {
        let fullHistory = JSON.parse(localStorage.getItem("breakerFullHistory") || "[]");
        fullHistory.unshift({ 
            timestamp: new Date().toISOString(), 
            timeDisplay: timeLabels[timeLabels.length - 1], 
            temperature: tempData[tempData.length - 1], 
            current: currentData[currentData.length - 1], 
            breakerState: getBreakerStateFromData(tempData[tempData.length - 1], currentData[currentData.length - 1]), 
            hotspot_probability: hotspotData[hotspotData.length - 1], 
            overload_probability: overloadData[overloadData.length - 1] 
        });
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
        logBody.innerHTML = `<tr><td colspan="7" class="empty-state">Waiting for RPi data......</td><td colspan="7" class="empty-state">waiting for RPi data...</td></td>`; 
        return; 
    }
    
    logBody.innerHTML = historyData.map(entry => {
        let statusText = "", statusClass = "";
        if (entry.breakerState === "Normal") { statusText = "✅ Normal"; statusClass = "status-normal"; }
        else if (entry.breakerState === "Potential Overload") { statusText = "⚠️ Warning"; statusClass = "status-warning"; }
        else if (entry.breakerState === "Overload") { statusText = "🔴 Overload"; statusClass = "status-overload"; }
        else { statusText = "🔥 Critical"; statusClass = "status-danger"; }
        return `<tr>
                    <td>${entry.time}</td>
                    <td>${entry.temperature.toFixed(1)}°C</td>^<td>${entry.current.toFixed(1)}A</td>
                    <td>${(entry.hotspotProb * 100).toFixed(0)}%</td>
                    <td>${(entry.overloadProb * 100).toFixed(0)}%</td>
                    <td>${entry.breakerState}</td>
                    <td class="${statusClass}">${statusText}</td>
                </tr>`;
    }).join('');
}

function addToHistory(data) {
    // ✅ FIXED: Use Philippines time instead of UTC
    const phTime = new Date().toLocaleString('en-PH', {
        timeZone: 'Asia/Manila',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
    
    historyData.unshift({ 
        time: phTime,  // ← NOW USING PHILIPPINES TIME
        temperature: data.temperature, 
        current: data.current, 
        breakerState: data.breakerState, 
        hotspotProb: data.ml?.hotspot_prob || 0, 
        overloadProb: data.ml?.overload_prob || 0 
    });
    
    // Limit history to 50 items
    if (historyData.length > 50) historyData.pop();
    
    renderHistoryTable();
    saveToLocalStorage();
}

// Fetch REAL data from Flask server
async function fetchRealData() {
    try {
        const response = await fetch('/api/latest-data?_=' + Date.now());
        const data = await response.json();
        
        if (data && data.temperature !== undefined && data.temperature !== null) {
            updateDashboard(data);
        }
    } catch (error) {
        console.error('Error fetching RPi data:', error);
    }
}

function updateDashboard(data) {
    if (!data) return;
    
    // ✅ FIXED: Use Philippines time for the chart labels
    const timeLabel = new Date().toLocaleString('en-PH', {
        timeZone: 'Asia/Manila',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
    
    timeLabels.push(timeLabel);
    tempData.push(data.temperature);
    currentData.push(data.current);
    
    let hotspotProb = data.ml?.hotspot_prob || 0;
    let overloadProb = data.ml?.overload_prob || 0;
    hotspotData.push(hotspotProb);
    overloadData.push(overloadProb);
    
    const percentHotspot = (hotspotProb * 100).toFixed(1);
    const percentOverload = (overloadProb * 100).toFixed(1);
    document.getElementById("hotspot-value").textContent = percentHotspot + "%";
    document.getElementById("hotspot-bar").style.width = percentHotspot + "%";
    document.getElementById("overload-value").textContent = percentOverload + "%";
    document.getElementById("overload-bar").style.width = percentOverload + "%";
    document.getElementById("temperature-value").textContent = data.temperature.toFixed(1);
    document.getElementById("current-value").textContent = data.current.toFixed(2);
    document.getElementById("breaker-state").textContent = data.breakerState || data.state;
    document.getElementById("breaker-state").className = `breaker-state-text ${data.breakerState || data.state}`;
    
    // Update recommendation text (fixed for your HTML)
    const recommendationText = document.getElementById("recommendation-text");
    if (recommendationText) {
        if (data.breakerState === "Overheating" || data.state === "Critical") {
            recommendationText.innerHTML = "🔥 CRITICAL: IMMEDIATE SHUTDOWN REQUIRED! - EMERGENCY: Isolate circuit NOW!";
        } else if (data.breakerState === "Overload" || data.state === "Critical") {
            recommendationText.innerHTML = "⚠️ OVERLOAD DETECTED - Reduce load immediately! Reduce connected load by 30-40%";
        } else if (data.breakerState === "Potential Overload" || data.state === "Warning") {
            recommendationText.innerHTML = "⚡ Potential overload developing - Take preventive action. Reduce load by 15-20%";
        } else {
            recommendationText.innerHTML = "✅ System operating normally - No action required. Standby - Monitoring";
        }
    }
    
    if (timeLabels.length > MAX_HISTORY) { 
        timeLabels.shift(); 
        tempData.shift(); 
        currentData.shift(); 
        hotspotData.shift(); 
        overloadData.shift(); 
    }
    drawCombinedChart();
    addToHistory(data);
}

// Start fetching REAL data (NO simulation)
window.addEventListener("load", () => {
    clearOldUTCHistory();  // ✅ ADD THIS LINE - Clears old UTC data
    initCombinedChart();
    fetchRealData();  // Initial fetch
    fetchInterval = setInterval(fetchRealData, 2000);  // Fetch every 2 seconds
});