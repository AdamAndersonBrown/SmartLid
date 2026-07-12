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

#include "lvgl.h"
#include "esp_timer.h"
static esp_lcd_panel_handle_t panel_handle = NULL;
static lv_disp_drv_t disp_drv; // Global reference for the DMA callback

static bool notify_lvgl_flush_ready(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_io_event_data_t *edata, void *user_ctx) {
    lv_disp_flush_ready(&disp_drv);
    return false;
}
static bool screen_on = true;

// --- SURGICAL LVGL PORT HARDWARE LAYER ---
static void disp_flush_cb(lv_disp_drv_t *disp_drv, const lv_area_t *area, lv_color_t *color_p) {
    // Safe DMA push without in-place mutation
    esp_lcd_panel_draw_bitmap(panel_handle, area->x1, area->y1, area->x2 + 1, area->y2 + 1, (uint16_t *)color_p);
    (void)disp_drv; // SURGICAL FIX: lv_disp_flush_ready deferred to DMA hardware callback
}

static void lv_tick_task(void *arg) { lv_tick_inc(2); }

static void lvgl_port_task(void *arg) {
    uint32_t delay_ms;
    while (1) {
        if (screen_on) {
            delay_ms = lv_timer_handler();
            // Clamp delay to ensure UI responsiveness while still allowing RTOS yielding
            if (delay_ms > 50) delay_ms = 50;
            if (delay_ms < 5) delay_ms = 5;
        } else {
            delay_ms = 1000; // Deep sleep poll while screen is physically off
        }
        vTaskDelay(pdMS_TO_TICKS(delay_ms));
    }
}
// -----------------------------------------
static TickType_t last_wake_time = 0;

void core2_set_screen_power(bool enable) {
    uint8_t reg = 0x12; uint8_t data;
    i2c_master_write_read_device(I2C_NUM_0, 0x34, &reg, 1, &data, 1, pdMS_TO_TICKS(10));
    if (enable) data |= 0x02; else data &= ~0x02;
    uint8_t cmd[2] = {0x12, data};
    i2c_master_write_to_device(I2C_NUM_0, 0x34, cmd, 2, pdMS_TO_TICKS(10));
}

void display_manager_wake(void) {
    last_wake_time = xTaskGetTickCount();
    if (!screen_on) {
        core2_set_screen_power(true);
        screen_on = true;
        display_manager_draw_servo_buttons();
        ESP_LOGI("POWER", "Screen Woken Up");
    }
}

static void display_sleep_task(void *pvParam) {
    while(1) {
        if (screen_on && (xTaskGetTickCount() - last_wake_time > pdMS_TO_TICKS(10000))) {
            core2_set_screen_power(false);
            screen_on = false;
            ESP_LOGI("POWER", "Screen Sleeping (10s Idle)");
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}


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
        {0x82, 0xFF}, // Enable Battery ADC
        {0x93, 0x00}, // AXP192 REG 0x93: GPIO2 Control = Output (NOT 0x9A!)
        {0x94, 0x00}  // AXP192 REG 0x94: GPIO2 High (Speaker Amp Enable)
    };
    for(int i=0; i<6; i++) {
        i2c_master_write_to_device(I2C_NUM_0, 0x34, axp_cmd[i], 2, pdMS_TO_TICKS(100));
    }
    vTaskDelay(pdMS_TO_TICKS(100)); // Allow power to stabilize
}


// --- ENTERPRISE UI INSTANTIATION ---
static lv_obj_t * tv_status;
static lv_obj_t * tv_telemetry;


// --- LVGL STATE BINDINGS (THREAD-SAFE POLLING) ---
static volatile int ui_batt = 0;
static volatile bool ui_wifi = false;
static volatile int ui_class_id = 0;
static volatile bool ui_bg_refresh_needed = false;
static volatile uint16_t ui_bg_color_req = 0x0000;
static const char* ui_state_str = "IDLE";

