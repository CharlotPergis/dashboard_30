import requests
import time
import math
from datetime import datetime

import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

import board
import busio
import adafruit_mlx90614

import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# =========================================================
# CONFIG
# =========================================================
LCD_REFRESH_INTERVAL = 1.0
FLASK_URL = "http://127.0.0.1:5000/api/update"
TIMEOUT = 2

time.sleep(2)


# =========================================================
# GPIO SETUP
# =========================================================
GREEN_LED = 17
RED_LED = 27
BUZZER = 22

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(GREEN_LED, GPIO.OUT)
GPIO.setup(RED_LED, GPIO.OUT)
GPIO.setup(BUZZER, GPIO.OUT)

GPIO.output(GREEN_LED, 0)
GPIO.output(RED_LED, 0)
GPIO.output(BUZZER, 0)

warning_last_toggle = 0
critical_last_toggle = 0
critical_buzzer_on = False
# =========================================================
# I2C SETUP
# =========================================================
i2c = busio.I2C(board.SCL, board.SDA)

# =========================================================
# MLX90614 SETUP
# =========================================================
mlx = None

def init_mlx():
    global mlx
    try:
        mlx = adafruit_mlx90614.MLX90614(i2c)
        print("✔ MLX initialized")
    except Exception as e:
        print("MLX INIT FAILED:", e)
        mlx = None

init_mlx()

def read_temperature():
    global mlx
    try:
        if mlx is None:
            init_mlx()

        return float(mlx.object_temperature)

    except Exception as e:
        print("MLX ERROR:", e)
        init_mlx()
        return 0.0

# =========================================================
# SCT-013-000 FINAL CALIBRATED MODULE (THESIS READY)
# =========================================================
TIMEOUT = 2
CT_RATIO = 2000.0
BURDEN_RESISTOR = 22.0

# FINAL CALIBRATION (LOCKED FROM YOUR CLAMP TEST)
CALIBRATION = 0.95

NO_LOAD_THRESHOLD = 0
WINDOW_SEC = 0.8

# =========================================================
# INIT
# =========================================================

ads = ADS.ADS1115(i2c)
ads.gain = 1
ads.data_rate = 860

# A1 channel (your hardware)
chan = AnalogIn(ads, 1)

_offset = 1.63976 # fixed

def read_current(window_sec=WINDOW_SEC):

    start = time.time()

    sum_sq = 0.0
    samples = 0

    while (time.time() - start) < window_sec:

        v = chan.voltage

        centered = v - _offset

        sum_sq += centered * centered
        samples += 1

        time.sleep(0.001)

    if samples == 0:
        return 0.0

    vrms = math.sqrt(sum_sq / samples)

    current = (vrms * CT_RATIO / BURDEN_RESISTOR) * CALIBRATION

    if current < NO_LOAD_THRESHOLD:
        current = 0.0

    return round(current, 2)

# =========================================================
# LCD SETUP
# =========================================================
def init_lcd():
    for i in range(3):
        try:
            lcd = CharLCD(
                i2c_expander='PCF8574',
                address=0x27,
                port=1,
                cols=16,
                rows=4
            )
            lcd.clear()
            return lcd
        except Exception as e:
            print(f"LCD retry {i+1}/3 failed:", e)
            time.sleep(1)

    raise RuntimeError("LCD failed")

lcd = init_lcd()

# =========================================================
# HELPERS
# =========================================================
def get_time():
    return datetime.now().strftime("%H:%M:%S")

def center(text):
    text = str(text)
    return text[:16] if len(text) > 16 else text.center(16)

def safe_float(value):
    try:
        return float(value) if value is not None else 0.0
    except:
        return 0.0
# =========================================================
# OUTPUT STATE VARIABLES
# =========================================================
last_beep_time = 0
last_green_blink = 0

green_state = False
buzzer_state = False

