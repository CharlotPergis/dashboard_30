from supabase import create_client
from datetime import datetime
import time
import random

SUPABASE_URL = "https://qkniqwgcwvxkgjciccad.supabase.co"
SUPABASE_KEY = "sb_publishable_pzHW1LlymSCVL876qchBKw_pPY0xN-2"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def read_temperature():
    return 25 + random.uniform(-5, 15)

def read_current():
    return 15 + random.uniform(-5, 25)

print("="*50)
print("🚀 Breaker Monitor - Sending to Supabase (FAST MODE)")
print(f"📡 URL: {SUPABASE_URL}")
print("="*50)

success = 0
errors = 0

while True:
    try:
        temp = read_temperature()
        current = read_current()
        
        # Determine state
        if temp > 75 or current > 45:
            state = "Overheating"
            hot_prob = 0.92
            ovl_prob = 0.88
        elif temp > 60 or current > 35:
            state = "Overload"
            hot_prob = 0.78
            ovl_prob = 0.72
        elif temp > 50 or current > 28:
            state = "Potential Overload"
            hot_prob = 0.58
            ovl_prob = 0.52
        else:
            state = "Normal"
            hot_prob = 0.12
            ovl_prob = 0.10
        
        composite = (hot_prob + ovl_prob) / 2
        
        data = {
            "created_at": datetime.now().isoformat(),
            "temperature_c": round(temp, 2),
            "current_a": round(current, 2),
            "breaker_state": state,
            "hotspot_probability": round(hot_prob, 3),
            "overload_probability": round(ovl_prob, 3),
            "composite_risk": round(composite, 3)
        }
        
        response = supabase.table("breaker_readings").insert(data).execute()
        
        success += 1
        print(f"✅ [{success}] Sent: {temp:.1f}°C, {current:.1f}A, {state}")
        
    except Exception as e:
        errors += 1
        print(f"❌ Error: {e}")
    
    # CHANGE THIS VALUE TO MAKE IT FASTER:
    time.sleep(1)  # Sends every 0.5 seconds (2x per second)