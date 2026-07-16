import os

def patch_file(filepath, replacements):
    if not os.path.exists(filepath):
        print(f"Error: Could not find {filepath}")
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    for search, replace in replacements:
        if search in content:
            content = content.replace(search, replace)
        else:
            print(f"Warning: Snippet not found in {filepath} (Already patched?)")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Successfully patched {filepath}")

# 1. Update servo_manager.c
patch_file("main/hardware/servo_manager.c", [
    # A. Add global tracking variables
    (
        "static int current_servo_angle = 0;\nstatic esp_pm_lock_handle_t servo_pm_lock = NULL;",
        "static int current_servo_angle = 0;\nstatic esp_pm_lock_handle_t servo_pm_lock = NULL;\nstatic SemaphoreHandle_t servo_mutex = NULL;\nstatic bool pm_lock_acquired = false;\nstatic bool is_unlocking = false;"
    ),
    
    # B. Initialize the Mutex
    (
        "void servo_manager_init(void) {\n    ESP_LOGI(TAG, \"Initializing Smooth MCPWM V5 Driver on GPIO 33\");",
        "void servo_manager_init(void) {\n    servo_mutex = xSemaphoreCreateMutex();\n    ESP_LOGI(TAG, \"Initializing Smooth MCPWM V5 Driver on GPIO 33\");"
    ),

    # C. Rewrite servo_move_smooth for Thread-Safety, State Tracking, and Failsafe Resync
    (
        """static void servo_move_smooth(int target_angle, int delay_ms) {
    // Hard mechanical limits to prevent piano wire binding
    if (target_angle < 0) target_angle = 0;
    if (target_angle > 180) target_angle = 180;

    // Prevent Light Sleep from killing the APB Clock during active holding/sweeping
    if (current_servo_angle == 0 && target_angle > 0) {
        if (servo_pm_lock) esp_pm_lock_acquire(servo_pm_lock);
    }

    if (comparator != NULL) {
        // Sync interpolation strictly to the 50Hz (20ms) PWM frame to prevent shadow register jitter
        int step_size = 20 / delay_ms; 
        if (step_size < 1) step_size = 1;
        
        while (current_servo_angle != target_angle) {
            if (target_angle > current_servo_angle) {
                current_servo_angle += step_size;
                if (current_servo_angle > target_angle) current_servo_angle = target_angle;
            } else {
                current_servo_angle -= step_size;
                if (current_servo_angle < target_angle) current_servo_angle = target_angle;
            }
            mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle));
            vTaskDelay(pdMS_TO_TICKS(20)); // Yield exactly 1 PWM frame
        }
        
        // --- NEW: SOFTWARE LIMP MODE ---
        if (target_angle == 0) {
            vTaskDelay(pdMS_TO_TICKS(150)); // Allow mechanical latch/springs to settle
            mcpwm_comparator_set_compare_value(comparator, 0); // Drop duty cycle to 0
            ESP_LOGI(TAG, "Servo returned to 0-Duty Limp Mode");
            if (servo_pm_lock) esp_pm_lock_release(servo_pm_lock); // Safe to sleep again
        }
    } else {
        current_servo_angle = target_angle;
    }
}""",
        """static void servo_move_smooth(int target_angle, int delay_ms) {
    if (target_angle < 0) target_angle = 0;
    if (target_angle > 180) target_angle = 180;

    if (servo_mutex) xSemaphoreTake(servo_mutex, portMAX_DELAY);

    // Only acquire lock if we are actively moving away from 0, and don't already have it
    if (target_angle > 0 && !pm_lock_acquired) {
        if (servo_pm_lock) esp_pm_lock_acquire(servo_pm_lock);
        pm_lock_acquired = true;
    }

    if (comparator != NULL) {
        if (current_servo_angle == target_angle) {
            // Failsafe resync pulse: ensures physical hardware matches software state
            mcpwm_comparator_set_compare_value(comparator, angle_to_compare(target_angle));
            vTaskDelay(pdMS_TO_TICKS(50));
        } else {
            int step_size = 20 / delay_ms; 
            if (step_size < 1) step_size = 1;
            
            while (current_servo_angle != target_angle) {
                if (target_angle > current_servo_angle) {
                    current_servo_angle += step_size;
                    if (current_servo_angle > target_angle) current_servo_angle = target_angle;
                } else {
                    current_servo_angle -= step_size;
                    if (current_servo_angle < target_angle) current_servo_angle = target_angle;
                }
                mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle));
                vTaskDelay(pdMS_TO_TICKS(20)); 
            }
        }
        
        // --- NEW: SOFTWARE LIMP MODE ---
        if (target_angle == 0) {
            vTaskDelay(pdMS_TO_TICKS(150)); // Allow mechanical latch/springs to settle
            mcpwm_comparator_set_compare_value(comparator, 0); // Drop duty cycle to 0
            ESP_LOGI(TAG, "Servo returned to 0-Duty Limp Mode");
            
            // Strictly release lock ONLY if we actually hold it to prevent FreeRTOS panics
            if (pm_lock_acquired) {
                if (servo_pm_lock) esp_pm_lock_release(servo_pm_lock);
                pm_lock_acquired = false;
            }
        }
    } else {
        current_servo_angle = target_angle;
    }
    
    if (servo_mutex) xSemaphoreGive(servo_mutex);
}"""
    ),
    
    # E. Remove lower static declaration of is_unlocking to prevent shadow variable warnings
    (
        "static bool is_unlocking = false;\n\nstatic void unlock_sequence_task(void *pvParameters) {",
        "// static bool is_unlocking = false; // Moved to global scope\n\nstatic void unlock_sequence_task(void *pvParameters) {"
    ),

    # F. Add abort hook to manual override
    (
        """void servo_set_manual(int target_angle) {
    // 3ms per degree gives a 5x faster sweep for active ML unlocks for manual adjustments
    servo_move_smooth(target_angle, 3);
}""",
        """void servo_set_manual(int target_angle) {
    if (target_angle == 0) {
        is_unlocking = false; // Abort pending automatic unlock sequence
    }
    // 3ms per degree gives a 5x faster sweep for active ML unlocks for manual adjustments
    servo_move_smooth(target_angle, 3);
}"""
    ),

    # G. Replace blocking wait with a chunked wait loop that allows early aborts
    (
        """    // Non-blocking wait in the background
    vTaskDelay(pdMS_TO_TICKS(10000));
    
    ESP_LOGI(TAG, "Unlock Sequence Concluding: Sweeping CCW (0 deg)");
    servo_set_manual(0); // MUST hit 0 to trigger Limp Mode & release PM Lock
    
    is_unlocking = false;
    vTaskDelete(NULL); // Task deletes itself to free memory""",
        """    // Chunked wait loop allows early abort if the user manually taps LOCK
    for (int i = 0; i < 100; i++) {
        if (!is_unlocking) break; // Early abort triggered by UI
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    
    if (is_unlocking) {
        ESP_LOGI(TAG, "Unlock Sequence Concluding: Sweeping CCW (0 deg)");
        servo_set_manual(0); // MUST hit 0 to trigger Limp Mode & release PM Lock
        is_unlocking = false;
    }
    vTaskDelete(NULL); // Task deletes itself to free memory"""
    )
])

# 2. Update touch_manager.c
patch_file("main/hardware/touch_manager.c", [
    (
        "uint16_t x = raw_x;",
        "uint16_t x = 320 - raw_x;"
    )
])

print("Patching sequence complete.")
if __name__ == "__main__":
    pass