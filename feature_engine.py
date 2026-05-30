import numpy as np
import pandas as pd
from collections import deque

# =========================================================
# STREAMING BUFFERS (SHORT + LONG MEMORY)
# =========================================================
temp_buffer_short = deque(maxlen=10)
temp_buffer_long = deque(maxlen=50)

current_buffer_short = deque(maxlen=10)
current_buffer_long = deque(maxlen=50)


# =========================================================
# RESET BUFFERS (IMPORTANT FOR STARTUP)
# =========================================================
def reset_buffers():
    temp_buffer_short.clear()
    temp_buffer_long.clear()
    current_buffer_short.clear()
    current_buffer_long.clear()


# =========================================================
# INTERNAL BUFFER UPDATE
# =========================================================
def _update_buffers(temp, current):
    temp_buffer_short.append(float(temp))
    temp_buffer_long.append(float(temp))

    current_buffer_short.append(float(current))
    current_buffer_long.append(float(current))


# =========================================================
# FEATURE ENGINE (SHORT + LONG TERM PHYSICS MODEL)
# =========================================================
def build_basic_features(temp, current):

    temp = float(temp)
    current = float(current)

    _update_buffers(temp, current)

    # =====================================================
    # WARM-UP MODE (INSUFFICIENT DATA)
    # =====================================================
    if len(temp_buffer_short) < 10 or len(temp_buffer_long) < 10:
        power_loss = 0.01 * (current ** 2)
        features = {
            "ambient_temp_c": temp,
            "temperature_c": temp,
            "current_a": current,

            "current_squared": current ** 2,
            "power_loss": power_loss,
            "thermal_stress": 0.0,

            "temp_slope_short": 0.0,
            "temp_slope_long": 0.0,
            "current_slope_short": 0.0,
            "current_slope_long": 0.0,

            "temp_acceleration": 0.0,
            "trend_strength": 0.0,

            "temp_ema": temp,
            "current_ema": current,

     
        }

        for i in range(10):
            features[f"temp_lag_{i+1}"] = temp
            features[f"current_lag_{i+1}"] = current

        return pd.DataFrame([features])

    # =====================================================
    # CONVERT BUFFERS TO ARRAYS
    # =====================================================
    t_s = np.array(temp_buffer_short, dtype=np.float32)
    c_s = np.array(current_buffer_short, dtype=np.float32)

    t_l = np.array(temp_buffer_long, dtype=np.float32)
    c_l = np.array(current_buffer_long, dtype=np.float32)



    # =====================================================
    # SHORT TERM SLOPES (FAST RESPONSE)
    # =====================================================
    temp_slope_short = (t_s[-1] - t_s[0]) / len(t_s)
    current_slope_short = (c_s[-1] - c_s[0]) / len(c_s)

    # =====================================================
    # LONG TERM SLOPES (OVERHEATING DETECTION)
    # =====================================================
    temp_slope_long = (t_l[-1] - t_l[0]) / len(t_l)
    current_slope_long = (c_l[-1] - c_l[0]) / len(c_l)

    # =====================================================
    # ACCELERATION (THERMAL RUNAWAY DETECTION)
    # =====================================================
    temp_acceleration = t_s[-1] - 2*t_s[-2] + t_s[-3]

    # =====================================================
    # TREND STRENGTH (CONSISTENCY OF HEATING)
    # =====================================================
    trend_strength = np.mean(np.diff(t_s) > 0)

    # =====================================================
    # EMA (SMOOTH SIGNAL)
    # =====================================================
    weights = np.linspace(0.2, 1.0, len(t_s))
    temp_ema = np.sum(t_s * weights) / np.sum(weights)
    current_ema = np.sum(c_s * weights) / np.sum(weights)

    # =====================================================
    # THERMAL MEMORY (SLOW HEAT BUILDUP)
    # =====================================================
    thermal_memory = np.mean(t_l)

    # =====================================================
    # LAGS
    # =====================================================
    temp_lags = list(t_s[::-1])[:10]
    curr_lags = list(c_s[::-1])[:10]

    while len(temp_lags) < 10:
        temp_lags.append(temp)

    while len(curr_lags) < 10:
        curr_lags.append(current)

    # =====================================================
    # FINAL FEATURE SET
    # =====================================================
    features = {
        "ambient_temp_c": temp,
        "temperature_c": temp,
        "current_a": current,

        "current_squared": current ** 2,
        "power_loss": 0.01 * (current ** 2),
        "thermal_stress": temp * current,

        "temp_slope_short": temp_slope_short,
        "temp_slope_long": temp_slope_long,
        "current_slope_short": current_slope_short,
        "current_slope_long": current_slope_long,

        "temp_acceleration": temp_acceleration,
        "trend_strength": trend_strength,

        "temp_ema": temp_ema,
        "current_ema": current_ema,

        "thermal_memory": thermal_memory,

    }

    for i in range(10):
        features[f"temp_lag_{i+1}"] = temp_lags[i]
        features[f"current_lag_{i+1}"] = curr_lags[i]

    return pd.DataFrame([features])