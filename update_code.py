# update_code.py
import os
import re

print("Executing Surgical Patch: Shifting UDP from Broadcast to Hardware-ACK Unicast...")

target_file = "main/hardware/imu_telemetry_task.c"

if os.path.exists(target_file):
    print("\n[!] Please open a new PowerShell window and run 'ipconfig'.")
    print("[!] Look for the 'IPv4 Address' under your active Wi-Fi adapter.")
    pc_ip = input("\n[?] Enter your Windows PC's exact IPv4 address (e.g., 192.168.86.X): ").strip()
    
    # Simple validation to ensure it looks like an IP address
    if len(pc_ip.split('.')) == 4:
        with open(target_file, "r") as file:
            content = file.read()
            
        # Target the inet_addr assignment specifically, replacing whatever IP is currently there
        updated_content = re.sub(
            r'inet_addr\("[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}"\)',
            f'inet_addr("{pc_ip}")',
            content
        )
        
        with open(target_file, "w") as file:
            file.write(updated_content)
            
        print(f"-> SUCCESS: Targeted Unicast IP ({pc_ip}) injected into {target_file}.")
        print("-> NOTE: If your PC restarts tomorrow and gets a new IP from the router, you will need to update this again.")
    else:
        print("-> ABORT: Invalid IP address format entered.")
else:
    print(f"-> ERROR: Could not locate {target_file}.")