static void lvgl_poll_timer_cb(lv_timer_t * timer) {
    static int last_batt = -1;
    static bool last_wifi = false;
    static int last_class = -1;
    bool header_dirty = false;

    if (ui_bg_refresh_needed) {
        uint32_t hex = 0x000000;
        if (ui_bg_color_req == 0x001F) hex = 0x0044FF; // Blue
        else if (ui_bg_color_req == 0x0000) hex = 0x000000; // Black
        lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(hex), 0);
        ui_bg_refresh_needed = false;
    }

    if (ui_batt != last_batt || ui_wifi != last_wifi) {
        last_batt = ui_batt;
        last_wifi = ui_wifi;
        header_dirty = true;
    }

    if (ui_class_id != last_class) {
        last_class = ui_class_id;
        header_dirty = true;
        if (ui_class_id == 1) {
            ui_state_str = "RATTLE";
            if(tv_telemetry) {
                lv_label_set_text(tv_telemetry, ">>> RATTLE DETECTED <<<");
                lv_obj_set_style_text_color(tv_telemetry, lv_color_hex(0xE3B341), 0);
            }
        } else if (ui_class_id == 2) {
            ui_state_str = "LIFT";
            if(tv_telemetry) {
                lv_label_set_text(tv_telemetry, ">>> LIFT SEQUENCE <<<");
                lv_obj_set_style_text_color(tv_telemetry, lv_color_hex(0x07E0), 0);
            }
        } else {
            ui_state_str = "IDLE";
            if(tv_telemetry) {
                lv_label_set_text(tv_telemetry, "Telemetry Pipeline Active");
                lv_obj_set_style_text_color(tv_telemetry, lv_color_hex(0x58A6FF), 0);
            }
        }
    }

    if (header_dirty && tv_status) {
        lv_label_set_text_fmt(tv_status, "WIFI:%s | %s | BAT:%d%%", 
            last_wifi ? "ON" : "OFF", ui_state_str, last_batt);
    }
}

