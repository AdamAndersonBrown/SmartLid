import os

file_path = os.path.join("main", "hardware", "touch_manager.c")

try:
    with open(file_path, "r") as f:
        content = f.read()

    # Swap the backend execution angles while leaving the UI labels alone
    old_left = 'if (x < 100) { ESP_LOGW(TAG, "UI Zone: LEFT (LOCK)"); servo_set_manual(0); }'
    new_left = 'if (x < 100) { ESP_LOGW(TAG, "UI Zone: LEFT (LOCK)"); servo_set_manual(180); }'
    
    old_right = 'else if (x > 220) { ESP_LOGW(TAG, "UI Zone: RIGHT (UNLOCK)"); servo_set_manual(180); }'
    new_right = 'else if (x > 220) { ESP_LOGW(TAG, "UI Zone: RIGHT (UNLOCK)"); servo_set_manual(0); }'

    content = content.replace(old_left, new_left)
    content = content.replace(old_right, new_right)

    with open(file_path, "w") as f:
        f.write(content)
        
    print("SUCCESS: UI touch zones have been successfully reversed on the backend.")
except Exception as e:
    print(f"ERROR: {e}")