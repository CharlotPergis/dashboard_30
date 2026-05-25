from flask import Flask, request, jsonify, render_template
import joblib
import os
import time
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime
from supabase import create_client
import threading

# =========================================================
# FEATURE ENGINE MODULE (simplified)
# =========================================================
temp_buffer = []
current_buffer = []

def build_basic_features(temp, current):
    """Build basic features for ML prediction"""
    import pandas as pd
    
    # Add to buffers
    temp_buffer.append(temp)
    current_buffer.append(current)
    
    # Keep last 10 samples
    if len(temp_buffer) > 10:
        temp_buffer.pop(0)
    if len(current_buffer) > 10:
        current_buffer.pop(0)
    
    # Calculate features
    temp_mean = sum(temp_buffer) / len(temp_buffer) if temp_buffer else temp
    current_mean = sum(current_buffer) / len(current_buffer) if current_buffer else current
    
    temp_trend = temp_buffer[-1] - temp_buffer[0] if len(temp_buffer) >= 2 else 0
    current_trend = current_buffer[-1] - current_buffer[0] if len(current_buffer) >= 2 else 0
    
    # Create DataFrame with features
    df = pd.DataFrame({
        'temperature': [temp],
        'current': [current],
        'temp_mean_10': [temp_mean],
        'current_mean_10': [current_mean],
        'temp_trend': [temp_trend],
        'current_trend': [current_trend],
        'temp_current_ratio': [temp / current if current > 0 else 0],
        'power': [temp * current]
    })
    
    return df

# =========================================================
# FLASK APP INIT
# =========================================================
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

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
# EMAIL CONFIG
# =========================================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'breaker.monitor.system@gmail.com'
app.config['MAIL_PASSWORD'] = 'kzng lhzr elww gyyu'
app.config['MAIL_DEFAULT_SENDER'] = 'breaker.monitor.system@gmail.com'
app.config['MAIL_DEBUG'] = True

try:
    mail = Mail(app)
    print("✓ Email service initialized")
except Exception as e:
    print(f"✗ Email initialization error: {e}")
    mail = None

# =========================================================
# LOAD MODELS
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Create dummy models if they don't exist
if not os.path.exists(os.path.join(BASE_DIR, "ml/hotspot_model.pkl")):
    print("⚠️ Models not found, creating dummy models...")
    os.makedirs(os.path.join(BASE_DIR, "ml"), exist_ok=True)
    
    from sklearn.ensemble import RandomForestClassifier
    import pandas as pd
    import numpy as np
    
    # Create dummy training data
    X_train = pd.DataFrame({
        'temperature': np.random.rand(100),
        'current': np.random.rand(100),
        'temp_mean_10': np.random.rand(100),
        'current_mean_10': np.random.rand(100),
        'temp_trend': np.random.rand(100),
        'current_trend': np.random.rand(100),
        'temp_current_ratio': np.random.rand(100),
        'power': np.random.rand(100)
    })
    y_train = np.random.randint(0, 2, 100)
    
    dummy_model = RandomForestClassifier()
    dummy_model.fit(X_train, y_train)
    dummy_model.feature_names_in_ = X_train.columns
    
    joblib.dump(dummy_model, os.path.join(BASE_DIR, "ml/hotspot_model.pkl"))
    joblib.dump(dummy_model, os.path.join(BASE_DIR, "ml/overload_model.pkl"))
    print("✓ Dummy models created")

hotspot_model = joblib.load(
    os.path.join(BASE_DIR, "ml/hotspot_model.pkl")
)

overload_model = joblib.load(
    os.path.join(BASE_DIR, "ml/overload_model.pkl")
)

print("✓ Models loaded successfully")

# =========================================================
# FEATURE LOCK
# =========================================================
FEATURE_COLUMNS = hotspot_model.feature_names_in_.tolist()

