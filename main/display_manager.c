#include "display_manager.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_ili9341.h"
#include "driver/i2c.h"
#include "esp_lcd_panel_ops.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "DISPLAY";

#define LCD_HOST       SPI2_HOST
#define LCD_PIXEL_CLK  (20 * 1000 * 1000)
#define LCD_MOSI       23
#define LCD_MISO       38
#define LCD_SCLK       18
#define LCD_CS         5
#define LCD_DC         15
#define LCD_WIDTH      320
#define LCD_HEIGHT     240

static esp_lcd_panel_handle_t panel_handle = NULL;

void core2_power_init(void) {
    // 1. Initialize I2C safely
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = 21,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_io_num = 22,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    i2c_param_config(I2C_NUM_0, &conf);
    esp_err_t err = i2c_driver_install(I2C_NUM_0, conf.mode, 0, 0, 0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "I2C Init failed: %s", esp_err_to_name(err));
    }

    // 2. Command AXP192 to power the LCD
    uint8_t axp_cmd[][2] = {
        {0x27, 0xCC}, // DCDC3 (LCD Backlight) 
        {0x28, 0xCC}, // LDO2 (LCD Logic) 3.3V
        {0x12, 0x47}, // Enable DCDC1, DCDC3, LDO2, EXTEN
        {0x82, 0xFF}  // Enable Battery ADC
    };
    for(int i=0; i<4; i++) {
        i2c_master_write_to_device(I2C_NUM_0, 0x34, axp_cmd[i], 2, pdMS_TO_TICKS(100));
    }
    vTaskDelay(pdMS_TO_TICKS(100)); // Allow power to stabilize
}

void display_manager_init(void) {
    core2_power_init();
    ESP_LOGI(TAG, "Initializing SPI bus for LCD...");
    spi_bus_config_t buscfg = {
        .sclk_io_num = LCD_SCLK,
        .mosi_io_num = LCD_MOSI,
        .miso_io_num = LCD_MISO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_WIDTH * LCD_HEIGHT * 2 + 8
    };
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    ESP_LOGI(TAG, "Installing ILI9342C panel driver...");
    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = LCD_DC,
        .cs_gpio_num = LCD_CS,
        .pclk_hz = LCD_PIXEL_CLK,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_config, &io_handle));

    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = -1, // Reset is handled by AXP192
        .color_space = ESP_LCD_COLOR_SPACE_BGR,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(io_handle, &panel_config, &panel_handle));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_handle, false)); // Fixed purple tint
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true));
    
    display_manager_fill_screen(COLOR_BLACK);
    ESP_LOGI(TAG, "LCD initialized successfully.");
}

static uint16_t last_bg_color = COLOR_BLACK;

void display_manager_fill_screen(uint16_t color) {
    last_bg_color = color;
    if (!panel_handle) return;
    uint16_t *buffer = malloc(LCD_WIDTH * 20 * sizeof(uint16_t));
    for (int i = 0; i < LCD_WIDTH * 20; i++) buffer[i] = color;
    
    for (int y = 0; y < LCD_HEIGHT; y += 20) {
        esp_lcd_panel_draw_bitmap(panel_handle, 0, y, LCD_WIDTH, y + 20, buffer);
    }
    free(buffer);
}

void display_manager_draw_qr(const uint8_t *qrcode, int size) {
    if (!panel_handle || !qrcode) return;
    
    // Scale the QR code to fit nicely on the 240p screen
    int scale = 200 / size; 
    int offset_x = (LCD_WIDTH - (size * scale)) / 2;
    int offset_y = (LCD_HEIGHT - (size * scale)) / 2;

    display_manager_fill_screen(COLOR_WHITE); // White background for scanner contrast

    uint16_t *block = malloc(scale * scale * sizeof(uint16_t));
    for (int i = 0; i < scale * scale; i++) block[i] = COLOR_BLACK;

    for (int y = 0; y < size; y++) {
        for (int x = 0; x < size; x++) {
            // qrcode array is 1D, packed. True = Black square.
            if (qrcode[y * size + x]) {
                int px = offset_x + (x * scale);
                int py = offset_y + (y * scale);
                esp_lcd_panel_draw_bitmap(panel_handle, px, py, px + scale, py + scale, block);
            }
        }
    }
    free(block);
}


void core2_get_battery_state(int *percent, bool *is_charging) {
    uint8_t reg_v = 0x78;
    uint8_t data_v[2];
    i2c_master_write_read_device(I2C_NUM_0, 0x34, &reg_v, 1, data_v, 2, pdMS_TO_TICKS(10));
    uint16_t adc = (data_v[0] << 4) | (data_v[1] & 0x0F);
    float vbatt = adc * 1.1f;
    int p = (int)((vbatt - 3200.0f) / (4100.0f - 3200.0f) * 100.0f);
    if (p > 100) { p = 100; }
    if (p < 0) { p = 0; }
    *percent = p;

    // Register 0x00: Input power status. Bit 5 = VBUS (USB) present.
    uint8_t reg_p = 0x00;
    uint8_t data_p;
    i2c_master_write_read_device(I2C_NUM_0, 0x34, &reg_p, 1, &data_p, 1, pdMS_TO_TICKS(10));
    *is_charging = (data_p & 0x20) ? true : false;
}

void display_manager_draw_battery(int percent, bool is_charging) {
    if (!panel_handle) return;
    int fill_w = (percent * 26) / 100;
    uint16_t *buf = malloc(35 * 15 * sizeof(uint16_t));
    for(int y=0; y<15; y++) {
        for(int x=0; x<35; x++) {
            uint16_t color = last_bg_color;
            if (x < 30 && y < 12) {
                if (x == 0 || x == 29 || y == 0 || y == 11) color = COLOR_WHITE;
                else if (x > 1 && x < 2 + fill_w && y > 1 && y < 10) {
                    color = (percent > 20) ? COLOR_WHITE : COLOR_RED;
                    // Draw charging '+' symbol inside the battery
                    if (is_charging && x >= 13 && x <= 17 && y >= 4 && y <= 8) {
                        if (x == 15 || y == 6) color = COLOR_BLACK; 
                    }
                }
            } else if (x >= 30 && x < 33 && y >= 3 && y <= 8) {
                color = COLOR_WHITE;
            }
            buf[y * 35 + x] = color;
        }
    }
    esp_lcd_panel_draw_bitmap(panel_handle, 280, 5, 315, 20, buf);
    free(buf);
}

void display_manager_draw_reset_progress(int percent, bool warning) {
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


