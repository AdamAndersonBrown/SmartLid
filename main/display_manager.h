#ifndef DISPLAY_MANAGER_H
#define DISPLAY_MANAGER_H

#include "esp_err.h"
#include <stdint.h>
#include <stdbool.h>

void display_manager_init(void);
void display_manager_fill_screen(uint16_t color);
void display_manager_draw_qr(const uint8_t *qrcode, int size);

// Basic RGB565 Colors
#define COLOR_BLUE  0x001F
#define COLOR_GREEN 0x07E0
#define COLOR_BLACK 0x0000
#define COLOR_WHITE 0xFFFF

#endif // DISPLAY_MANAGER_H
