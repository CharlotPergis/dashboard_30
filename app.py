from flask import Flask, request, jsonify, render_template
import joblib
import os
import gdown
import time
from flask_cors import CORS
# from flask_mail import Mail, Message  # COMMENTED OUT - Using Resend instead
import resend  # ADDED FOR RESEND EMAIL
from datetime import datetime, timezone
from supabase import create_client
from types import SimpleNamespace
import threading
import traceback
import signal
import sys

from feature_engine import (
    build_basic_features,
    temp_buffer_short,
    temp_buffer_long,
    current_buffer_short,
    current_buffer_long,
    reset_buffers
)

# =========================================================
# GLOBAL EXCEPTION HANDLER
# =========================================================
def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Handle unexpected exceptions gracefully"""
    print(f"❗ UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_value}")
    traceback.print_tb(exc_traceback)
    # Don't crash - just log and continue

# Install global exception handler
sys.excepthook = global_exception_handler

# Handle SIGTERM gracefully
def signal_handler(sig, frame):
    print("\n🛑 Shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# =========================================================
# BASE DIR
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =========================================================
# MODEL SETUP
# =========================================================
MODEL_DIR = os.path.join(BASE_DIR, "ml")
os.makedirs(MODEL_DIR, exist_ok=True)

HOTSPOT_PATH = os.path.join(MODEL_DIR, "hotspot_model.pkl")
OVERLOAD_PATH = os.path.join(MODEL_DIR, "overload_model.pkl")


def download_if_missing(file_id, output_path):
    if not os.path.exists(output_path):
        print(f"⬇ Downloading model: {output_path}")
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, output_path, quiet=False)


# DOWNLOAD MODELS
download_if_missing("1t0AFcMD8VfsCJjK6NHkM8-O5rlZh9-2j", HOTSPOT_PATH)
download_if_missing("1LV1QmQmT1JL8fG5RoXZn-ae44_K12xVn", OVERLOAD_PATH)

# LOAD MODELS
hotspot_model = None
overload_model = None

try:
    hotspot_model = joblib.load(HOTSPOT_PATH)
    overload_model = joblib.load(OVERLOAD_PATH)

    # Get expected feature names from models
    HOTSPOT_FEATURES = hotspot_model.feature_names_in_.tolist()
    OVERLOAD_FEATURES = overload_model.feature_names_in_.tolist()

    print("✓ ML models loaded successfully (Google Drive)")
    print("HOTSPOT FEATURES:", HOTSPOT_FEATURES)
    print("OVERLOAD FEATURES:", OVERLOAD_FEATURES)

except Exception as e:
    print(f"❌ Model loading failed: {e}")

    HOTSPOT_FEATURES = []
    OVERLOAD_FEATURES = []

# =========================================================
# FLASK INIT (ONLY ONCE)
# =========================================================
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

# Thread lock for buffer operations
buffer_lock = threading.Lock()
store_lock = threading.Lock()

latest_data_store = {}

print("🔥 INITIALIZING SYSTEM...")

# =========================================================
# FEATURE BUILDERS
# =========================================================
def build_hotspot_X(temp, current):
    try:
        feat = build_basic_features(temp, current)
        # Handle case when HOTSPOT_FEATURES is empty
        if HOTSPOT_FEATURES:
            feat = feat.reindex(columns=HOTSPOT_FEATURES, fill_value=0)
        return feat
    except Exception as e:
        print(f"⚠ Hotspot feature build error: {e}")
        # Return empty feature set as fallback
        import pandas as pd
        if HOTSPOT_FEATURES:
            return pd.DataFrame([[0] * len(HOTSPOT_FEATURES)], columns=HOTSPOT_FEATURES)
        else:
            return pd.DataFrame([[0] * 10])  # Default fallback


def build_overload_X(temp, current):
    try:
        feat = build_basic_features(temp, current)
        # Handle case when OVERLOAD_FEATURES is empty
        if OVERLOAD_FEATURES:
            feat = feat.reindex(columns=OVERLOAD_FEATURES, fill_value=0)
        return feat
    except Exception as e:
        print(f"⚠ Overload feature build error: {e}")
        # Return empty feature set as fallback
        import pandas as pd
        if OVERLOAD_FEATURES:
            return pd.DataFrame([[0] * len(OVERLOAD_FEATURES)], columns=OVERLOAD_FEATURES)
        else:
            return pd.DataFrame([[0] * 10])  # Default fallback

# =========================================================
# SUPABASE CONFIGURATION
# =========================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = None

# Initialize Supabase client properly
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✓ Supabase client initialized successfully")
        
        # Test the connection immediately
        test_response = supabase.table("breaker_readings").select("count", count="exact").limit(1).execute()
        print("✓ Supabase connection verified")
        
    except Exception as e:
        print(f"✗ Supabase initialization error: {e}")
        print("⚠ Running without Supabase - data will be saved locally only")
        supabase = None
else:
    print("⚠ Supabase credentials missing - running without Supabase")

# =========================================================
# EMAIL CONFIG - RESEND API (Works on Render Free Tier)
# =========================================================
# Get API key from environment variable
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

email_enabled = False

if RESEND_API_KEY:
    try:
        resend.api_key = RESEND_API_KEY
        email_enabled = True
        print("✓ Resend API initialized - Email alerts active")
    except Exception as e:
        print(f"✗ Resend initialization error: {e}")
        email_enabled = False
else:
    print("⚠ RESEND_API_KEY not found - email alerts disabled")

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
alert_lock = threading.Lock()

def should_send_alert(alert_key):
    """Check if alert should be sent based on cooldown period"""
    with alert_lock:
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
    """Send sensor data to Supabase with accurate server timestamp"""
    
    if supabase is None:
        print("⚠ Supabase not available, skipping insert")
        return False
    
    try:
        # Generate accurate UTC timestamp from server
        accurate_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Prepare data matching your table structure
        data = {
            "temperature_c": round(float(temp), 2),
            "current_a": round(float(current), 2),
            "breaker_state": state,
            "hotspot_probability": round(float(hot_prob), 4),
            "overload_probability": round(float(ovl_prob), 4),
            "composite_risk": round(float(composite_risk), 4),
            "recommended_action": action[:200] if action else "Monitor system",
            "created_at": accurate_timestamp
        }
        
        print(f"📤 Attempting Supabase insert...")
        print(f"   Data: {data}")
        
        # Insert to Supabase
        response = supabase.table("breaker_readings").insert(data).execute()
        
        # Check if successful
        if response and hasattr(response, 'data'):
            print(f"✓ Supabase INSERT SUCCESS | {temp:.1f}°C | {current:.1f}A | {state}")
            print(f"   Timestamp: {accurate_timestamp}")
            print(f"   Response: {response.data}")
            return True
        else:
            print(f"⚠ Supabase insert returned unexpected response: {response}")
            return False
            
    except Exception as e:
        print(f"✗ Supabase INSERT ERROR: {e}")
        print(f"   Full traceback: {traceback.format_exc()}")
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
# ENHANCED EMAIL ALERT SYSTEM - RESEND API VERSION
# =========================================================
def send_breaker_alert(reading, risk, alert_type, message_action):
    """Send email alert using Resend API"""
    
    if not email_enabled:
        print("⚠ Email skipped (Resend not configured)")
        return False, "Email disabled"

    # CHANGED: Only send to your email for testing
    recipients = [
        'pergishazel@gmail.com',  # Only your email
    ]

    hotspot_prob = risk['hotspot_prob']
    overload_prob = risk['overload_prob']
    
    # Use the actual thresholds from app.py
    is_critical_hotspot = hotspot_prob >= CRITICAL_THRESHOLD
    is_critical_overload = overload_prob >= CRITICAL_OVL
    is_warning_hotspot = hotspot_prob >= WARNING_THRESHOLD
    is_warning_overload = overload_prob >= WARNING_OVL
    
    if alert_type == "Critical":
        # Determine the specific critical condition based on thresholds
        if is_critical_hotspot and is_critical_overload:
            subject = "🔴🔴 CRITICAL: Severe Overheating AND Overload Detected!"
            primary_issue = "CRITICAL: Both OVERHEATING and OVERLOAD detected!"
        elif is_critical_hotspot:
            subject = "🔥 CRITICAL: Breaker Overheating Alert!"
            primary_issue = "CRITICAL OVERHEATING DETECTED"
        elif is_critical_overload:
            subject = "⚠️ CRITICAL: Severe Electrical Overload!"
            primary_issue = "CRITICAL OVERLOAD DETECTED"
        else:
            subject = "🔴 CRITICAL: Breaker System Emergency!"
            primary_issue = "CRITICAL SYSTEM STATE"
        
        body = f"""IMMEDIATE ACTION REQUIRED

