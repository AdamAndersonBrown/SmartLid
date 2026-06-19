# fix_hybrid.py
import os

train_script = "training_data/training_model.py"

print("Disabling Hybrid Quantization in the Training Pipeline...")

if os.path.exists(train_script):
    with open(train_script, "r") as f:
        content = f.read()

    target = "converter.optimizations = [tf.lite.Optimize.DEFAULT]"
    fix = "# converter.optimizations = [tf.lite.Optimize.DEFAULT] # Disabled to force pure Float32 math for ESP32"

    if target in content:
        content = content.replace(target, fix)
        with open(train_script, "w") as f:
            f.write(content)
        print("-> training_model.py patched. Ready to re-train.")
    else:
        print("-> Hybrid compression is already disabled or file not found.")
else:
    print(f"-> ERROR: Could not find {train_script}")