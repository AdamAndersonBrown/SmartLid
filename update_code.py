# update_code.py
import os
import re

disp_h = "main/display_manager.h"
disp_c = "main/display_manager.c"
touch_c = "main/touch_manager.c"

print("Upgrading UI with ML Tag visualizers and 7-Second Reset Warning...")

# 1. Update Display Manager Header
if os.path.exists(disp_h):
    with open(disp_h, "r") as f:
        content = f.read()
    
    if "COLOR_YELLOW" not in content:
        content = content.replace('#define COLOR_RED   0xF800', '#define COLOR_RED   0xF800\n#define COLOR_YELLOW 0xFFE0\n#define COLOR_ORANGE 0xFD20')
        
    content = content.replace('void display_manager_draw_reset_progress(int percent);', 'void display_manager_draw_reset_progress(int percent, bool warning);\nvoid display_manager_draw_tag(int tag);')
    with open(disp_h, "w") as f:
        f.write(content)
    print("-> display_manager.h patched.")

# 2. Update Display Manager Source
if os.path.exists(disp_c):
    with open(disp_c, "r") as f:
        content = f.read()

    # Regex to find and replace the old reset_progress function
    pattern_reset = r'void display_manager_draw_reset_progress\(int percent\)\s*\{[\s\S]*?free\(buf\);\n\}'
    
    new_ui_functions = """void display_manager_draw_reset_progress(int percent, bool warning) {
    if (!panel_handle) return;
    
    // 1. Draw the progress bar at the bottom
    uint16_t *buf = malloc(320 * 10 * sizeof(uint16_t));
    if (buf) {
        int fill_w = (percent * 320) / 100;
        for(int y=0; y<10; y++) {
            for(int x=0; x<320; x++) {
                buf[y * 320 + x] = (x < fill_w) ? COLOR_RED : last_bg_color;
            }
        }
        esp_lcd_panel_draw_bitmap(panel_handle, 0, 230, 320, 240, buf);
        free(buf);
    }

    // 2. Draw or clear the central warning box
    uint16_t *warn_buf = malloc(100 * 100 * sizeof(uint16_t));
    if (warn_buf) {
        if (warning) {
            for(int i=0; i<100*100; i++) warn_buf[i] = COLOR_RED;
            esp_lcd_panel_draw_bitmap(panel_handle, 110, 70, 210, 170, warn_buf);
        } else if (percent == 0) {
            // Only clear it if the reset is fully aborted to prevent flickering
            for(int i=0; i<100*100; i++) warn_buf[i] = last_bg_color;
            esp_lcd_panel_draw_bitmap(panel_handle, 110, 70, 210, 170, warn_buf);
        }
        free(warn_buf);
    }
}

void display_manager_draw_tag(int tag) {
    if (!panel_handle) return;
    uint16_t *buf = malloc(60 * 60 * sizeof(uint16_t));
    if (!buf) return;

    int b_x = 130, c_x = 230, y_pos = 160;
    uint16_t color_b = (tag == 1) ? COLOR_YELLOW : last_bg_color;
    uint16_t color_c = (tag == 2) ? COLOR_ORANGE : last_bg_color;

    // Paint Tag 1 (Button B) area
    for(int i=0; i<60*60; i++) buf[i] = color_b;
    esp_lcd_panel_draw_bitmap(panel_handle, b_x, y_pos, b_x + 60, y_pos + 60, buf);

    // Paint Tag 2 (Button C) area
    for(int i=0; i<60*60; i++) buf[i] = color_c;
    esp_lcd_panel_draw_bitmap(panel_handle, c_x, y_pos, c_x + 60, y_pos + 60, buf);

    free(buf);
}
"""
    if "display_manager_draw_tag" not in content:
        content = re.sub(pattern_reset, new_ui_functions, content)
        with open(disp_c, "w") as f:
            f.write(content)
        print("-> display_manager.c patched (UI visualizers added).")

# 3. Overwrite Touch Manager with 7-Second logic and Tag drawing calls
if os.path.exists(touch_c):
    new_touch = """#include "touch_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "common_defs.h"
#include "display_manager.h"

static const char *TAG = "TOUCH";
#define FT6336U_ADDR 0x38
#define RESET_TIME_MS 7000
#define WARN_TIME_MS  5000

static void touch_task(void *pvParameters) {
    uint8_t data[5];
    int reset_held_time = 0;
    int miss_count = 0;
    int last_tag = -1;

    while(1) {
        uint8_t reg = 0x02; 
        esp_err_t err = i2c_master_write_read_device(I2C_NUM_0, FT6336U_ADDR, &reg, 1, data, 5, pdMS_TO_TICKS(10));
        
        bool is_touched = false;
        if (err == ESP_OK) {
            uint8_t touch_points = data[0] & 0x0F;
            if (touch_points > 0 && touch_points <= 2) {
                uint16_t x = ((data[1] & 0x0F) << 8) | data[2];
                uint16_t y = ((data[3] & 0x0F) << 8) | data[4];
                
                if (y > 240) {
                    is_touched = true;
                    miss_count = 0;
                    
                    if (x < 100) {
                        // Button A: Factory Reset
                        active_event_tag = 0;
                        reset_held_time += 50;
                        
                        bool warn = (reset_held_time >= WARN_TIME_MS);
                        display_manager_draw_reset_progress((reset_held_time * 100) / RESET_TIME_MS, warn);
                        
                        if (reset_held_time >= RESET_TIME_MS) {
                            ESP_LOGE(TAG, "!!! FACTORY RESET TRIGGERED BY TOUCH !!!");
                            xEventGroupSetBits(wifi_event_group, FACTORY_RESET_BIT);
                            reset_held_time = 0; 
                            vTaskDelay(pdMS_TO_TICKS(5000));
                        }
                    } else if (x >= 100 && x < 220) {
                        // Button B: ML Event Tag 1
                        active_event_tag = 1;
                        if (reset_held_time > 0) { reset_held_time = 0; display_manager_draw_reset_progress(0, false); }
                    } else if (x >= 220) {
                        // Button C: ML Event Tag 2
                        active_event_tag = 2;
                        if (reset_held_time > 0) { reset_held_time = 0; display_manager_draw_reset_progress(0, false); }
                    }
                }
            }
        }
        
        if (!is_touched) {
            miss_count++;
            if (miss_count > 5) { // 250ms debounce
                active_event_tag = 0;
                if (reset_held_time > 0) {
                    // Abort reset, clear progress bar and warning box
                    reset_held_time = 0;
                    display_manager_draw_reset_progress(0, false);
                }
            }
        }

        // Only command the SPI bus to draw if the tag actually changed
        if (active_event_tag != last_tag) {
            display_manager_draw_tag(active_event_tag);
            last_tag = active_event_tag;
        }

        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void touch_manager_init(void) {
    xTaskCreate(touch_task, "touch_task", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "Capacitive Touch UI and Tagger initialized.");
}
"""
    with open(touch_c, "w") as f:
        f.write(new_touch)
    print("-> touch_manager.c patched (7-Second logic and UI triggers added).")

print("Surgical patch complete.")