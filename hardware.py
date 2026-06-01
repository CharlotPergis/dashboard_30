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
warning_buzzer_on = False

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
# SCT-013-000 FINAL CALIBRATED MODULE
# =========================================================
CT_RATIO = 2000.0
BURDEN_RESISTOR = 22.0
CALIBRATION = 1.0

NO_LOAD_THRESHOLD = 0.05
WINDOW_SEC = 0.8

# ADS1115 SETUP
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
ads.gain = 1
ads.data_rate = 860

chan = AnalogIn(ads, 1)

def read_current():

    samples = []
    bias_samples = []

    # =========================
    # Bias estimation
    # =========================
    start_time = time.time()
    while time.time() - start_time < WINDOW_SEC:
        bias_samples.append(chan.voltage)
        time.sleep(0.001)

    bias = sum(bias_samples) / len(bias_samples)

    # =========================
    # RMS sampling
    # =========================
    start_time = time.time()
    while time.time() - start_time < WINDOW_SEC:
        v = chan.voltage
        ac = v - bias
        samples.append(ac)
        time.sleep(0.001)

    sum_sq = sum(s * s for s in samples)
    vrms = math.sqrt(sum_sq / len(samples))

    irms = (vrms / BURDEN_RESISTOR) * CT_RATIO
    irms *= CALIBRATION

    if irms < NO_LOAD_THRESHOLD:
        irms = 0.0

    return irms

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
# GPIO CONTROL
# =========================================================
def set_outputs(state):
    global warning_last_toggle, warning_buzzer_on
    global critical_last_toggle, critical_buzzer_on

    now = time.time()

    if state == "Normal":
        GPIO.output(GREEN_LED, 1)
        GPIO.output(RED_LED, 0)
        GPIO.output(BUZZER, 0)

    elif state == "Warning":
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)

        now = time.time()

    # 0.5s ON / 0.5s OFF pattern
        if now - warning_last_toggle >= 0.5:
            warning_buzzer_on = not warning_buzzer_on
            GPIO.output(BUZZER, 1 if warning_buzzer_on else 0)
            warning_last_toggle = now

    elif state == "Critical":
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)

        # LONG BEEP
        GPIO.output(BUZZER, 1)

    elif state == "WarmingUp":
        GPIO.output(RED_LED, 0)

        blink = (time.time() % 0.3) < 0.15  # fast toggle
        GPIO.output(GREEN_LED, 1 if blink else 0)

        GPIO.output(BUZZER, 0)

    else:
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)
        GPIO.output(BUZZER, 0)

# =========================================================
# LCD UPDATE
# =========================================================
def lcd_update(state, ml, temp, current):
    try:
        now = get_time()

        temp = safe_float(temp)
        current = safe_float(current)

        hotspot = ml.get("hotspot_prob", 0.0) if ml else 0.0
        overload = ml.get("overload_prob", 0.0) if ml else 0.0

        lcd.cursor_pos = (0, 0)
        lcd.write_string(center(now))

        lcd.cursor_pos = (1, 0)
        lcd.write_string(center(f"T:{temp:.1f}C"))

        lcd.cursor_pos = (2, 0)
        lcd.write_string(center(f"I:{current:.2f}A"))

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
    ml = {}

    while True:
        now = time.time()

        if now - last_sensor >= 1.0:
            last_sensor = now

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
                ml = result.get("ml", {})

            except Exception as e:
                print("API ERROR:", e)
                state = "Warning"

            set_outputs(state)

        if now - last_lcd >= LCD_REFRESH_INTERVAL:
            lcd_update(state, ml, temp, current)
            last_lcd = now

        time.sleep(0.02)

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
