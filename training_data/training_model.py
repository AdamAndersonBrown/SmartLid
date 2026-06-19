import os
import json
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
from sklearn.model_selection import train_test_split

# --- 1. CONFIGURATION ---
DATA_DIR = "./training_data"
WINDOW_SIZE = 20  # 20 samples = 1 second at 50ms polling (20Hz)
FEATURES = ['ax', 'ay', 'az', 'gx', 'gy', 'gz']
NUM_CLASSES = 3

print("--- SmartLid 1D CNN Training Pipeline ---")

# --- 2. DATA LOADING & WINDOWING ---
def load_and_window_data(directory, window_size):
    X_all, y_all = [], []
    
    for filename in os.listdir(directory):
        if not filename.endswith(".jsonl"): continue
        
        filepath = os.path.join(directory, filename)
        data = []
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    data.append(json.loads(line.strip()))
                except:
                    pass
                    
        if len(data) == 0: continue
        df = pd.DataFrame(data).sort_values('ts')
        
        # Extract features and tags
        features_array = df[FEATURES].values
        tags_array = df['tag'].values
        
        # Slide a window over the data
        for i in range(len(df) - window_size):
            window = features_array[i : i + window_size]
            # Use the most common tag in this window as the label
            tags_in_window = tags_array[i : i + window_size]
            majority_tag = np.bincount(tags_in_window).argmax()
            
            X_all.append(window)
            y_all.append(majority_tag)
            
    return np.array(X_all), np.array(y_all)

print("Loading and preprocessing JSONL data...")
X, y = load_and_window_data(DATA_DIR, WINDOW_SIZE)

if len(X) == 0:
    print("ERROR: No data found! Ensure your .jsonl files are in ./training_data")
    exit()

# Normalize the data (Neural networks prefer small numbers, e.g., -1.0 to 1.0)
# MPU6886 raw 16-bit values range roughly from -32768 to 32767
X = X / 32768.0 

# Split into Training and Validation sets
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
print(f"Data ready. Training shapes: X={X_train.shape}, y={y_train.shape}")

# --- 3. BUILD THE 1D CNN MODEL ---
model = models.Sequential([
    # The Convolutional layer slides over the 20-step window looking for patterns
    layers.Conv1D(filters=16, kernel_size=3, activation='relu', input_shape=(WINDOW_SIZE, len(FEATURES))),
    layers.MaxPooling1D(pool_size=2),
    layers.Conv1D(filters=32, kernel_size=3, activation='relu'),
    layers.MaxPooling1D(pool_size=2),
    layers.Flatten(),
    # The Dense layer evaluates the patterns and makes a decision
    layers.Dense(32, activation='relu'),
    layers.Dropout(0.2), # Prevent overfitting to your specific trashcan
    layers.Dense(NUM_CLASSES, activation='softmax') # Outputs % confidence for each class
])

model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])

# --- 4. TRAIN THE MODEL ---
print("\nStarting Training...")
history = model.fit(X_train, y_train, epochs=25, validation_data=(X_val, y_val), batch_size=32)

# --- 5. CONVERT TO TENSORFLOW LITE ---
print("\nConverting model to TFLite for ESP32 deployment...")
converter = tf.lite.TFLiteConverter.from_keras_model(model)
# converter.optimizations = [tf.lite.Optimize.DEFAULT] # Disabled to force pure Float32 math for ESP32 # Quantize to save memory
tflite_model = converter.convert()

with open("smartlid_model.tflite", "wb") as f:
    f.write(tflite_model)

# --- 6. EXPORT TO C HEADER (HEX DUMP) ---
# Microcontrollers can't read .tflite files from a hard drive, they need it compiled into the flash memory.
print("Generating C Header file (model_data.h)...")
with open("model_data.h", "w") as f:
    f.write("// Automatically generated TFLite Model\n")
    f.write("#ifndef MODEL_DATA_H\n#define MODEL_DATA_H\n\n")
    f.write(f"const unsigned int smartlid_model_tflite_len = {len(tflite_model)};\n")
    f.write("const unsigned char smartlid_model_tflite[] = {\n")
    
    hex_array = [f"0x{b:02x}" for b in tflite_model]
    for i in range(0, len(hex_array), 12):
        f.write("    " + ", ".join(hex_array[i:i+12]) + ",\n")
        
    f.write("};\n\n#endif\n")

print("\nSUCCESS! Pipeline complete.")
print("The 'model_data.h' file is ready to be dropped into your ESP-IDF project.")