print("✓ Feature lock loaded")
print("Total features:", len(FEATURE_COLUMNS))

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
# EMAIL ALERT FUNCTION (FIXED - COPIED FROM VER.1)
# =========================================================
def send_breaker_alert(reading, risk, alert_type, time_to_trip=None):
    if mail is None:
        return False, "Email service not configured"

    recipients = ['gwenlykapergis@gmail.com',
                  'mariamonicaragunjanvillaflor@gmail.com',
                  'mercymicadespabiladeras@gmail.com']

    time_to_trip_text = ""
    if time_to_trip and alert_type in ["overheating", "prevention"]:
        time_to_trip_text = f"\nEstimated Time to Trip: {time_to_trip['formatted']}\nUrgency: {time_to_trip['urgency']}"

    if alert_type == "overheating":
        subject = "🔥 CRITICAL: Breaker Overheating Alert!"
        body = f"""IMMEDIATE ACTION REQUIRED

BREAKER OVERHEATING DETECTED!

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.1f}A
Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
Overload Probability: {risk['overload_prob']*100:.1f}%
{time_to_trip_text}

Action: Isolate circuit immediately!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    elif alert_type == "prevention":
        subject = "⚠️ PREVENTION: Potential Overload Detected!"
        body = f"""PREVENTIVE ACTION RECOMMENDED

POTENTIAL OVERLOAD DEVELOPING!

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.1f}A
Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
Overload Probability: {risk['overload_prob']*100:.1f}%
{time_to_trip_text}

Action: Reduce load by 15-20%

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    else:
        return False, "Unknown alert type"

    try:
        msg = Message(
            subject=subject,
            sender=app.config['MAIL_USERNAME'],
            recipients=recipients
        )
        msg.body = body
        mail.send(msg)
        print(f"✓ Email sent: {subject}")
        return True, "Alert sent"
    except Exception as e:
        print(f"✗ Email error: {e}")
        return False, str(e)

# =========================================================
# ALERT TRACKING
# =========================================================
last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 300

def should_send_alert(alert_type):
    current_time = time.time()
    if alert_type in last_alert_time:
        if current_time - last_alert_time[alert_type] < ALERT_COOLDOWN_SECONDS:
            return False
    last_alert_time[alert_type] = current_time
    return True

# =========================================================
# ACTION ENGINE
# =========================================================
def get_action(state, hotspot, overload):
    """Generate human-readable action based on state"""
    if state == "Warning":
        if hotspot and overload:
            return "Reduce load immediately → hotspot + overload detected. Check for loose terminals and wiring."
        if hotspot:
            return "Reduce load and inspect connections → possible loose terminals or oxidation."
        if overload:
            return "Turn off heavy appliances → circuit nearing capacity limit."
        return "Monitor system - elevated readings detected."

    if state == "Critical":
        if hotspot and overload:
            return "SHUT DOWN SYSTEM → severe heat + overload risk. Inspect breaker immediately."
        if hotspot:
            return "SHUT DOWN → overheating likely from poor contact or damaged insulation."
        if overload:
            return "DISCONNECT LOAD → overload beyond safe limit."
        return "Emergency inspection required immediately."

    if state == "WarmingUp":
        return "System initializing - collecting baseline data."

    return "System operating normally."

# =========================================================
# SYSTEM CONFIG
# =========================================================
WARMUP_SAMPLES = 10
WARNING_THRESHOLD = 0.60
CRITICAL_THRESHOLD = 0.85