static void lvgl_ui_init(void) {
    // Force the background explicitly black to fix the backlight optical illusion
    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(0x000000), 0);
    
    // Zone 1: System Status Header
    tv_status = lv_label_create(lv_scr_act());
    lv_label_set_text(tv_status, "WIFI:OFF | IDLE | BAT:--%");
    lv_obj_set_style_text_color(tv_status, lv_color_hex(0xFFFFFF), 0);
    lv_obj_align(tv_status, LV_ALIGN_TOP_MID, 0, 5);

    // Zone 3: Telemetry Dead-Zone
    tv_telemetry = lv_label_create(lv_scr_act());
    lv_label_set_text(tv_telemetry, "Awaiting Telemetry Pipeline...");
    lv_obj_set_style_text_color(tv_telemetry, lv_color_hex(0x58A6FF), 0);
    lv_obj_align(tv_telemetry, LV_ALIGN_CENTER, 0, 0);

    // Zone 4: Chin Legends (Mapping to physical hardware bezel)
    lv_obj_t * lbl_left = lv_label_create(lv_scr_act());
    lv_label_set_text(lbl_left, "v 7s:RST");
    lv_obj_set_style_text_color(lbl_left, lv_color_hex(0x8B949E), 0);
    lv_obj_align(lbl_left, LV_ALIGN_BOTTOM_LEFT, 5, -5);

    lv_obj_t * lbl_mid = lv_label_create(lv_scr_act());
    lv_label_set_text(lbl_mid, "v TAG 1");
    lv_obj_set_style_text_color(lbl_mid, lv_color_hex(0x8B949E), 0);
    lv_obj_align(lbl_mid, LV_ALIGN_BOTTOM_MID, 0, -5);

    lv_obj_t * lbl_right = lv_label_create(lv_scr_act());
    lv_label_set_text(lbl_right, "v 3s:WIFI");
    lv_obj_set_style_text_color(lbl_right, lv_color_hex(0x8B949E), 0);
    lv_obj_align(lbl_right, LV_ALIGN_BOTTOM_RIGHT, -5, -5);

    // Zone 2: Servo Manual Overrides (Visual Only - Intercepted natively by touch_manager)
    lv_obj_t * btn_ccw = lv_btn_create(lv_scr_act());
    lv_obj_set_size(btn_ccw, 90, 60);
    lv_obj_align(btn_ccw, LV_ALIGN_TOP_LEFT, 5, 25);
    lv_obj_set_style_bg_color(btn_ccw, lv_color_hex(0x0044FF), 0);
    lv_obj_t * lbl_ccw = lv_label_create(btn_ccw);
    lv_label_set_text(lbl_ccw, "LOCK\n(CCW)");
    lv_obj_set_style_text_align(lbl_ccw, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(lbl_ccw);

    lv_obj_t * btn_unlock = lv_btn_create(lv_scr_act());
    lv_obj_set_size(btn_unlock, 100, 60);
    lv_obj_align(btn_unlock, LV_ALIGN_TOP_MID, 0, 25);
    lv_obj_set_style_bg_color(btn_unlock, lv_color_hex(0x2EA043), 0);
    lv_obj_t * lbl_unlock = lv_label_create(btn_unlock);
    lv_label_set_text(lbl_unlock, "TEST\nLIFT");
    lv_obj_set_style_text_align(lbl_unlock, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(lbl_unlock);

    lv_obj_t * btn_cw = lv_btn_create(lv_scr_act());
    lv_obj_set_size(btn_cw, 90, 60);
    lv_obj_align(btn_cw, LV_ALIGN_TOP_RIGHT, -5, 25);
    lv_obj_set_style_bg_color(btn_cw, lv_color_hex(0xDA3633), 0);
    lv_obj_t * lbl_cw = lv_label_create(btn_cw);
    lv_label_set_text(lbl_cw, "UNLOCK\n(CW)");
    lv_obj_set_style_text_align(lbl_cw, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(lbl_cw);
    lv_timer_create(lvgl_poll_timer_cb, 50, NULL);
}
// -----------------------------------

void display_manager_init(void) {
    last_wake_time = xTaskGetTickCount();
    xTaskCreate(display_sleep_task, "disp_sleep", 2048, NULL, 2, NULL);
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
        .on_color_trans_done = notify_lvgl_flush_ready,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_config, &io_handle));

    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = -1, // Reset is handled by AXP192
        .color_space = ESP_LCD_COLOR_SPACE_RGB,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(io_handle, &panel_config, &panel_handle));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_handle, false)); // Fixed purple tint
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true));

    // --- SURGICAL LVGL CORE INIT ---
    lv_init();
    static lv_disp_draw_buf_t draw_buf;
    static lv_color_t *buf1 = NULL;
    buf1 = heap_caps_malloc(LCD_WIDTH * 20 * sizeof(lv_color_t), MALLOC_CAP_DMA);
    lv_disp_draw_buf_init(&draw_buf, buf1, NULL, LCD_WIDTH * 20);

    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = LCD_WIDTH;
    disp_drv.ver_res = LCD_HEIGHT;
    disp_drv.flush_cb = disp_flush_cb;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    const esp_timer_create_args_t lvgl_tick_timer_args = { .callback = &lv_tick_task, .name = "lvgl_tick" };
    esp_timer_handle_t lvgl_tick_timer = NULL;
    esp_timer_create(&lvgl_tick_timer_args, &lvgl_tick_timer);
    esp_timer_start_periodic(lvgl_tick_timer, 2000); // 2ms tick

    xTaskCreate(lvgl_port_task, "lvgl_task", 4096, NULL, 5, NULL);
    // -------------------------------
    
    display_manager_fill_screen(COLOR_BLACK);
    display_manager_draw_servo_buttons();
    lvgl_ui_init();
    ESP_LOGI(TAG, "LCD initialized successfully.");
}

