# update_code.py
import os

def patch_servo():
    # Dynamically locate the file across the project tree
    app_path = None
    for root, dirs, files in os.walk("."):
        if "servo_manager.c" in files:
            app_path = os.path.join(root, "servo_manager.c")
            break

    if not app_path:
        print("Error: servo_manager.c not found anywhere in the directory tree.")
        return

    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify we haven't already patched this file
    if "servo_move_smooth(target_angle, 3);" in content:
        print(f"-> {app_path} is already patched.")
        return
    if "servo_move_smooth(target_angle, 15);" not in content:
        print(f"Error: Target delay not found in {app_path}. Has the code been altered?")
        return

    # 1. Patch the ML Unlock & Touch UI sweep (15ms -> 3ms is exactly 5x faster)
    content = content.replace("servo_move_smooth(target_angle, 15);", "servo_move_smooth(target_angle, 3);")
    content = content.replace("15ms per degree gives a slightly slower, highly deliberate sweep", "3ms per degree gives a 5x faster sweep for active ML unlocks")

    # 2. Patch the background latch test task (8ms -> 2ms is roughly 5x faster)
    content = content.replace("servo_move_smooth(180, 8);", "servo_move_smooth(180, 2);")
    content = content.replace("servo_move_smooth(0, 8);", "servo_move_smooth(0, 2);")

    with open(app_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"SUCCESS: {app_path} patched. Servo interpolation delays decreased by a factor of 5.")

if __name__ == "__main__":
    patch_servo()