from flask import Flask, request, jsonify, render_template
import joblib
import os
import time
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime
from supabase import create_client
from types import SimpleNamespace
import threading

from feature_engine import (
    build_basic_features,
    temp_buffer_short,
    temp_buffer_long,
    current_buffer_short,
    current_buffer_long,
    reset_buffers
)

# =========================================================
# INIT
# =========================================================
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

# START EMPTY - NO DEFAULT VALUES
latest_data_store = {}

print("🔥 INITIALIZING SYSTEM...")

# =========================================================
# SUPABASE CONFIGURATION
# =========================================================
SUPABASE_URL = "https://qkniqwgcwvxkgjciccad.supabase.co"
SUPABASE_KEY = "sb_publishable_pzHW1LlymSCVL876qchBKw_pPY0xN-2"

# Initialize Supabase client
supabase = None
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✓ Supabase client initialized successfully")
except Exception as e:
    print(f"✗ Supabase initialization error: {e}")
    print("⚠ Running without Supabase - data will be saved locally only")

# =========================================================
# EMAIL CONFIG (SAFE)
# =========================================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'breaker.monitor.system@gmail.com'
app.config['MAIL_PASSWORD'] = 'kzng lhzr elww gyyu'
app.config['MAIL_DEFAULT_SENDER'] = 'breaker.monitor.system@gmail.com'

mail = None
email_enabled = False

try:
    mail = Mail(app)
    email_enabled = True
    print("✓ Email service initialized")
except Exception as e:
    print(f"✗ Email initialization error: {e}")
    print("⚠ Email alerts disabled — system continues normally")

# =========================================================
# THRESHOLDS (Version 2 thresholds preserved)
# =========================================================
WARMUP_SAMPLES = 10
WARNING_THRESHOLD = 0.65
CRITICAL_THRESHOLD = 0.70
WARNING_OVL = 0.75
CRITICAL_OVL = 0.90

# =========================================================
# ALERT TRACKING (Enhanced with cooldown)
# =========================================================
last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 300

def should_send_alert(alert_key):
    """Check if alert should be sent based on cooldown period"""
    now = time.time()
    if alert_key in last_alert_time:
        if now - last_alert_time[alert_key] < ALERT_COOLDOWN_SECONDS:
            return False
    last_alert_time[alert_key] = now
    return True

# =========================================================
# SUPABASE FUNCTIONS
# =========================================================
def send_to_supabase(temp, current, state, hot_prob, ovl_prob, composite_risk, action):
    """Send REAL sensor data to Supabase"""
    
    if supabase is None:
        print("⚠ Supabase not available, skipping insert")
        return False
    
    try:
        # Prepare data matching your table structure
        data = {
            "temperature_c": round(float(temp), 2),
            "current_a": round(float(current), 2),
            "breaker_state": state,
            "hotspot_probability": round(float(hot_prob), 4),
            "overload_probability": round(float(ovl_prob), 4),
            "composite_risk": round(float(composite_risk), 4),
            "recommended_action": action[:200] if action else "Monitor system"
        }
        
        # Insert to Supabase
        response = supabase.table("breaker_readings").insert(data).execute()
        
        # Check if successful
        if response and hasattr(response, 'data'):
            print(f"✓ Supabase | {temp:.1f}°C | {current:.1f}A | {state}")
            return True
        else:
            print(f"⚠ Supabase insert returned unexpected response")
            return False
            
    except Exception as e:
        print(f"✗ Supabase error: {e}")
        return False

# =========================================================
# FALLBACK LOGGER
# =========================================================
def log_fallback_alert(subject, body):
    try:
        with open("alert_fallback_log.txt", "a") as f:
            f.write("\n============================\n")
            f.write(f"TIME: {datetime.now()}\n")
            f.write(f"SUBJECT: {subject}\n")
            f.write(body + "\n")
        print("✓ Alert saved locally (fallback log)")
    except Exception as e:
        print("⚠ Fallback logging failed:", e)