warning_last_toggle = 0
warning_buzzer_on = False
# =========================================================
# GPIO CONTROL
# =========================================================
def set_outputs(state):
    global warning_last_toggle, warning_buzzer_on
    global critical_last_toggle, critical_buzzer_on

    now = time.time()

    # =========================
    # NORMAL
    # =========================
    if state == "Normal":
        GPIO.output(GREEN_LED, 1)
        GPIO.output(RED_LED, 0)
        GPIO.output(BUZZER, 0)

    # =========================
    # WARNING (2 sec ON, 3 sec OFF cycle)
    # =========================
    elif state == "Warning":
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)

        if now - warning_last_toggle >= (2 if warning_buzzer_on else 3):
            warning_buzzer_on = not warning_buzzer_on
            GPIO.output(BUZZER, warning_buzzer_on)
            warning_last_toggle = now

    # =========================
    # CRITICAL (fast intermittent + long beep feel)
    # =========================
    elif state == "Critical":
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)

        # fast beep cycle (0.2s on/off)
        if now - critical_last_toggle >= 0.2:
            critical_buzzer_on = not critical_buzzer_on
            GPIO.output(BUZZER, critical_buzzer_on)
            critical_last_toggle = now

    elif state == "WarmingUp":
        GPIO.output(GREEN_LED, int(time.time() * 2) % 2)
        GPIO.output(RED_LED, 0)
        GPIO.output(BUZZER, 0)

    else:
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)
        GPIO.output(BUZZER, 0)

# =========================================================
# LCD DISPLAY
# =========================================================
def lcd_update(state, ml, temp, current):
    try:
        now = get_time()

        temp = safe_float(temp)
        current = safe_float(current)

        hotspot = ml.get("hotspot_prob", 0.0) if ml else 0.0
        overload = ml.get("overload_prob", 0.0) if ml else 0.0

        # =========================
        # LINE 1: TIME
        # =========================
        lcd.cursor_pos = (0, 0)
        lcd.write_string(center(now))

        # =========================
        # LINE 2: TEMPERATURE
        # =========================
        lcd.cursor_pos = (1, 0)
        lcd.write_string(center(f"T:{temp:.1f}C"))

        # =========================
        # LINE 3: CURRENT
        # =========================
        lcd.cursor_pos = (2, 0)
        lcd.write_string(center(f"I:{current:.2f}A"))

        # =========================
        # LINE 4: STATE + ALERT FLAGS
        # =========================
        lcd.cursor_pos = (3, 0)

        if state == "Normal":
            lcd.write_string(center("SYSTEM OK"))

        elif state == "Warning":
            if hotspot >= 0.6 and overload >= 0.6:
                lcd.write_string(center("WARN: H+OVERLOAD"))
            elif hotspot >= 0.6:
                lcd.write_string(center("WARN: OVERHEAT"))
            elif overload >= 0.6:
                lcd.write_string(center("WARN: OVERLOAD"))
            else:
                lcd.write_string(center("CHECK LOAD"))

        elif state == "Critical":
            if hotspot >= 0.85 and overload >= 0.85:
                lcd.write_string(center("CRIT: H+OVERLOAD"))
            elif hotspot >= 0.85:
                lcd.write_string(center("CRIT: OVERHEAT"))
            elif overload >= 0.85:
                lcd.write_string(center("CRIT: OVERLOAD"))
            else:
                lcd.write_string(center("CRITICAL"))

        elif state == "WarmingUp":
            lcd.write_string(center("STARTING UP"))

        else:
            lcd.write_string(center("SYSTEM ERROR"))

    except Exception as e:
        print("LCD ERROR:", e)
        try:
            lcd.clear()
        except:
            pass


# =========================================================
# MAIN LOOP
# =========================================================
def run():
    print("System running...")

    last_lcd = 0
    last_sensor = 0

    temp = 0.0
    current = 0.0
    state = "Normal"
    ml = {"composite_risk": 0}

    while True:
        now = time.time()

        if now - last_sensor >= 3:
            temp = read_temperature()
            current = read_current()

            print(f"[{get_time()}] T={temp:.2f}°C | I={current:.2f}A | State={state}")

            try:
                response = requests.post(
                    FLASK_URL,
                    json={"temperature": temp, "current": current},
                    timeout=TIMEOUT
                )

                result = response.json()
                state = result.get("state", "Normal")
                ml = result.get("ml", ml)

            except Exception as e:
                print("API ERROR:", e)
                state = "Warning"

            set_outputs(state)
            last_sensor = now

        if now - last_lcd >= LCD_REFRESH_INTERVAL:
            lcd_update(state, ml, temp, current)
            last_lcd = now

        time.sleep(0.1)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        GPIO.cleanup()
        try:
            lcd.clear()
        except:
            pass
