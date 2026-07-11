import os

def apply_patch():
    # --- Python Patch ---
    py_file = "training_model.py"
    if os.path.exists(py_file):
        with open(py_file, "r", encoding="utf-8") as f:
            py_content = f.read()
        
        # 1. Replace absolute quaternions with the Yaw-Invariant Gravity Vector
        py_content = py_content.replace(
            "'features': [q0, q1, q2, q3,", 
            "'features': [vx, vy, vz,"
        )
        
        # 2. Update shapes and indices for the 9-feature matrix
        py_content = py_content.replace("(WINDOW_SIZE, 10)", "(WINDOW_SIZE, 9)")
        py_content = py_content.replace("first_frame[7:10] = 0.0", "first_frame[6:9] = 0.0")
        py_content = py_content.replace("last_frame[7:10] = 0.0", "last_frame[6:9] = 0.0")
        py_content = py_content.replace(
            "window[:, 7]**2 + window[:, 8]**2 + window[:, 9]**2", 
            "window[:, 6]**2 + window[:, 7]**2 + window[:, 8]**2"
        )
        
        with open(py_file, "w", encoding="utf-8") as f:
            f.write(py_content)
        print("Patched training_model.py (9-Feature Yaw-Invariant Spatial Array)")
    else:
        print(f"Error: {py_file} not found.")

    # --- C++ Patch ---
    cpp_file = os.path.join("main", "ml", "inference_manager.cpp")
    if os.path.exists(cpp_file):
        with open(cpp_file, "r", encoding="utf-8") as f:
            cpp_content = f.read()

        cpp_content = cpp_content.replace("#define ML_FEATURES 10", "#define ML_FEATURES 9")
        
        old_buffer_push = """    // 100x10 Spatial Fusion Architecture
    ring_buffer[WINDOW_SIZE - 1][0] = q[0]; 
    ring_buffer[WINDOW_SIZE - 1][1] = q[1];
    ring_buffer[WINDOW_SIZE - 1][2] = q[2];
    ring_buffer[WINDOW_SIZE - 1][3] = q[3];
    ring_buffer[WINDOW_SIZE - 1][4] = a_body[0] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][5] = a_body[1] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][6] = a_body[2] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][7] = velocity[0] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][8] = velocity[1] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][9] = velocity[2] / 2.0f;"""
        
        new_buffer_push = """    // 100x9 Yaw-Invariant Spatial Architecture
    float vx = 2.0f * (q[1] * q[3] - q[0] * q[2]);
    float vy = 2.0f * (q[0] * q[1] + q[2] * q[3]);
    float vz = q[0] * q[0] - q[1] * q[1] - q[2] * q[2] + q[3] * q[3];

    ring_buffer[WINDOW_SIZE - 1][0] = vx; 
    ring_buffer[WINDOW_SIZE - 1][1] = vy;
    ring_buffer[WINDOW_SIZE - 1][2] = vz;
    ring_buffer[WINDOW_SIZE - 1][3] = a_body[0] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][4] = a_body[1] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][5] = a_body[2] / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][6] = velocity[0] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][7] = velocity[1] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][8] = velocity[2] / 2.0f;"""
        
        if old_buffer_push in cpp_content:
            cpp_content = cpp_content.replace(old_buffer_push, new_buffer_push)
            with open(cpp_file, "w", encoding="utf-8") as f:
                f.write(cpp_content)
            print("Patched inference_manager.cpp (9-Feature Yaw-Invariant Spatial Array)")
        else:
            print("Error: Could not locate the 10-feature ring_buffer block in C++ file.")
    else:
        print(f"Error: {cpp_file} not found.")

if __name__ == "__main__":
    apply_patch()