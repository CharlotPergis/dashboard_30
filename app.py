from flask import Flask, request, jsonify, render_template
import joblib
import os
import time
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime

from feature_engine import (
    build_basic_features,
    temp_buffer,
    current_buffer
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

# Email config
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

# ----------------------
# Email Alert Function
# ----------------------
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

# ----------------------
# Alert Tracking
# ----------------------
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
# SYSTEM CONFIG
# =========================================================
WARMUP_SAMPLES = 10
WARNING_THRESHOLD = 0.60
CRITICAL_THRESHOLD = 0.85

# =========================================================
# API
# =========================================================
@app.route("/api/update", methods=["POST"])
def update_data():

    global latest_data_store

    try:
        # RECEIVE DATA
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

        # STORE DATA
        latest_data_store = {
            "temperature": round(temp, 2),
            "current": round(current, 2),
            "breakerState": state,
            "status": status,
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
            f"HP={hot_prob:.3f} | OP={ovl_prob:.3f}"
        )

        return jsonify({
            "success": True,
            "state": state,
            "status": status,
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
# HEALTH CHECK
# =========================================================
@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "models_loaded": True,
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

    app.run(host="0.0.0.0", port=5000, debug=False)
