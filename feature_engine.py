import numpy as np
import pandas as pd
from collections import deque

# =========================
# STREAMING BUFFERS
# =========================
temp_buffer = deque(maxlen=10)
current_buffer = deque(maxlen=10)


def _update_buffers(temp, current):
    temp_buffer.append(float(temp))
    current_buffer.append(float(current))


# =========================
# FEATURE ENGINE (FIXED + CONSISTENT)
# =========================
def build_basic_features(temp, current):
    """
    FIXED VERSION:
    - consistent training/inference behavior
    - stable early predictions
    - reduced probability inflation
    """

    _update_buffers(temp, current)

    t = np.array(temp_buffer, dtype=float)
    c = np.array(current_buffer, dtype=float)

    # =========================
    # WARM-UP MODE (IMPORTANT FIX)
    # =========================
    if len(t) < 5:
        base_temp = float(temp)
        base_current = float(current)

        features = {
            "ambient_temp_c": base_temp,
            "temperature_c": base_temp,
            "temperature_rise_c": 0.0,
            "current_a": base_current,

            "current_squared": base_current ** 2,
            "power_loss": (base_current ** 2) * 0.01,
            "thermal_stress": 0.0,

            "thermal_slope_c_per_5s": 0.0,
            "current_slope_a_per_5s": 0.0,

            "temp_trend": 0.0,
            "current_trend": 0.0,

            "temp_avg_3": base_temp,
            "current_avg_3": base_current,

            "temp_acceleration": 0.0,
            "temp_trend_long": 0.0,

            # FIX: stable baseline instead of inflated value
            "thermal_memory": base_temp,
        }

        for i in range(1, 10):
            features[f"temp_lag_{i}"] = base_temp
            features[f"current_lag_{i}"] = base_current

        return pd.DataFrame([features])

    # =========================
    # NORMAL MODE (STABLE)
    # =========================
    ambient_temp = float(temp)
    current_a = float(current)

    # Safe arrays (avoid crash if partial buffer)
    t_safe = np.pad(t, (10 - len(t), 0), mode="edge")
    c_safe = np.pad(c, (10 - len(c), 0), mode="edge")

    current_squared = current_a ** 2
    power_loss = current_squared * 0.01

    # FIX: consistent thermal stress definition
    thermal_stress = np.mean(t_safe) * current_a

    # =========================
    # SMOOTH SLOPES
    # =========================
    thermal_slope = (t_safe[-1] - t_safe[0]) / 10 * 5
    current_slope = (c_safe[-1] - c_safe[0]) / 10 * 5

    # =========================
    # LAGS
    # =========================
    temp_lags = list(t_safe[::-1])[:9]
    curr_lags = list(c_safe[::-1])[:9]

    # =========================
    # DERIVED FEATURES (FIXED SAFETY)
    # =========================
    temp_trend = t_safe[-1] - t_safe[-2]
    current_trend = c_safe[-1] - c_safe[-2]

    temp_avg_3 = np.mean(t_safe[-3:])
    current_avg_3 = np.mean(c_safe[-3:])

    temp_acceleration = t_safe[-1] - 2 * t_safe[-2] + t_safe[-3]

    temp_trend_long = t_safe[-1] - t_safe[-7]

    thermal_memory = np.mean(t_safe)

    # =========================
    # FINAL FEATURES
    # =========================
    features = {
        "ambient_temp_c": ambient_temp,
        "temperature_c": ambient_temp,
        "temperature_rise_c": np.mean(t_safe) - 30,  # FIXED baseline (important)

        "current_a": current_a,

        "current_squared": current_squared,
        "power_loss": power_loss,
        "thermal_stress": thermal_stress,

        "thermal_slope_c_per_5s": thermal_slope,
        "current_slope_a_per_5s": current_slope,

        "temp_trend": temp_trend,
        "current_trend": current_trend,

        "temp_avg_3": temp_avg_3,
        "current_avg_3": current_avg_3,

        "temp_acceleration": temp_acceleration,
        "temp_trend_long": temp_trend_long,
        "thermal_memory": thermal_memory,
    }

    for i in range(9):
        features[f"temp_lag_{i+1}"] = temp_lags[i]
        features[f"current_lag_{i+1}"] = curr_lags[i]

    return pd.DataFrame([features])
