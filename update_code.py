# update_code.py
import os
import re

print("Executing Surgical Patch: Reversing Unlock Macro Sequence (180 -> 10 deg)...")

c_file = "main/hardware/servo_manager.c"
if os.path.exists(c_file):
    with open(c_file, "r") as f: 
        content = f.read()

    # 1. Update the initial trigger sweep (to 180)
    content = re.sub(
        r'ESP_LOGI\(TAG,\s*"Unlock Sequence Triggered:[^"]+"\);\s*servo_set_manual\([0-9]+\);',
        r'ESP_LOGI(TAG, "Unlock Sequence Triggered: Sweeping CW (180 deg)");\n    servo_set_manual(180);',
        content
    )
    
    # 2. Update the concluding wait sweep (to 10)
    content = re.sub(
        r'ESP_LOGI\(TAG,\s*"Unlock Sequence Concluding:[^"]+"\);\s*servo_set_manual\([0-9]+\);',
        r'ESP_LOGI(TAG, "Unlock Sequence Concluding: Sweeping CCW (10 deg)");\n    servo_set_manual(10);',
        content
    )

    with open(c_file, "w") as f: 
        f.write(content)
        
    print("-> SUCCESS: servo_manager.c macro sequence reversed.")
else:
    print("-> ERROR: Could not locate servo_manager.c")