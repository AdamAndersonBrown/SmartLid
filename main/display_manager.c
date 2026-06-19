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
        {0x12, 0x47}  // Enable DCDC1, DCDC3, LDO2, EXTEN
    };
    for(int i=0; i<3; i++) {
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

void display_manager_fill_screen(uint16_t color) {
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
