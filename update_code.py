import os
import re

TARGET_FILE = os.path.join("main", "hardware", "display_manager.c")

def patch_file():
    if not os.path.exists(TARGET_FILE):
        print(f"CRITICAL: {TARGET_FILE} not found in the current directory.")
        return

    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    changed = False

    # --- 0. Include Required Header ---
    if "esp_wifi.h" not in content:
        content = content.replace(
            '#include "esp_timer.h"',
            '#include "esp_timer.h"\n#include "esp_wifi.h"'
        )
        changed = True

    # --- 1. Fix GRAM Persistence on Reboot ---
    target_init = "    // Force the background explicitly black to fix the backlight optical illusion\n    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(0x000000), 0);"
    safe_init = """    // Force the background explicitly black to fix the backlight optical illusion
    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(0x000000), 0);
    
    // SURGICAL FIX: Force LVGL to paint a physical black rectangle over the entire screen.
    // This prevents old ILI9341 GRAM contents (like the QR code) from surviving a software reboot.
    lv_obj_t * force_bg = lv_obj_create(lv_scr_act());
    lv_obj_set_size(force_bg, LCD_WIDTH, LCD_HEIGHT);
    lv_obj_set_style_bg_color(force_bg, lv_color_hex(0x000000), 0);
    lv_obj_set_style_border_width(force_bg, 0, 0);
    lv_obj_set_style_radius(force_bg, 0, 0);
    lv_obj_clear_flag(force_bg, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_center(force_bg);"""
    
    if target_init in content and "force_bg" not in content:
        content = content.replace(target_init, safe_init)
        changed = True

    # --- 2. Fix Session Persistence (Decouple from ui_wifi) ---
    target_poll_regex = r'(\s*if \(lbl_right\) \{\s*lv_label_set_text\(lbl_right, last_wifi \? "wifi off" : "wifi on"\);\s*\})\s*// SURGICAL FIX: Dismiss the QR code automatically when provisioned/connected\s*if \(ui_wifi && qr_bg != NULL\) \{\s*lv_obj_del\(qr_bg\);\s*qr_bg = NULL;\s*\}\s*\}'
    
    safe_poll = r"""\1
    }

    // SURGICAL FIX: Dismiss the QR code continuously by checking actual WiFi PHY mode,
    // completely decoupled from the UI state changes.
    if (qr_bg != NULL) {
        wifi_mode_t mode;
        if (esp_wifi_get_mode(&mode) == ESP_OK) {
            // If SoftAP is disabled, provisioning is over.
            if (mode != WIFI_MODE_APSTA && mode != WIFI_MODE_AP) {
                lv_obj_del(qr_bg);
                qr_bg = NULL;
            }
        } else {
            // If wifi is uninitialized/stopped, we shouldn't show the QR code.
            lv_obj_del(qr_bg);
            qr_bg = NULL;
        }
    }"""
    
    if re.search(target_poll_regex, content):
        content = re.sub(target_poll_regex, safe_poll, content)
        changed = True
    else:
        # Fallback if regex fails
        fallback_target = """        // SURGICAL FIX: Dismiss the QR code automatically when provisioned/connected
        if (ui_wifi && qr_bg != NULL) {
            lv_obj_del(qr_bg);
            qr_bg = NULL;
        }
    }"""
        fallback_safe = """    }
        
    // SURGICAL FIX: Dismiss the QR code continuously by checking actual WiFi PHY mode.
    if (qr_bg != NULL) {
        wifi_mode_t mode;
        if (esp_wifi_get_mode(&mode) == ESP_OK) {
            if (mode != WIFI_MODE_APSTA && mode != WIFI_MODE_AP) {
                lv_obj_del(qr_bg);
                qr_bg = NULL;
            }
        } else {
            lv_obj_del(qr_bg);
            qr_bg = NULL;
        }
    }"""
        if fallback_target in content:
            content = content.replace(fallback_target, fallback_safe)
            changed = True

    if changed:
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print("SUCCESS: QR dismissal logic decoupled from UI events. GRAM persistence neutralized.")
    else:
        print("FAILED: Target anchor points not found. File was not modified.")

if __name__ == "__main__":
    patch_file()