{primary_issue}

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A
Hotspot Probability: {hotspot_prob*100:.1f}% {'(CRITICAL)' if is_critical_hotspot else '(WARNING)' if is_warning_hotspot else ''}
Overload Probability: {overload_prob*100:.1f}% {'(CRITICAL)' if is_critical_overload else '(WARNING)' if is_warning_overload else ''}

--- PROACTIVE ACTION RECOMMENDED ---
{message_action}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    elif alert_type == "Warning":
        # Determine the specific warning condition
        if is_warning_hotspot and is_warning_overload:
            subject = "⚠️⚠️ WARNING: Multiple Issues Detected - Take Action"
            primary_issue = "WARNING: Both Temperature and Load Issues Detected"
        elif is_warning_hotspot:
            subject = "⚠️ WARNING: Temperature Rising - Potential Hotspot"
            primary_issue = "ELEVATED TEMPERATURE DETECTED"
        elif is_warning_overload:
            subject = "⚠️ WARNING: High Current Detected - Potential Overload"
            primary_issue = "HIGH ELECTRICAL LOAD DETECTED"
        else:
            subject = "⚠️ WARNING: Breaker System Alert"
            primary_issue = "SYSTEM WARNING"
        
        body = f"""PREVENTIVE ACTION RECOMMENDED

{primary_issue}

Temperature: {reading.temperature_c:.1f}°C
Current: {reading.current_a:.2f}A
Hotspot Probability: {hotspot_prob*100:.1f}% {'(WARNING)' if is_warning_hotspot else ''}
Overload Probability: {overload_prob*100:.1f}% {'(WARNING)' if is_warning_overload else ''}

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

Hotspot Risk: {hotspot_prob*100:.1f}%
Overload Risk: {overload_prob*100:.1f}%

--- PROACTIVE ACTION RECOMMENDED ---
{message_action}
"""

    try:
        # Send email using Resend API
        response = resend.Emails.send({
            "from": "Breaker Monitor <onboarding@resend.dev>",
            "to": recipients,
            "subject": subject,
            "text": body,
        })
        
        print(f"✓ Email sent via Resend: {subject}")
        print(f"   Email ID: {response.get('id', 'unknown')}")
        print(f"   - Hotspot: {hotspot_prob*100:.1f}% (Threshold: {CRITICAL_THRESHOLD*100:.0f}% for critical)")
        print(f"   - Overload: {overload_prob*100:.1f}% (Threshold: {CRITICAL_OVL*100:.0f}% for critical)")
        return True, "Sent"

    except Exception as e:
        print(f"✗ Email failed: {e}")
        log_fallback_alert(subject, body)
        return False, str(e)