# =========================================================
# ENHANCED EMAIL ALERT SYSTEM (Without time-to-trip)
# =========================================================
def send_breaker_alert(reading, risk, alert_type, message_action):
    """Enhanced email alert without time-to-trip information"""
    
    if not email_enabled or mail is None:
        print("⚠ Email skipped (disabled)")
        return False, "Email disabled"

    recipients = [
        'gwenlykapergis@gmail.com',
        'mariamonicaragunjanvillaflor@gmail.com',
        'mercymicadespabiladeras@gmail.com'
    ]

    # Version 1 style subject lines with Version 2 formatting
    if alert_type == "Critical":
        if risk['hotspot_prob'] >= 0.85:
            subject = "🔥 CRITICAL: Breaker Overheating Alert!"
        else:
            subject = "🔴 CRITICAL: Severe Overload Detected!"
        body = f"""IMMEDIATE ACTION REQUIRED

BREAKER {risk['hotspot_prob'] >= 0.85 and 'OVERHEATING' or 'OVERLOAD'} DETECTED!

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A
Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
Overload Probability: {risk['overload_prob']*100:.1f}%

--- PROACTIVE ACTION RECOMMENDED ---
{message_action}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    elif alert_type == "Warning":
        subject = "⚠️ PREVENTION: Potential Electrical Risk Detected!"
        body = f"""PREVENTIVE ACTION RECOMMENDED

POTENTIAL ISSUE DEVELOPING!

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A
Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
Overload Probability: {risk['overload_prob']*100:.1f}%

--- PROACTIVE ACTION RECOMMENDED ---
{message_action}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    else:
        subject = "Breaker System Alert"
        body = f"""
BREAKER MONITORING SYSTEM ALERT

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A

Hotspot Risk: {risk['hotspot_prob']*100:.1f}%
Overload Risk: {risk['overload_prob']*100:.1f}%

--- PROACTIVE ACTION RECOMMENDED ---
{message_action}
"""

    try:
        msg = Message(subject=subject,
                      sender=app.config['MAIL_USERNAME'],
                      recipients=recipients)

        msg.body = body
        mail.send(msg)

        print("✓ Email sent:", subject)
        return True, "Sent"

    except Exception as e:
        print("✗ Email failed:", e)
        log_fallback_alert(subject, body)
        return False, str(e)

# =========================================================
# STATE LOGIC (Version 2 preserved)
# =========================================================
def determine_state(hot_prob, ovl_prob):

    if len(temp_buffer_short) < WARMUP_SAMPLES or len(temp_buffer_long) < WARMUP_SAMPLES:
        return "WarmingUp", "System initializing..."

    if hot_prob >= CRITICAL_THRESHOLD:
        return "Critical", "Severe overheating detected"

    if ovl_prob >= CRITICAL_OVL:
        return "Critical", "Severe overload detected"

    if hot_prob >= WARNING_THRESHOLD:
        return "Warning", "Elevated temperature detected"

    if ovl_prob >= WARNING_OVL:
        return "Warning", "High load detected"

    return "Normal", "System stable"

# =========================================================
# ACTION ENGINE (Version 2 preserved)
# =========================================================
def get_action(state, hotspot, overload):

    if state == "Warning":

        if hotspot and overload:
            return "Reduce load immediately → hotspot + overload detected. Check wiring."

        if hotspot:
            return "Reduce load and inspect connections."

        if overload:
            return "Turn off heavy appliances."

        return "Monitor system."

    if state == "Critical":

        if hotspot and overload:
            return "SHUT DOWN SYSTEM immediately."

        if hotspot:
            return "SHUT DOWN → overheating detected."

        if overload:
            return "DISCONNECT LOAD immediately."

        return "Emergency inspection required."

    return "System normal."

