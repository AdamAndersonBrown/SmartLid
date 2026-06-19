idf_component_register(SRCS "app_main.c" "inference_manager.cpp" "speaker_manager.c" "touch_manager.c" "display_manager.c" "wifi_prov_handler.c" "error_manager.c" "led_manager.c" "imu_telemetry_task.c"
                    INCLUDE_DIRS "."
                    REQUIRES esp_lcd nvs_flash esp_netif esp_wifi wifi_provisioning lwip driver qrcode)
