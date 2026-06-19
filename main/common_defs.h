#ifndef COMMON_DEFS_H
#define COMMON_DEFS_H

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "error_manager.h"

#define APP_TAG "M5_CORE2"

extern EventGroupHandle_t wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1
#define WIFI_PROV_DONE_BIT BIT2
#define SHUTDOWN_REQUEST_BIT BIT4
#define FACTORY_RESET_BIT BIT5

// Minimal LED States to satisfy wifi_prov_handler
typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_INITIALIZING,
    LED_STATE_PROVISIONING_ACTIVE,
    LED_STATE_PROVISIONING_CONNECTING,
    LED_STATE_WIFI_CONNECTING,
    LED_STATE_WIFI_CONNECTED_IDLE,
    LED_STATE_TIME_SYNCING,
    LED_STATE_AUDIO_CONNECTING,
    LED_STATE_AUDIO_STREAMING,
    LED_STATE_OTA_CHECKING,
    LED_STATE_BUTTON_HELD,
    LED_STATE_ERROR,
    LED_STATE_REBOOTING
} led_state_t;

#endif // COMMON_DEFS_H
