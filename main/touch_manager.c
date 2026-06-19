#include "touch_manager.h"
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