# =========================================================
# STATE LOGIC (Version 2 preserved)
# =========================================================
def determine_state(hot_prob, ovl_prob):
    try:
        with buffer_lock:
            # Safely check buffer lengths
            temp_short_len = len(temp_buffer_short) if temp_buffer_short else 0
            temp_long_len = len(temp_buffer_long) if temp_buffer_long else 0
            
            if temp_short_len < WARMUP_SAMPLES or temp_long_len < WARMUP_SAMPLES:
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
    except Exception as e:
        print(f"⚠ State determination error: {e}")
        return "Normal", "System monitoring active"

# =========================================================
# ACTION ENGINE (Version 2 preserved)
# =========================================================
def get_action(state, hotspot, overload):
    try:
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
    except Exception as e:
        print(f"⚠ Action generation error: {e}")
        return "Monitor system - check connections"

# =========================================================
# API ENDPOINT - FLASK CALCULATES EVERYTHING
# =========================================================
@app.route("/api/update", methods=["POST"])
def update_data():
    start_time = time.time()
    
    # ===== VALIDATION =====
    try:
        data = request.get_json(force=True, silent=True, cache=False)
        if not data:
            return jsonify({"error": "No data received", "status": "error"}), 400
        
        # Safe extraction with defaults
        temp = float(data.get("temperature", 0))
        current = float(data.get("current", 0))
        
        # Validate ranges
        if temp < -20 or temp > 150:
            return jsonify({"error": f"Invalid temperature: {temp}"}), 400
        if current < 0 or current > 100:
            return jsonify({"error": f"Invalid current: {current}"}), 400
            
    except (TypeError, ValueError, Exception) as e:
        return jsonify({"error": f"Invalid sensor data: {str(e)}"}), 400
    
    # ===== ENHANCED DEBUG: SHOW EXACT RPI DATA =====
    print(f"\n{'='*60}")
    print(f"📡 RPi RAW DATA RECEIVED:")
    print(f"   Temperature: {temp}°C")
    print(f"   Current: {current}A")
    
    # ===== UPDATE BUFFERS WITH THREAD SAFETY =====
    try:
        with buffer_lock:
            temp_buffer_short.append(temp)
            temp_buffer_long.append(temp)
            current_buffer_short.append(current)
            current_buffer_long.append(current)
        
        # Safe maxlen access
        buffer_max = temp_buffer_short.maxlen if hasattr(temp_buffer_short, 'maxlen') else 10
        print(f"📊 Buffer sizes: {len(temp_buffer_short)}/{buffer_max}")
    except Exception as e:
        print(f"⚠ Buffer update error: {e}")
        # Continue even if buffers fail
    
    # ==================================================
    # FEATURE EXTRACTION WITH ERROR HANDLING
    # ==================================================
    try:
        X_hot = build_hotspot_X(temp, current)
        X_ovr = build_overload_X(temp, current)
    except Exception as e:
        print(f"❌ Feature extraction failed: {e}")
        # Return safe fallback response
        return jsonify({
            "temperature": float(temp),
            "current": float(current),
            "state": "Normal",
            "breakerState": "Normal",
            "status": "System online - monitoring",
            "action": "System normal, continuing monitoring",
            "ml": {
                "hotspot_prob": 0.0,
                "overload_prob": 0.0,
                "composite_risk": 0.0
            },
            "forecast": {
                "future_temp": float(temp),
                "future_current": float(current)
            },
            "error": "Feature extraction temporary issue"
        }), 200

    # ==================================================
    # HOTSPOT PREDICTION WITH ERROR HANDLING
    # ==================================================
    hot_prob = 0.0
    try:
        if hotspot_model is not None and X_hot is not None:
            hot_prob = float(hotspot_model.predict_proba(X_hot)[0][1])
            print(f"🔥 Hotspot Model Output: {hot_prob:.4f} ({hot_prob*100:.1f}%)")
        else:
            print("⚠ Hotspot model not loaded")
    except Exception as e:
        print(f"❌ Hotspot prediction failed: {e}")
        hot_prob = 0.0

    # ==================================================
    # OVERLOAD PREDICTION WITH ERROR HANDLING
    # ==================================================
    ovl_prob = 0.0
    try:
        if overload_model is not None and X_ovr is not None:
            ovl_prob = float(overload_model.predict_proba(X_ovr)[0][1])
            print(f"⚡ Overload Model Output: {ovl_prob:.4f} ({ovl_prob*100:.1f}%)")
            
            # Optional calibration for low current
            if current < 16:
                ovl_prob *= 0.5
                print(f"⚡ Overload adjusted (low current): {ovl_prob:.4f} ({ovl_prob*100:.1f}%)")
        else:
            print("⚠ Overload model not loaded")
    except Exception as e:
        print(f"❌ Overload prediction failed: {e}")
        ovl_prob = 0.0

    hot_prob_raw = hot_prob
    ovl_prob_raw = ovl_prob

    # =========================
    # FORECAST CALCULATIONS WITH SAFE DEFAULTS
    # =========================
    future_temp = temp
    future_current = current
    
    try:
        if X_hot is not None and "temp_slope_short" in X_hot.columns and "temp_slope_long" in X_hot.columns:
            slope1 = (
                float(X_hot["temp_slope_short"].iloc[0]) * 0.7 +
                float(X_hot["temp_slope_long"].iloc[0]) * 0.3
            )
            future_temp = temp + slope1 * 10
            print(f"📈 Temperature forecast: {future_temp:.2f}°C")
    except Exception as e:
        print(f"⚠ Temp forecast failed: {e}")

    try:
        if X_ovr is not None and "current_slope_short" in X_ovr.columns:
            slope = float(X_ovr["current_slope_short"].iloc[0])
            future_current = current + slope * 10
            print(f"📈 Current forecast: {future_current:.2f}A")
    except Exception as e:
        print(f"⚠ Current forecast failed: {e}")

    print(f"{'='*60}")

    # =========================
    # Composite risk calculation
    composite_risk = (hot_prob + ovl_prob) / 2

    # =========================
    # STATE (Version 2)
    # =========================
    try:
        state, status = determine_state(hot_prob, ovl_prob)
        print(f"🎯 System State: {state} - {status}")
    except Exception as e:
        print(f"⚠ State determination failed: {e}")
        state = "Normal"
        status = "System monitoring active"

    # Use correct thresholds for overload in action
    action = "System normal, continuing monitoring"
    try:
        action = get_action(
            state,
            hot_prob >= WARNING_THRESHOLD,
            ovl_prob >= WARNING_OVL
        )
        print(f"💡 Recommended Action: {action}")
    except Exception as e:
        print(f"⚠ Action generation failed: {e}")

    # =========================
    # ALERTS (With enhanced cooldown keys and timeout)
    # =========================
    if state in ["Warning", "Critical"]:
        try:
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
            
            # Run alert in separate thread with timeout
            def send_alert_thread():
                try:
                    if should_send_alert(alert_key):
                        print(f"📧 Sending {state} alert (trigger: {alert_trigger})...")
                        
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
                except Exception as e:
                    print(f"⚠ Alert thread error: {e}")
            
            # Start alert in background thread to prevent blocking
            alert_thread = threading.Thread(target=send_alert_thread)
            alert_thread.daemon = True
            alert_thread.start()
            
        except Exception as e:
            print(f"⚠ Alert system error: {e}")

    # =========================
    # SEND TO SUPABASE WITH TIMEOUT
    # =========================
    supabase_success = False
    try:
        # Run supabase insert in separate thread with timeout
        supabase_result = [False]
        
        def supabase_insert():
            try:
                result = send_to_supabase(
                    temp, current, state,
                    hot_prob, ovl_prob,
                    composite_risk, action
                )
                supabase_result[0] = result
            except Exception as e:
                print(f"⚠ Supabase thread error: {e}")
        
        supabase_thread = threading.Thread(target=supabase_insert)
        supabase_thread.daemon = True
        supabase_thread.start()
        supabase_thread.join(timeout=2.0)
        
        supabase_success = supabase_result[0]
        
        if supabase_success:
            print("✅ DATA SAVED TO SUPABASE")
        else:
            print("⚠ Supabase save skipped or timed out")
            
    except Exception as e:
        print(f"❌ Supabase error (non-critical): {e}")

    # =========================
    # STORE RESPONSE
    # =========================
    response_data = {
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
        "buffer_size": int(len(temp_buffer_short)) if temp_buffer_short else 0,
        "time": datetime.now().strftime("%H:%M:%S"),
        "response_time_ms": round((time.time() - start_time) * 1000, 2)
    }
    
    # Update store with thread safety
    try:
        with store_lock:
            latest_data_store.clear()
            latest_data_store.update(response_data)
    except Exception as e:
        print(f"⚠ Store update error: {e}")

    print(f"✅ FINAL: Hotspot={hot_prob*100:.1f}% | Overload={ovl_prob*100:.1f}% | Resp={response_data['response_time_ms']}ms")
    print("="*70)

    # Always return valid JSON, even if some parts failed
    return jsonify(response_data)

