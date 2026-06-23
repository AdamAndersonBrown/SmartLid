# update_code.py
import os

print("Executing Surgical Patch: Extending hardware sweep limit to 180 degrees...")

# 1. Extend the Touch UI limit
touch_file = "main/hardware/touch_manager.c"
if os.path.exists(touch_file):
    with open(touch_file, "r") as f: 
        content = f.read()
    
    # Replace the 90-degree absolute sweep with 180
    if "servo_set_manual(90);" in content:
        content = content.replace("servo_set_manual(90);", "servo_set_manual(180);")
        with open(touch_file, "w") as f: 
            f.write(content)
        print("-> SUCCESS: touch_manager.c right UI button mapped to 180 degrees.")
    else:
        print("-> ABORT: Target 90-degree logic not found in touch_manager.c.")
else:
    print("-> ERROR: Could not locate touch_manager.c")

# 2. Extend the automated ML sequence limit
servo_file = "main/hardware/servo_manager.c"
if os.path.exists(servo_file):
    with open(servo_file, "r") as f: 
        content = f.read()
    
    # Replace the 90-degree sweep in the latch task with 180
    if "servo_move_smooth(90, 8);" in content:
        content = content.replace("servo_move_smooth(90, 8);", "servo_move_smooth(180, 8);")
        with open(servo_file, "w") as f: 
            f.write(content)
        print("-> SUCCESS: servo_manager.c automated ML latch sequence extended to 180 degrees.")
    else:
        print("-> ABORT: Target 90-degree logic not found in servo_manager.c.")
else:
    print("-> ERROR: Could not locate servo_manager.c")

print("\nPatch complete. Ready to compile.")