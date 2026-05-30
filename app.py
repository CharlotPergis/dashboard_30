from flask import Flask, request, jsonify, render_template
import joblib
import os
import time
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime
from supabase import create_client  # NEW: From Version 1
import threading  # NEW: From Version 1

from feature_engine import (
    build_basic_features,
    temp_buffer_short,
    temp_buffer_long,
    current_buffer_short,
    current_buffer_long
)

# =========================================================
# INIT
# =========================================================
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

latest_data_store = {}

print("🔥 INITIALIZING SYSTEM...")

# =========================================================
# SUPABASE CONFIGURATION (NEW: From Version 1)
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
# LOAD MODELS
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

hotspot_model = joblib.load(os.path.join(BASE_DIR, "ml/hotspot_model.pkl"))
overload_model = joblib.load(os.path.join(BASE_DIR, "ml/overload_model.pkl"))

FEATURE_COLUMNS = hotspot_model.feature_names_in_.tolist()

# =========================================================
# THRESHOLDS
# =========================================================
WARMUP_SAMPLES = 10
WARNING_THRESHOLD = 0.70
CRITICAL_THRESHOLD = 0.85

# =========================================================
# ALERT TRACKING (Enhanced with Version 1 cooldown)
# =========================================================
last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 300

def should_send_alert(alert_type):
    now = time.time()
    if alert_type in last_alert_time:
        if now - last_alert_time[alert_type] < ALERT_COOLDOWN_SECONDS:
            return False
    last_alert_time[alert_type] = now
    return True

# =========================================================
# SUPABASE FUNCTIONS (NEW: From Version 1)
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
# TIME-TO-TRIP CALCULATION (NEW: From Version 1)
# =========================================================
def calculate_time_to_trip(temp, current, hot_prob, ovl_prob):
    """Estimate time until breaker trips based on conditions"""
    try:
        # Base estimation logic
        if hot_prob >= 0.85:
            # Critical hotspot - very urgent
            minutes = max(1, int(5 * (1 - (hot_prob - 0.85) / 0.15)))
            urgency = "CRITICAL - Immediate action required"
        elif hot_prob >= 0.70:
            # Warning level
            minutes = max(5, int(15 * (1 - (hot_prob - 0.70) / 0.15)))
            urgency = "URGENT - Take action soon"
        elif ovl_prob >= 0.85:
            # Critical overload
            minutes = max(2, int(8 * (1 - (ovl_prob - 0.85) / 0.15)))
            urgency = "CRITICAL - Reduce load immediately"
        elif ovl_prob >= 0.70:
            # Overload warning
            minutes = max(10, int(20 * (1 - (ovl_prob - 0.70) / 0.15)))
            urgency = "MODERATE - Plan load reduction"
        else:
            return None
        
        # Format the time
        if minutes < 60:
            time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            hours = minutes // 60
            mins = minutes % 60
            time_str = f"{hours} hour{'s' if hours != 1 else ''} {mins} minute{'s' if mins != 1 else ''}"
        
        return {
            "minutes": minutes,
            "formatted": time_str,
            "urgency": urgency
        }
    except:
        return None

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
# ENHANCED EMAIL ALERT SYSTEM (Merged Version 1 + Version 2)
# =========================================================
def send_breaker_alert(reading, risk, alert_type, message_action, time_to_trip=None):
    """Enhanced email alert with time-to-trip information"""
    
    if not email_enabled or mail is None:
        print("⚠ Email skipped (disabled)")
        return False, "Email disabled"

    recipients = [
        'gwenlykapergis@gmail.com',
        'mariamonicaragunjanvillaflor@gmail.com',
        'mercymicadespabiladeras@gmail.com'
    ]

    # Add time-to-trip info if available
    time_to_trip_text = ""
    if time_to_trip and alert_type in ["Critical", "Warning"]:
        time_to_trip_text = f"\n\nEstimated Time to Trip: {time_to_trip['formatted']}\nUrgency: {time_to_trip['urgency']}"

    # Version 1 style subject lines
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
{time_to_trip_text}

