# update_code.py
import os
import re

main_path = "main/app_main.c"

print("Deploying foolproof QR code trigger...")

if os.path.exists(main_path):
    with open(main_path, "r") as f:
        content = f.read()

    # 1. Add explicit external function declaration
    if "extern void wifi_prov_print_qr" not in content:
        content = '#include "esp_wifi.h"\nextern void wifi_prov_print_qr(const char *name, const char *username, const char *pop, const char *transport);\n' + content

    # 2. Inject brute force trigger right before the "Waiting..." log
    pattern = r'(ESP_LOGI\([^,]+,\s*"Waiting for WiFi connection\.\.\."\);)'
    
    injection = r"""
    // --- FOOLPROOF QR TRIGGER ---
    uint8_t fw_mac[6];
    esp_wifi_get_mac(WIFI_IF_STA, fw_mac);
    char fw_name[15];
    snprintf(fw_name, sizeof(fw_name), "IMU_%02X%02X%02X", fw_mac[3], fw_mac[4], fw_mac[5]);
    wifi_prov_print_qr(fw_name, "wifiprov", "abcd1234", "softap");
    // ----------------------------
    \1"""

    if "FOOLPROOF QR TRIGGER" not in content:
        new_content = re.sub(pattern, injection, content)
        if new_content != content:
            with open(main_path, "w") as f:
                f.write(new_content)
            print("-> app_main.c patched (Foolproof QR trigger injected).")
        else:
            print("-> ERROR: Could not find 'Waiting for WiFi connection...' log in app_main.c.")
    else:
        print("-> Foolproof trigger already present.")
else:
    print(f"-> ERROR: {main_path} not found.")

print("Surgical patch complete.")