import os
import sys
import json
import numpy as np

# Connect to the dashboard directory
DASHBOARD_DIR = r"C:\Workbench\smart_trash_dashboard"
sys.path.append(DASHBOARD_DIR)
import imu_filter

def apply_autolabel():
    lift_file = os.path.join(DASHBOARD_DIR, "training_data", "class_2_lift.jsonl")
    if not os.path.exists(lift_file): 
        print(f"Error: Could not find {lift_file}")
        return

    # 1. Load data
    raw_data = []
    with open(lift_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                parsed = json.loads(line.strip())
                pts = parsed if isinstance(parsed, list) else [parsed]
                raw_data.extend(pts)
            except: pass

    # 2. Split into distinct temporal bursts
    bursts = []
    current_burst = []
    for i, pt in enumerate(raw_data):
        if i == 0:
            current_burst.append(pt)
            continue
        if pt['ts'] - raw_data[i-1]['ts'] > 1000000: 
            if len(current_burst) > 10: bursts.append(current_burst)
            current_burst = []
        current_burst.append(pt)
    if len(current_burst) > 10: bursts.append(current_burst)

    old_cwd = os.getcwd()
    os.chdir(DASHBOARD_DIR)

    changes_made = 0

    for burst in bursts:
        engine = imu_filter.IMUFusionEngine(sample_rate=50.0)
        motion_path = engine.process_window(burst)
        
        # Phase 1: Identify core Lift events
        core_lift = [False] * len(motion_path)
        for i, pt in enumerate(motion_path):
            if pt['vz'] > 0.06 or (pt['vz'] > -0.05 and (abs(pt['c_gy']) > 40.0 or abs(pt['c_gx']) > 40.0)):
                core_lift[i] = True

        # Phase 2: Pad 500ms
        keep_flags = [False] * len(motion_path)
        for i, is_lift in enumerate(core_lift):
            if is_lift:
                for j in range(max(0, i - 25), min(len(motion_path), i + 25)):
                    keep_flags[j] = True

        # Phase 3: Carve out Set-Downs
        for i, pt in enumerate(motion_path):
            if pt['vz'] < -0.15:
                for j in range(max(0, i - 10), min(len(motion_path), i + 15)):
                    keep_flags[j] = False

        # Phase 4: Apply labels to the original dictionaries
        for i, pt in enumerate(motion_path):
            original_pt = burst[i]
            current_ignore = original_pt.get('ignore', False)
            should_ignore = not keep_flags[i]
            
            if should_ignore and not current_ignore:
                original_pt['ignore'] = True
                changes_made += 1

    os.chdir(old_cwd)

    # 3. Rewrite the JSONL file
    with open(lift_file, 'w', encoding='utf-8') as f:
        for pt in raw_data:
            f.write(json.dumps(pt) + '\n')

    print(f"SUCCESS: Permanently applied {changes_made} new 'ignore: true' labels to class_2_lift.jsonl")

if __name__ == "__main__":
    apply_autolabel()