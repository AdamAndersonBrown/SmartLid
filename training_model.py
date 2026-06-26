import os
import re
import json
import sys
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight

# 1. ARCHITECTURAL SYNC: Point directly to the dashboard directory
DASHBOARD_DIR = r"C:\Workbench\smart_trash_dashboard"
sys.path.append(DASHBOARD_DIR)
import imu_filter

DATA_DIR = os.path.join(DASHBOARD_DIR, "training_data")
WINDOW_SIZE = 100 
FEATURES = ['qw', 'qx', 'qy', 'qz', 'c_ax', 'c_ay', 'c_az', 'vx', 'vy', 'vz']
NUM_CLASSES = 3

print("--- SmartLid 1D CNN Training Pipeline (V5: Mahony Quaternions & Leaky Velocity) ---")

def load_and_window_data(directory, window_size):
    X_all, y_all = [], []
    if not os.path.exists(directory):
        print(f"Directory {directory} not found.")
        return np.array(X_all), np.array(y_all)

    for filename in os.listdir(directory):
        if not filename.endswith(".jsonl"): continue
        match = re.search(r'class_(\d+)', filename)
        if not match: continue
        true_tag = int(match.group(1))
        
        filepath = os.path.join(directory, filename)
        data = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    parsed = json.loads(line.strip())
                    pts = parsed if isinstance(parsed, list) else [parsed]
                    for pt in pts:
                        if not pt.get('ignore', False):
                            data.append(pt)
                except: pass
                
        if not data: continue
        
        # 2. RUNTIME SIMULATION: Pass raw data through Mahony Filter
        old_cwd = os.getcwd()
        os.chdir(DASHBOARD_DIR) # Shift CWD so imu_calibration.json loads correctly
        engine = imu_filter.IMUFusionEngine(sample_rate=50.0)
        motion_path = engine.process_window(data)
        os.chdir(old_cwd)
        
        df = pd.DataFrame(motion_path).sort_values('ts')
        features_array = df[FEATURES].values
        
        # 3. NORMALIZATION (Must precisely match C++ deployment)
        # qw, qx, qy, qz are inherently -1 to 1.
        features_array[:, 4:7] /= 20.0 # Accel (m/s^2) roughly bound by +/- 20
        features_array[:, 7:10] /= 2.0 # Velocity (m/s) roughly bound by +/- 2
        
        step_size = window_size // 2
        for i in range(0, len(df) - window_size, step_size):
            window = features_array[i : i + window_size]
            
            # Kinematic Gate: Use Dynamic Earth Acceleration instead of raw gyro
            if true_tag != 0:
                dyn_accel_mag = np.sqrt(window[:, 4]**2 + window[:, 5]**2 + window[:, 6]**2)
                if np.max(dyn_accel_mag) < 0.1: # 0.1 normalized = ~2 m/s^2 force
                    continue
            
            X_all.append(window)
            y_all.append(true_tag)
            
    return np.array(X_all), np.array(y_all)

X, y = load_and_window_data(DATA_DIR, WINDOW_SIZE)
if len(X) == 0: exit("ERROR: No valid data found!")

X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
class_weight_dict = dict(enumerate(compute_class_weight('balanced', classes=np.unique(y_train), y=y_train)))

model = models.Sequential([
    layers.Conv1D(filters=16, kernel_size=3, activation='relu', input_shape=(WINDOW_SIZE, len(FEATURES))),
    layers.MaxPooling1D(pool_size=2),
    layers.Conv1D(filters=32, kernel_size=3, activation='relu'),
    layers.MaxPooling1D(pool_size=2),
    layers.Flatten(),
    layers.Dense(32, activation='relu'),
    layers.Dropout(0.3),
    layers.Dense(NUM_CLASSES, activation='softmax') 
])

model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
model.fit(X_train, y_train, epochs=25, validation_data=(X_val, y_val), batch_size=32, class_weight=class_weight_dict)

converter = tf.lite.TFLiteConverter.from_keras_model(model)
tflite_model = converter.convert()

export_path = "model_data.h"
with open(export_path, "w") as f:
    f.write("// Automatically generated TFLite Model (10-Channel Kinematic)\n#ifndef MODEL_DATA_H\n#define MODEL_DATA_H\n\n")
    f.write(f"const unsigned int smartlid_model_tflite_len = {len(tflite_model)};\n")
    f.write("const unsigned char smartlid_model_tflite[] = {\n")
    hex_array = [f"0x{b:02x}" for b in tflite_model]
    for i in range(0, len(hex_array), 12): f.write("    " + ", ".join(hex_array[i:i+12]) + ",\n")
    f.write("};\n\n#endif\n")
print("\nSUCCESS! Pipeline complete.")
