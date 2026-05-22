import requests
import time
import os
from datetime import datetime

import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

import board
import busio
import adafruit_mlx90614

import numpy as np
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn


# =========================================================
# CONFIG
# =========================================================
SAMPLE_INTERVAL = 1.0
LCD_REFRESH_INTERVAL = 1.0
I2C_RECOVERY_INTERVAL = 10

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


# =========================================================
# SAFE MLX INIT
# =========================================================
mlx = None

def init_mlx():
    global mlx
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        mlx = adafruit_mlx90614.MLX90614(i2c)
        print("✔ MLX initialized")
    except Exception as e:
        print("MLX INIT FAILED:", e)
        mlx = None

init_mlx()


# =========================================================
# ADS1115 + SCT SETUP (NEW)
# =========================================================
i2c_ads = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c_ads)

ads.gain = 1
ads.data_rate = 860

chan = AnalogIn(ads, 0)

BURDEN_RESISTOR = 220.0
CT_RATIO = 2000
CALIBRATION = 0.0505
SAMPLES = 800
NOISE_THRESHOLD = 0.05


# =========================================================
# LCD INIT
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
            time.sleep(0.5)
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


# =========================================================
# TEMP READ
# =========================================================
def read_temperature():
    global mlx

    try:
        if mlx is None:
            init_mlx()

        return float(mlx.object_temperature)

    except Exception as e:
        print("MLX ERROR:", e)
        init_mlx()
        return 35.0


# =========================================================
# CURRENT (SCT-013-000 RMS IMPLEMENTATION)
# =========================================================
def read_current():

    samples = []

    for _ in range(SAMPLES):
        samples.append(chan.voltage)

    samples = np.array(samples)

    # remove DC bias
    samples = samples - np.mean(samples)

    vrms = np.sqrt(np.mean(samples ** 2))

    secondary_current = vrms / BURDEN_RESISTOR
    primary_current = secondary_current * CT_RATIO

    primary_current *= CALIBRATION

    if primary_current < NOISE_THRESHOLD:
        primary_current = 0

    return primary_current


# =========================================================
# OUTPUT CONTROL
# =========================================================
def set_outputs(state):
    if state == "Normal":
        GPIO.output(GREEN_LED, 1)
        GPIO.output(RED_LED, 0)
        GPIO.output(BUZZER, 0)

    elif state == "Warning":
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)
        GPIO.output(BUZZER, 0)

    else:
        GPIO.output(GREEN_LED, 0)
        GPIO.output(RED_LED, 1)
        GPIO.output(BUZZER, 1)


# =========================================================
# LCD UPDATE
# =========================================================
def lcd_update(state, ml, temp, current):
    try:
        now = get_time()

        hp = ml.get("hotspot_prob", 0.0) if ml else 0.0
        op = ml.get("overload_prob", 0.0) if ml else 0.0
        cr = ml.get("composite_risk", 0.0) if ml else 0.0

        lcd.cursor_pos = (0, 0)
        lcd.write_string(center(now))

        lcd.cursor_pos = (1, 0)
        lcd.write_string(center(f"T:{temp:.1f}C"))

        lcd.cursor_pos = (2, 0)
        lcd.write_string(center(f"I:{current:.2f}A"))

        lcd.cursor_pos = (3, 0)
        lcd.write_string(center(f"{state} {cr:.2f}"))

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
    last_recovery = time.time()

    last_valid_ml = {"hotspot_prob": 0, "overload_prob": 0, "composite_risk": 0}

    while True:
        try:
            temp = read_temperature()
            current = read_current()

            try:
                response = requests.post(
                    FLASK_URL,
                    json={"temperature": temp, "current": current},
                    timeout=TIMEOUT
                )
                result = response.json()

                state = result.get("state", "Normal")
                ml = result.get("ml", last_valid_ml)

                last_valid_ml = ml

            except Exception as api_error:
                print("API ERROR:", api_error)
                state = "Warning"
                ml = last_valid_ml

            set_outputs(state)

            now = time.time()

            if now - last_lcd >= LCD_REFRESH_INTERVAL:
                lcd_update(state, ml, temp, current)
                last_lcd = now

            print(
                f"[{state}] "
                f"T:{temp:.2f} I:{current:.2f} "
                f"HP:{ml.get('hotspot_prob', 0):.3f} "
                f"OP:{ml.get('overload_prob', 0):.3f} "
                f"CR:{ml.get('composite_risk', 0):.3f}"
            )

            if now - last_recovery > I2C_RECOVERY_INTERVAL:
                os.system("i2cdetect -y 1 > /dev/null 2>&1")
                last_recovery = now

        except Exception as e:
            print("SYSTEM ERROR:", e)

            set_outputs("Critical")

            try:
                lcd.clear()
                lcd.write_string("SYSTEM ERROR")
            except:
                pass

        time.sleep(SAMPLE_INTERVAL)


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
