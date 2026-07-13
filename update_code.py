# update_code.py
import os

def patch_file():
    filepath = os.path.join("main", "hardware", "servo_manager.c")
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        return

    with open(filepath, "r") as file:
        content = file.read()

    # Accommodating both the original RTOS delay and the ROM delay patch
    old_block_rom = """    if (comparator != NULL) {
        int step = (target_angle > current_servo_angle) ? 1 : -1;
        while (current_servo_angle != target_angle) {
            current_servo_angle += step;
            mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle));
            esp_rom_delay_us(delay_ms * 1000); // Hardware block to maximize torque
        }"""

    old_block_rtos = """    if (comparator != NULL) {
        int step = (target_angle > current_servo_angle) ? 1 : -1;
        while (current_servo_angle != target_angle) {
            current_servo_angle += step;
            mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle));
            vTaskDelay(pdMS_TO_TICKS(delay_ms)); // Pause between physical 1-degree steps
        }"""

    new_block = """    if (comparator != NULL) {
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
        }"""

    if old_block_rom in content:
        updated = content.replace(old_block_rom, new_block)
        print("Successfully synchronized PWM timing (overwriting ROM delay).")
    elif old_block_rtos in content:
        updated = content.replace(old_block_rtos, new_block)
        print("Successfully synchronized PWM timing (overwriting RTOS delay).")
    elif new_block in content:
        print("Patch already applied.")
        return
    else:
        print("Error: Target code string not found. Whitespace mismatch?")
        return

    with open(filepath, "w") as file:
        file.write(updated)

if __name__ == "__main__":
    patch_file()