# =========================================================
# API ENDPOINT - UPDATED TO USE PROBABILITIES FROM RPi
# =========================================================
@app.route("/api/update", methods=["POST"])
def update_data():

    # ===== BETTER VALIDATION - FIXED =====
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        # Safe extraction with defaults
        temp = float(data.get("temperature", 0))
        current = float(data.get("current", 0))
        
        # Validate ranges
        if temp < -20 or temp > 150:
            return jsonify({"error": f"Invalid temperature: {temp}"}), 400
        if current < 0 or current > 100:
            return jsonify({"error": f"Invalid current: {current}"}), 400
            
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid sensor data: {str(e)}"}), 400
    # =====================================
    
    # ===== ENHANCED DEBUG: SHOW EXACT RPI DATA =====
    print(f"\n{'='*60}")
    print(f"📡 RPi RAW DATA RECEIVED:")
    print(f"   Temperature: {temp}°C")
    print(f"   Current: {current}A")
    
    # ============================================
    # USE PROBABILITIES COMING DIRECTLY FROM RPi
    # WITH SAFE DEFAULT VALUES
    # ============================================
    X_hot = build_hotspot_X(temp, current)
    X_ovr = build_overload_X(temp, current)
    # Safe extraction with defaults to prevent KeyError
    hot_prob = float(data.get("hotspot_prob", 0))
    ovl_prob = float(data.get("overload_prob", 0))
    
    # Validate probability ranges
    hot_prob = max(0.0, min(1.0, hot_prob))
    ovl_prob = max(0.0, min(1.0, ovl_prob))
    
    # Store raw values for debugging
    hot_prob_raw = hot_prob
    ovl_prob_raw = ovl_prob
    
    print(f"🔥 RPi Hotspot Probability: {hot_prob:.4f} ({hot_prob*100:.1f}%)")
    print(f"⚡ RPi Overload Probability: {ovl_prob:.4f} ({ovl_prob*100:.1f}%)")
    print(f"{'='*60}")
    # ==============================================

    # CRITICAL FIX: Manually update buffers before feature extraction
    temp_buffer_short.append(temp)
    temp_buffer_long.append(temp)
    current_buffer_short.append(current)
    current_buffer_long.append(current)
    
    # DEBUG: Show buffer status
    print(f"📊 Buffer sizes - Temp short: {len(temp_buffer_short)}/{temp_buffer_short.maxlen}, Temp long: {len(temp_buffer_long)}/{temp_buffer_long.maxlen}")
    if len(temp_buffer_short) > 0:
        print(f"📊 Recent temps (last 5): {list(temp_buffer_short)[-5:]}")
        print(f"📊 Recent currents (last 5): {list(current_buffer_short)[-5:]}")
    
    # =========================
    # SIMPLE FORECAST
    # =========================
    future_temp = temp
    future_current = current
    # =========================
    
    # Composite risk calculation
    composite_risk = (hot_prob + ovl_prob) / 2

    # =========================
    # STATE (Version 2)
    # =========================
    state, status = determine_state(hot_prob, ovl_prob)
    print(f"🎯 System State: {state} - {status}")

    # Use correct thresholds for overload in action
    action = get_action(
        state,
        hot_prob >= WARNING_THRESHOLD,
        ovl_prob >= WARNING_OVL
    )
    print(f"💡 Recommended Action: {action}")

    # =========================
    # ALERTS (With enhanced cooldown keys)
    # =========================
    if state in ["Warning", "Critical"]:
        # Create unique alert key based on state and what triggered it
        if hot_prob >= WARNING_THRESHOLD and ovl_prob >= WARNING_OVL:
            alert_trigger = "both"
        elif hot_prob >= WARNING_THRESHOLD:
            alert_trigger = "hotspot"
        elif ovl_prob >= WARNING_OVL:
            alert_trigger = "overload"
        else:
            alert_trigger = "unknown"
        
        alert_key = f"{state}_{alert_trigger}"
        
        if should_send_alert(alert_key):
            print(f"📧 Sending {state} alert (trigger: {alert_trigger})...")
            
            # Use SimpleNamespace for cleaner object creation
            reading = SimpleNamespace(
                temperature_c=temp,
                current_a=current
            )
            
            send_breaker_alert(
                reading=reading,
                risk={
                    "hotspot_prob": hot_prob,
                    "overload_prob": ovl_prob
                },
                alert_type=state,
                message_action=action
            )
        else:
            print(f"⏰ {state} alert suppressed (cooldown active for {alert_key})")

    # =========================
    # SEND TO SUPABASE
    # =========================
    supabase_success = send_to_supabase(
        temp, current, state, 
        hot_prob, ovl_prob, 
        composite_risk, action
    )

    # =========================
    # STORE RESPONSE
    # =========================
    latest_data_store.update({
        "temperature": float(temp),
        "current": float(current),
        "state": state,
        "breakerState": state,
        "status": status,
        "action": action,
        "supabase_sync": supabase_success,
        "ml": {
            "hotspot_prob": float(hot_prob),
            "overload_prob": float(ovl_prob),
            "composite_risk": float(composite_risk),
            "hotspot_raw": float(hot_prob_raw),
            "overload_raw": float(ovl_prob_raw)
        },
        "forecast": {
            "future_temp": float(round(future_temp, 2)),
            "future_current": float(round(future_current, 2))
        },
        "buffer_size": int(len(temp_buffer_short)),
        "time": datetime.now().strftime("%H:%M:%S")
    })

    print(f"✅ FINAL DISPLAY VALUES: Hotspot={hot_prob*100:.1f}% | Overload={ovl_prob*100:.1f}%")
    print(f"✅ FINAL: [{state}] T={temp:.2f}°C I={current:.2f}A HP={hot_prob:.3f} OP={ovl_prob:.3f} Supabase={'✓' if supabase_success else '✗'}")
    print("="*70)

    return jsonify(latest_data_store)

