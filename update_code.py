# update_code.py
import os

def apply_surgical_patch(filepath, patches):
    if not os.path.exists(filepath):
        print(f"[!] Error: Cannot find {filepath}")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    for old_str, new_str in patches:
        if old_str in content:
            content = content.replace(old_str, new_str)
            print(f"[*] Patched node in {filepath}")
        else:
            print(f"[!] Warning: Target string not found in {filepath}. It may have already been patched.")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    print("Initiating Pre-Flight Check...")
    
    # --- ML TRAINING SCRIPT PATCHES ---
    ml_script_name = "training_model.py" 
    train_patches = [
        # Secure the burst splitter against negative time jumps (out-of-order appends)
        (
            "if pt['ts'] - raw_data[i-1]['ts'] > 1000000:",
            "if abs(pt['ts'] - raw_data[i-1]['ts']) > 1000000:"
        )
    ]
    
    print("Executing ML Pipeline Patches...")
    apply_surgical_patch(ml_script_name, train_patches)
    print("Patch sequence complete.")