static uint16_t last_bg_color = COLOR_BLACK;

void display_manager_fill_screen(uint16_t color) {
    ui_bg_color_req = color;
    ui_bg_refresh_needed = true;
    return; // SURGICAL FIX: LVGL owns the bus. Legacy drawing disabled to prevent SPI deadlocks.
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
    return; // SURGICAL FIX: LVGL owns the bus. Legacy drawing disabled to prevent SPI deadlocks.
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
    ui_batt = percent;
}

void display_manager_draw_reset_progress(int percent, bool warning) {
    return; // SURGICAL FIX: LVGL owns the bus. Legacy drawing disabled to prevent SPI deadlocks.
    if (!panel_handle) return;
    
    static uint16_t prog_buf[320 * 10];
    int fill_w = (percent * 320) / 100;
    for(int y=0; y<10; y++) {
        for(int x=0; x<320; x++) {
            prog_buf[y * 320 + x] = (x < fill_w) ? COLOR_RED : last_bg_color;
        }
    }
    esp_lcd_panel_draw_bitmap(panel_handle, 0, 230, 320, 240, prog_buf);

    static uint16_t warn_buf[100 * 100];
    if (warning) {
        for(int i=0; i<100*100; i++) warn_buf[i] = COLOR_RED;
        esp_lcd_panel_draw_bitmap(panel_handle, 110, 70, 210, 170, warn_buf);
    } else if (percent == 0) {
        for(int i=0; i<100*100; i++) warn_buf[i] = last_bg_color;
        esp_lcd_panel_draw_bitmap(panel_handle, 110, 70, 210, 170, warn_buf);
    }
}

void display_manager_draw_tag(int tag) {
    return; // SURGICAL FIX: LVGL owns the bus. Legacy drawing disabled to prevent SPI deadlocks.
    if (!panel_handle) return;
    
    static uint16_t b_buf[60 * 60];
    static uint16_t c_buf[60 * 60];
    
    int b_x = 130, c_x = 230, y_pos = 160;
    uint16_t color_b = (tag == 1) ? COLOR_YELLOW : last_bg_color;
    uint16_t color_c = (tag == 2) ? COLOR_ORANGE : last_bg_color;

    for(int i=0; i<60*60; i++) b_buf[i] = color_b;
    esp_lcd_panel_draw_bitmap(panel_handle, b_x, y_pos, b_x + 60, y_pos + 60, b_buf);

    for(int i=0; i<60*60; i++) c_buf[i] = color_c;
    esp_lcd_panel_draw_bitmap(panel_handle, c_x, y_pos, c_x + 60, y_pos + 60, c_buf);
}

void display_manager_draw_wifi(int rssi, bool connected) {
    ui_wifi = connected;
}

void display_manager_set_alert(int class_id) {
    ui_class_id = class_id;
}

void display_manager_draw_servo_buttons(void) {
    return; // SURGICAL FIX: LVGL owns the bus. Legacy drawing disabled to prevent SPI deadlocks.
    if (!panel_handle) return;
    static uint16_t ccw_buf[80 * 50];
    static uint16_t unlock_buf[80 * 50];
    static uint16_t cw_buf[80 * 50];

    // Left Button (CCW) - Blue
    for(int i=0; i<80*50; i++) ccw_buf[i] = 0x001F; 
    esp_lcd_panel_draw_bitmap(panel_handle, 0, 30, 80, 80, ccw_buf);

    // Middle Button (Unlock) - Green
    for(int i=0; i<80*50; i++) unlock_buf[i] = 0x07E0; 
    esp_lcd_panel_draw_bitmap(panel_handle, 120, 30, 200, 80, unlock_buf);

    // Right Button (CW) - Red
    for(int i=0; i<80*50; i++) cw_buf[i] = 0xF800; 
    esp_lcd_panel_draw_bitmap(panel_handle, 240, 30, 320, 80, cw_buf);
}