# =========================================================
# ROUTES
# =========================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/full_history.html")
def full_history_page():
    return render_template("full_history.html")

@app.route("/history")
def history_page():
    return render_template("full_history.html")

@app.route("/logs")
def logs_page():
    return render_template("full_history.html")

@app.route("/api/latest-data")
def latest():
    if not latest_data_store or len(latest_data_store) == 0:
        return jsonify({
            "has_data": False,
            "message": "Waiting for Raspberry Pi to connect...",
            "temperature": None,
            "current": None,
            "state": "Waiting",
            "breakerState": "Waiting",
            "status": "No data received yet",
            "action": "Start the Raspberry Pi sensor script to begin monitoring",
            "ml": {"hotspot_prob": 0, "overload_prob": 0},
            "time": datetime.now().strftime("%H:%M:%S")
        })
    
    response_data = dict(latest_data_store)
    if 'breakerState' not in response_data:
        response_data['breakerState'] = response_data.get('state', 'Normal')
    response_data['has_data'] = True
    
    return jsonify(response_data)

@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "supabase_connected": supabase is not None,
        "email_enabled": email_enabled,
        "buffer_size": len(temp_buffer_short),
        "buffer_max": temp_buffer_short.maxlen if temp_buffer_short else 0,
        "latest_data_available": bool(latest_data_store and len(latest_data_store) > 0)
    })

@app.route("/api/reset-buffers", methods=["POST"])
def reset_buffers_endpoint():
    reset_buffers()
    return jsonify({"success": True, "message": "Buffers reset"})

@app.route("/api/test-supabase")
def test_supabase():
    if supabase is None:
        return jsonify({"success": False, "error": "Supabase not initialized"})
    
    try:
        response = supabase.table("breaker_readings").select("*").limit(5).execute()
        return jsonify({
            "success": True,
            "message": "Supabase connected",
            "record_count": len(response.data) if hasattr(response, 'data') else 0
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/history")
def get_full_history():
    if supabase is None:
        return jsonify({"success": False, "error": "Supabase not connected", "data": []}), 500
    
    try:
        response = supabase.table("breaker_readings").select("*").order("created_at", desc=True).execute()
        if response and hasattr(response, 'data'):
            return jsonify({
                "success": True,
                "data": response.data,
                "count": len(response.data)
            })
        return jsonify({"success": True, "data": [], "count": 0})
    except Exception as e:
        print(f"History error: {e}")
        return jsonify({"success": False, "error": str(e), "data": []}), 500

@app.route("/api/debug")
def debug():
    return jsonify({
        "latest_data_store": latest_data_store,
        "has_data": bool(latest_data_store and len(latest_data_store) > 0),
        "buffer_sizes": {
            "temp_short": len(temp_buffer_short),
            "temp_long": len(temp_buffer_long),
            "current_short": len(current_buffer_short),
            "current_long": len(current_buffer_long)
        }
    })

# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    print("⚡ SMART PANEL SYSTEM ONLINE")
    print(f"📡 Supabase: {'Connected' if supabase else 'Failed'}")
    print(f"📧 Email: {'Enabled' if email_enabled else 'Disabled'}")
    print(f"📊 History API: Enabled at /api/history")
    print(f"📄 History Page: Enabled at /full_history.html")
    print(f"⚡ Thresholds: Warning={WARNING_THRESHOLD}, Critical={CRITICAL_THRESHOLD}, Warning_OVL={WARNING_OVL}, Critical_OVL={CRITICAL_OVL}")
    print(f"📊 Buffer size: {temp_buffer_short.maxlen if temp_buffer_short else 10}")
    print("===================================")
    print("\n⏳ Waiting for Raspberry Pi to connect...")
    print("📡 Expecting RPi to send: temperature, current, hotspot_prob, overload_prob")
    print("🌐 Dashboard available at: http://localhost:5000")
    print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=False)