# =========================================================
# API ENDPOINT (Sends REAL data to Supabase)
# =========================================================
@app.route("/api/update", methods=["POST"])
def update_data():

    global latest_data_store

    try:
        # RECEIVE DATA from RPi
        data = request.json
        temp = float(data["temperature"])
        current = float(data["current"])

        # FEATURE ENGINE
        X = build_basic_features(temp, current)
        X = X.reindex(columns=FEATURE_COLUMNS, fill_value=0)

        # ML PREDICTION
        hot_prob = hotspot_model.predict_proba(X)[0][1]
        ovl_prob = overload_model.predict_proba(X)[0][1]

        composite_risk = (hot_prob + ovl_prob) / 2

        # =================================================
        # ENGINEERING STATE LOGIC
        # =================================================

        # WARMUP
        if len(temp_buffer) < WARMUP_SAMPLES:
            state = "WarmingUp"
            status = "COLLECTING DATA"

        # CRITICAL
        elif hot_prob >= CRITICAL_THRESHOLD:
            state = "Critical"
            status = "HOTSPOT CRITICAL"
            
            if should_send_alert("critical_hotspot"):
                send_breaker_alert(
                    reading=type("obj", (object,), {
                        "temperature_c": temp,
                        "current_a": current
                    }),
                    risk={
                        "hotspot_prob": hot_prob,
                        "overload_prob": ovl_prob
                    },
                    alert_type="overheating"
                )

        elif ovl_prob >= CRITICAL_THRESHOLD:
            state = "Critical"
            status = "OVERLOAD CRITICAL"
            
            if should_send_alert("critical_overload"):
                send_breaker_alert(
                    reading=type("obj", (object,), {
                        "temperature_c": temp,
                        "current_a": current
                    }),
                    risk={
                        "hotspot_prob": hot_prob,
                        "overload_prob": ovl_prob
                    },
                    alert_type="overheating"
                )

        # WARNING
        elif hot_prob >= WARNING_THRESHOLD:
            state = "Warning"
            status = "HOTSPOT WARNING"
            
            if should_send_alert("warning_hotspot"):
                send_breaker_alert(
                    reading=type("obj", (object,), {
                        "temperature_c": temp,
                        "current_a": current
                    }),
                    risk={
                        "hotspot_prob": hot_prob,
                        "overload_prob": ovl_prob
                    },
                    alert_type="prevention"
                )

        elif ovl_prob >= WARNING_THRESHOLD:
            state = "Warning"
            status = "OVERLOAD WARNING"
            
            if should_send_alert("warning_overload"):
                send_breaker_alert(
                    reading=type("obj", (object,), {
                        "temperature_c": temp,
                        "current_a": current
                    }),
                    risk={
                        "hotspot_prob": hot_prob,
                        "overload_prob": ovl_prob
                    },
                    alert_type="prevention"
                )

        # NORMAL
        else:
            state = "Normal"
            status = "SYSTEM NORMAL"

        # Generate action recommendation
        action = get_action(
            state,
            hot_prob >= WARNING_THRESHOLD,
            ovl_prob >= WARNING_THRESHOLD
        )

        # SEND TO SUPABASE (REAL DATA)
        supabase_success = send_to_supabase(
            temp, current, state, 
            hot_prob, ovl_prob, 
            composite_risk, action
        )

        # STORE DATA locally
        latest_data_store = {
            "temperature": round(temp, 2),
            "current": round(current, 2),
            "breakerState": state,
            "status": status,
            "action": action,
            "supabase_sync": supabase_success,
            "ml": {
                "hotspot_prob": round(float(hot_prob), 4),
                "overload_prob": round(float(ovl_prob), 4),
                "composite_risk": round(float(composite_risk), 4)
            },
            "buffer_size": len(temp_buffer),
            "time": datetime.now().strftime("%H:%M:%S")
        }

        print(
            f"[{state}] T={temp:.2f}C | I={current:.2f}A | "
            f"HP={hot_prob:.3f} | OP={ovl_prob:.3f} | Supabase={'✓' if supabase_success else '✗'}"
        )

        return jsonify({
            "success": True,
            "state": state,
            "status": status,
            "action": action,
            "supabase_sync": supabase_success,
            "ml": {
                "hotspot_prob": round(float(hot_prob), 4),
                "overload_prob": round(float(ovl_prob), 4),
                "composite_risk": round(float(composite_risk), 4)
            }
        })

    except Exception as e:
        print("API ERROR:", e)
        return jsonify({"success": False, "error": str(e)})

# =========================================================
# WEB ROUTES
# =========================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/latest-data")
def latest():
    return jsonify(latest_data_store)

@app.route("/full_history.html")
def full_history():
    return render_template("full_history.html")

# =========================================================
# SUPABASE TEST ENDPOINT
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
# HEALTH CHECK
# =========================================================
@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "models_loaded": True,
        "supabase_connected": supabase is not None,
        "email_enabled": mail is not None,
        "buffer_size": len(temp_buffer)
    })

# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":

    print("===================================")
    print("⚡ SMART PANEL MONITORING SYSTEM")
    print("🔥 Predictive ML Protection Enabled")
    print("===================================")
    print(f"📡 Supabase: {'Connected' if supabase else 'Failed'}")
    print(f"📧 Email: {'Enabled' if mail else 'Disabled'}")
    print("===================================")
    
    # Run Flask app (no simulator thread - using REAL data from RPi)
    app.run(host="0.0.0.0", port=5000, debug=False)