# =========================================================
# ROUTES
# =========================================================
@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception as e:
        print(f"⚠ Template error: {e}")
        return "System Online - Dashboard loading...", 200

@app.route("/full_history.html")
def full_history_page():
    try:
        return render_template("full_history.html")
    except Exception as e:
        print(f"⚠ Template error: {e}")
        return "History page - Coming soon", 200

@app.route("/history")
def history_page():
    try:
        return render_template("full_history.html")
    except Exception as e:
        print(f"⚠ Template error: {e}")
        return "History page - Coming soon", 200

@app.route("/logs")
def logs_page():
    try:
        return render_template("full_history.html")
    except Exception as e:
        print(f"⚠ Template error: {e}")
        return "Logs page - Coming soon", 200

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
    
    with store_lock:
        response_data = dict(latest_data_store)
    
    if 'breakerState' not in response_data:
        response_data['breakerState'] = response_data.get('state', 'Normal')
    response_data['has_data'] = True
    
    return jsonify(response_data)

@app.route("/api/health")
def health():
    with buffer_lock:
        buffer_size = len(temp_buffer_short) if temp_buffer_short else 0
        buffer_max = temp_buffer_short.maxlen if (temp_buffer_short and hasattr(temp_buffer_short, 'maxlen')) else 10
    
    with store_lock:
        has_data = bool(latest_data_store and len(latest_data_store) > 0)
    
    return jsonify({
        "status": "online",
        "supabase_connected": supabase is not None,
        "email_enabled": email_enabled,
        "buffer_size": buffer_size,
        "buffer_max": buffer_max,
        "latest_data_available": has_data
    })

