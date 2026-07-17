import os

servo_path = os.path.join("main", "hardware", "servo_manager.c")
imu_path = os.path.join("main", "hardware", "imu_telemetry_task.c")

try:
    # --- 1. UPDATE SERVO HOLD TIME (10s -> 3s) ---
    with open(servo_path, "r") as f:
        servo_content = f.read()

    servo_content = servo_content.replace('Waiting 10s... (UI overrides will take immediate precedence)', 'Waiting 3s... (UI overrides will take immediate precedence)')
    servo_content = servo_content.replace('for(int i = 0; i < 100; i++)', 'for(int i = 0; i < 30; i++)')
    servo_content = servo_content.replace('10s Complete. Auto-closing.', '3s Complete. Auto-closing.')

    with open(servo_path, "w") as f:
        f.write(servo_content)
    
    print("SUCCESS: Servo hold time reduced from 10 seconds to 3 seconds.")

    # --- 2. UPDATE IMU ML WAKE THRESHOLDS (Pure Accelerometer Baseline) ---
    with open(imu_path, "r") as f:
        imu_content = f.read()

    old_imu_logic = """            if (delta > 6000) { 
                display_manager_wake(); 
                ml_active_frames = 150; // Wake ML for 3 seconds
            }"""

    new_imu_logic = """            // --- AI WAKE LOGIC (PURE ACCELEROMETER) ---
            static int32_t base_ax = 0, base_ay = 0, base_az = 0;
            if (base_ax == 0 && base_ay == 0 && base_az == 0) { 
                base_ax = acc_x; base_ay = acc_y; base_az = acc_z; 
            }
            
            // Calculate absolute shift from the resting baseline (catches slow rotations)
            int32_t spatial_shift = abs(acc_x - base_ax) + abs(acc_y - base_ay) + abs(acc_z - base_az);
            
            // WAKE MACHINE LEARNING: ~10 degrees of smooth rotation OR a sharp frame-to-frame jerk
            if (spatial_shift > 2000 || delta > 1500) { 
                ml_active_frames = 150; 
            }
            
            // WAKE SCREEN: High threshold for physical bumps to save battery
            if (delta > 6000) { 
                display_manager_wake(); 
            }
            
            // Slowly drag the baseline toward current state (Low-pass filter, ~5 second convergence)
            // We only drag the baseline if ML is asleep, so it doesn't chase the lift!
            if (ml_active_frames == 0) {
                base_ax = (base_ax * 255 + acc_x) / 256;
                base_ay = (base_ay * 255 + acc_y) / 256;
                base_az = (base_az * 255 + acc_z) / 256;
            }
            // ------------------------------------------"""

    if old_imu_logic in imu_content:
        imu_content = imu_content.replace(old_imu_logic, new_imu_logic)
        with open(imu_path, "w") as f:
            f.write(imu_content)
        print("SUCCESS: Accel-only spatial baseline applied. AI will now detect smooth lifts stealthily.")
    else:
        print("NOTICE: IMU wake thresholds already updated or code not found.")

except Exception as e:
    print(f"ERROR: {e}")