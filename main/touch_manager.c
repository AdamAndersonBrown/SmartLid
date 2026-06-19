#include "touch_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "common_defs.h"
#include "app_main.h"

static const char *TAG = "TOUCH";
#define FT6336U_ADDR 0x38
#define TOUCH_TASK_DELAY_MS 50
#define RESET_HOLD_TIME_MS 3000

static void touch_task(void *pvParameters) {
    uint8_t data[5];
    int held_time = 0;
    bool is_pressed = false;
    int miss_count = 0; // Jitter buffer

    while(1) {
        uint8_t reg = 0x02; 
        esp_err_t err = i2c_master_write_read_device(I2C_NUM_0, FT6336U_ADDR, &reg, 1, data, 5, pdMS_TO_TICKS(10));
        
        if (err == ESP_OK) {
            uint8_t touch_points = data[0] & 0x0F;
            
            if (touch_points > 0 && touch_points <= 2) { // Valid touch detected
                uint16_t x = ((data[1] & 0x0F) << 8) | data[2];
                uint16_t y = ((data[3] & 0x0F) << 8) | data[4];

                // Print the raw coordinates so we can see what the hardware is doing!
                ESP_LOGI(TAG, "Touch Registered -> X: %d, Y: %d", x, y);

                // Expanded bounding box for Button A (Bottom Left)
                // We check both standard and inverted coordinate maps just in case
                if ((x < 160 && y > 200) || (y < 160 && x > 200)) {
                    if (!is_pressed) {
                        ESP_LOGW(TAG, "Button A touched! Hold for 3 seconds to Factory Reset.");
                    }
                    is_pressed = true;
                    miss_count = 0;
                    held_time += TOUCH_TASK_DELAY_MS;

                    if (held_time >= RESET_HOLD_TIME_MS) {
                        ESP_LOGE(TAG, "!!! FACTORY RESET TRIGGERED BY TOUCH !!!");
                        xEventGroupSetBits(wifi_event_group, FACTORY_RESET_BIT);
                        held_time = 0; 
                        vTaskDelay(pdMS_TO_TICKS(5000));
                    }
                } else {
                    // Finger slid off the button
                    is_pressed = false;
                    held_time = 0;
                }
            } else {
                // 0 touches reported. Use the Jitter Buffer to allow a grace period.
                if (is_pressed) {
                    miss_count++;
                    if (miss_count > 5) { // ~250ms grace period expired
                        is_pressed = false;
                        held_time = 0;
                    }
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(TOUCH_TASK_DELAY_MS));
    }
}

void touch_manager_init(void) {
    xTaskCreate(touch_task, "touch_task", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "Capacitive touch driver initialized.");
}