@app.route("/api/reset-buffers", methods=["POST"])
def reset_buffers_endpoint():
    with buffer_lock:
        reset_buffers()
    return jsonify({"success": True, "message": "Buffers reset"})

@app.route("/api/test-supabase")
def test_supabase():
    if supabase is None:
        return jsonify({"success": False, "error": "Supabase not initialized"})
    
    try:
        # Test insert first
        test_data = {
            "temperature_c": 0,
            "current_a": 0,
            "breaker_state": "Test",
            "hotspot_probability": 0,
            "overload_probability": 0,
            "composite_risk": 0,
            "recommended_action": "Test connection",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        test_response = supabase.table("breaker_readings").insert(test_data).execute()
        print(f"Test insert response: {test_response}")
        
        # Then select
        response = supabase.table("breaker_readings").select("*").limit(5).execute()
        return jsonify({
            "success": True,
            "message": "Supabase connected and writeable",
            "record_count": len(response.data) if hasattr(response, 'data') else 0
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()})

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
    with buffer_lock:
        buffer_sizes = {
            "temp_short": len(temp_buffer_short) if temp_buffer_short else 0,
            "temp_long": len(temp_buffer_long) if temp_buffer_long else 0,
            "current_short": len(current_buffer_short) if current_buffer_short else 0,
            "current_long": len(current_buffer_long) if current_buffer_long else 0
        }
    
    with store_lock:
        has_data = bool(latest_data_store and len(latest_data_store) > 0)
        store_copy = dict(latest_data_store) if has_data else {}
    
    return jsonify({
        "latest_data_store": store_copy,
        "has_data": has_data,
        "buffer_sizes": buffer_sizes,
        "supabase_connected": supabase is not None
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
    buffer_max = temp_buffer_short.maxlen if (temp_buffer_short and hasattr(temp_buffer_short, 'maxlen')) else 10
    print(f"📊 Buffer size: {buffer_max}")
    print("===================================")
    print("\n⏳ Waiting for Raspberry Pi to connect...")
    print("📡 RPi sends: temperature, current (raw sensor data ONLY)")
    print("🧠 Flask calculates: hotspot_prob, overload_prob using ML models")
    print("🌐 Dashboard available at: http://localhost:5000")
    print("="*50)
    
    # Run with threaded=True to handle concurrent requests better
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
