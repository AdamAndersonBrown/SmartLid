import os
import json
import re

DASHBOARD_DIR = r"C:\Workbench\smart_trash_dashboard"
DATA_DIR = os.path.join(DASHBOARD_DIR, "training_data")
WINDOW_SIZE = 100 

def deep_audit_dataset(directory):
    print("--- Detailed Class 2 (Lift) X-Ray Auditor ---")
    if not os.path.exists(directory):
        print(f"CRITICAL: Directory not found: {directory}")
        return

    total_files = 0
    total_valid = 0
    
    for filename in os.listdir(directory):
        if not filename.endswith(".jsonl"): 
            continue
            
        # Broaden search: Catch anything with class_2 OR lift in the name
        match = re.search(r'class_(\d+)', filename)
        is_class_2 = match and int(match.group(1)) == 2
        is_lift = "lift" in filename.lower()
        
        if not (is_class_2 or is_lift):
            continue
            
        print(f"\n[ANALYZING FILE: {filename}]")
        total_files += 1
        
        filepath = os.path.join(directory, filename)
        raw_data = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    parsed = json.loads(line.strip())
                    pts = parsed if isinstance(parsed, list) else [parsed]
                    raw_data.extend(pts)
                except: 
                    pass
        
        if not raw_data:
            print("  -> ERROR: File is empty or contains invalid JSON.")
            continue

        # 1. Pipeline Replication: Split by 1s gaps
        initial_bursts = []
        current = []
        for i, pt in enumerate(raw_data):
            if i == 0:
                current.append(pt)
                continue
            
            # 1,000,000 us = 1 second gap
            if pt['ts'] - raw_data[i-1]['ts'] > 1000000:
                initial_bursts.append(current)
                current = []
            current.append(pt)
            
        if current:
            initial_bursts.append(current)

        print(f"  -> Found {len(initial_bursts)} sequence(s) separated by >1s gaps.")
        
        file_valid = 0
        for b_idx, burst in enumerate(initial_bursts):
            total_points = len(burst)
            duration_sec = (burst[-1]['ts'] - burst[0]['ts']) / 1000000.0
            
            # Check Pipeline Rule 1: Must be > 50 points
            if total_points <= 50:
                print(f"    [X] Sequence {b_idx}: REJECTED (Only {total_points} pts. Fails pipeline >50 pt cutoff)")
                continue
                
            ignored_count = sum(1 for p in burst if p.get('ignore', False))
            clean_count = total_points - ignored_count
            
            # Check Pipeline Rule 2: Must have >= WINDOW_SIZE (100) clean points
            if clean_count >= WINDOW_SIZE:
                print(f"    [+] Sequence {b_idx}: VALID   ({duration_sec:.2f}s | Clean: {clean_count} | Ignored: {ignored_count})")
                file_valid += 1
                total_valid += 1
            else:
                reason = f"Clean points ({clean_count}) < WINDOW_SIZE ({WINDOW_SIZE})"
                print(f"    [X] Sequence {b_idx}: REJECTED ({duration_sec:.2f}s | {reason} | Ignored: {ignored_count})")

        print(f"  -> Summary: {file_valid} valid events extracted from {filename}.")

    print("\n" + "="*45)
    print(f"Total Files Analyzed: {total_files}")
    print(f"Total Valid Lift Events Ready for Model: {total_valid}")
    print("="*45)

if __name__ == "__main__":
    deep_audit_dataset(DATA_DIR)