# update_code.py
import os

disp_h = "main/display_manager.h"
disp_c = "main/display_manager.c"
main_c = "main/app_main.c"

print("Injecting Real-Time Wi-Fi RSSI Display...")

# 1. Update Display Manager Header
if os.path.exists(disp_h):
    with open(disp_h, "r") as f:
        content = f.read()
    
    if "display_manager_draw_wifi" not in content:
        content = content.replace('void display_manager_draw_battery', 'void display_manager_draw_wifi(int rssi, bool connected);\nvoid display_manager_draw_battery')
        with open(disp_h, "w") as f:
            f.write(content)
        print("-> display_manager.h patched.")

# 2. Add Wi-Fi Rendering to Display Manager Source
if os.path.exists(disp_c):
    with open(disp_c, "r") as f:
        content = f.read()

    new_wifi_func = """
void display_manager_draw_wifi(int rssi, bool connected) {
    if (!panel_handle) return;
    static uint16_t wifi_buf[30 * 25]; // 30x25 pixel static block
    
    for(int i=0; i<30*25; i++) wifi_buf[i] = last_bg_color;

    if (connected) {
        int bars = 0;
        // Standard RSSI to Bar mapping
        if (rssi > -60) bars = 4;
        else if (rssi > -70) bars = 3;
        else if (rssi > -80) bars = 2;
        else if (rssi > -90) bars = 1;

        // Draw 4 vertical bars of increasing height
        for (int b = 0; b < 4; b++) {
            uint16_t color = (b < bars) ? COLOR_WHITE : 0x8410; // Grey if inactive
            int bx = 2 + (b * 6);  // X offset
            int bh = 6 + (b * 4);  // Bar height
            int by = 22 - bh;      // Y offset (anchored to bottom)
            
            for (int x = bx; x < bx + 4; x++) {
                for (int y = by; y < 22; y++) {
                    wifi_buf[y * 30 + x] = color;
                }
            }
        }
    } else {
        // Draw a thick Red X if disconnected
        for(int i=5; i<20; i++) {
            for(int w=0; w<3; w++) {
                wifi_buf[(i) * 30 + (i + w)] = COLOR_RED;
                wifi_buf[(i) * 30 + (24 - i + w)] = COLOR_RED;
            }
        }
    }
    
    // Draw in the top-left corner
    esp_lcd_panel_draw_bitmap(panel_handle, 5, 5, 35, 30, wifi_buf);
}
"""
    if "display_manager_draw_wifi" not in content:
        content += new_wifi_func
        with open(disp_c, "w") as f:
            f.write(content)
        print("-> display_manager.c patched (Wi-Fi graphics added).")

# 3. Add Wi-Fi Polling to Main Loop
if os.path.exists(main_c):
    with open(main_c, "r") as f:
        content = f.read()

    target_loop = "last_charge = charging;\n        }"
    fix_loop = """last_charge = charging;
        }

        // --- WIFI RSSI UPDATE LOGIC ---
        wifi_ap_record_t ap_info;
        bool wifi_conn = (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK);
        int current_rssi = wifi_conn ? ap_info.rssi : 0;
        
        static int last_rssi = 1; // Force initial draw
        static bool last_conn = false;
        
        // Update the UI if the signal strength changes by more than 2 dBm or connection state flips
        if (abs(current_rssi - last_rssi) > 2 || wifi_conn != last_conn) {
            display_manager_draw_wifi(current_rssi, wifi_conn);
            last_rssi = current_rssi;
            last_conn = wifi_conn;
        }"""

    if "WIFI RSSI UPDATE LOGIC" not in content and target_loop in content:
        content = content.replace(target_loop, fix_loop)
        with open(main_c, "w") as f:
            f.write(content)
        print("-> app_main.c patched (Wi-Fi polling injected).")

print("Surgical patch complete.")