Action Required: {message_action}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    elif alert_type == "Warning":
        subject = "⚠️ PREVENTION: Potential Electrical Risk Detected!"
        body = f"""PREVENTIVE ACTION RECOMMENDED

POTENTIAL ISSUE DEVELOPING!

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A
Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
Overload Probability: {risk['overload_prob']*100:.1f}%
{time_to_trip_text}

Recommended Action: {message_action}

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

Action: {message_action}
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
# STATE LOGIC (PRESERVED from Version 2)
# =========================================================
def determine_state(hot_prob, ovl_prob):

    if len(temp_buffer_short) < 10 or len(temp_buffer_long) < 10:
        return "WarmingUp", "System initializing..."

    if hot_prob >= CRITICAL_THRESHOLD:
        return "Critical", "Severe overheating detected"

    if ovl_prob >= CRITICAL_THRESHOLD:
        return "Critical", "Severe overload detected"

    if hot_prob >= WARNING_THRESHOLD:
        return "Warning", "Elevated temperature detected"

    if ovl_prob >= WARNING_THRESHOLD:
        return "Warning", "High load detected"

    return "Normal", "System stable"

# =========================================================
# ACTION ENGINE (PRESERVED from Version 2)
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
# API ENDPOINT (ENHANCED with Supabase + Version 2 features)
# =========================================================
@app.route("/api/update", methods=["POST"])
def update_data():

    data = request.json
    temp = float(data["temperature"])
    current = float(data["current"])

    X = build_basic_features(temp, current)
    X = X.reindex(columns=FEATURE_COLUMNS, fill_value=0)

    hot_prob = float(hotspot_model.predict_proba(X)[0][1])
    ovl_prob = float(overload_model.predict_proba(X)[0][1])

    composite_risk = (hot_prob + ovl_prob) / 2  # NEW: For Supabase

    state, status = determine_state(hot_prob, ovl_prob)

    # =====================================================
    # FORECAST (PRESERVED from Version 2)
    # =====================================================
    feat = X

    future_temp = temp
    future_current = current

    try:
        future_temp = temp + feat["temp_slope_short"].values[0] * 10
        future_current = current + feat["current_slope_short"].values[0] * 10
    except:
        pass

    action = get_action(
        state,
        hot_prob >= WARNING_THRESHOLD,
        ovl_prob >= WARNING_THRESHOLD
    )

    # =====================================================
    # TIME-TO-TRIP CALCULATION (NEW: From Version 1)
    # =====================================================
    time_to_trip = None
    if state in ["Warning", "Critical"]:
        time_to_trip = calculate_time_to_trip(temp, current, hot_prob, ovl_prob)

    # =====================================================
    # ALERTS (ENHANCED with time-to-trip from Version 1)
    # =====================================================
    if state in ["Warning", "Critical"]:
        if should_send_alert(state):
            send_breaker_alert(
                reading=type("obj", (), {
                    "temperature_c": temp,
                    "current_a": current
                }),
                risk={
                    "hotspot_prob": hot_prob,
                    "overload_prob": ovl_prob
                },
                alert_type=state,
                message_action=action,
                time_to_trip=time_to_trip  # NEW: Pass time-to-trip info
            )

    # =====================================================
    # SEND TO SUPABASE (NEW: From Version 1)
    # =====================================================
    supabase_success = send_to_supabase(
        temp, current, state, 
        hot_prob, ovl_prob, 
        composite_risk, action
    )

    # =====================================================
    # UPDATE LOCAL STORAGE (PRESERVED from Version 2 + Supabase status)
    # =====================================================
    latest_data_store.update({
        "temperature": float(temp),
        "current": float(current),
        "state": state,
        "status": status,
        "action": action,
        "supabase_sync": supabase_success,  # NEW: From Version 1
        "ml": {
            "hotspot_prob": float(hot_prob),
            "overload_prob": float(ovl_prob),
            "composite_risk": float(composite_risk)  # NEW: From Version 1
        },
        "forecast": {
            "future_temp": float(round(future_temp, 2)),
            "future_current": float(round(future_current, 2))
        },
        "time_to_trip": time_to_trip,  # NEW: From Version 1
        "buffer_size": int(len(temp_buffer_short)),
        "time": datetime.now().strftime("%H:%M:%S")
    })

    print(f"[{state}] T={temp:.2f} I={current:.2f} HP={hot_prob:.2f} OP={ovl_prob:.2f} Supabase={'✓' if supabase_success else '✗'}")

    return jsonify(latest_data_store)

# =========================================================
# ROUTES (PRESERVED from Version 2 + New Supabase routes)
# =========================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/latest-data")
def latest():
    return jsonify(latest_data_store)

@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "models_loaded": True,
        "supabase_connected": supabase is not None,
        "email_enabled": email_enabled,
        "buffer_size": len(temp_buffer_short)
    })

# =========================================================
# NEW: SUPABASE TEST ENDPOINT (From Version 1)
# =========================================================
@app.route("/api/test-supabase")
def test_supabase():
    """Test Supabase connection"""
    if supabase is None:
        return jsonify({"success": False, "error": "Supabase not initialized"})
    
    try:
        # Try to fetch the last 5 records
        response = supabase.table("breaker_readings").select("*").limit(5).execute()
        return jsonify({
            "success": True,
            "message": "Supabase connected",
            "record_count": len(response.data) if hasattr(response, 'data') else 0
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    print("⚡ SMART PANEL SYSTEM ONLINE")
    print(f"📡 Supabase: {'Connected' if supabase else 'Failed'}")
    print(f"📧 Email: {'Enabled' if email_enabled else 'Disabled'}")
    print(f"🔮 Forecast: Enabled (Version 2 feature)")
    print(f"⏱️  Time-to-Trip: Enabled (Version 1 feature)")
    print("===================================")
    app.run(host="0.0.0.0", port=5000, debug=False)