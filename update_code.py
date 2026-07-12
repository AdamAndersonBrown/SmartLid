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

    # 1. Inject the Global LVGL Display Driver and DMA Callback
    target_globals = "static esp_lcd_panel_handle_t panel_handle = NULL;"
    safe_globals = """static esp_lcd_panel_handle_t panel_handle = NULL;
static lv_disp_drv_t disp_drv; // Global reference for the DMA callback

static bool notify_lvgl_flush_ready(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_io_event_data_t *edata, void *user_ctx) {
    lv_disp_flush_ready(&disp_drv);
    return false;
}"""
    if "notify_lvgl_flush_ready" not in content:
        content = content.replace(target_globals, safe_globals)
        changed = True

    # 2. Neuter the immediate flush call to prevent the race condition
    target_flush = "lv_disp_flush_ready(disp_drv);"
    safe_flush = "(void)disp_drv; // SURGICAL FIX: lv_disp_flush_ready deferred to DMA hardware callback"
    if target_flush in content:
        content = content.replace(target_flush, safe_flush)
        changed = True

    # 3. Register the DMA callback in the SPI IO Configuration
    target_io = ".trans_queue_depth = 10,"
    safe_io = ".trans_queue_depth = 10,\n        .on_color_trans_done = notify_lvgl_flush_ready,"
    if ".on_color_trans_done" not in content and target_io in content:
        content = content.replace(target_io, safe_io)
        changed = True

    # 4. Remove the local disp_drv declaration since we elevated it to global scope
    # Regex used to handle any minor whitespace variations
    content_new = re.sub(r'static lv_disp_drv_t disp_drv;\s*lv_disp_drv_init\(&disp_drv\);', 'lv_disp_drv_init(&disp_drv);', content)
    if content_new != content:
        content = content_new
        changed = True

    if changed:
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"SUCCESS: Surgical patch applied. DMA Tearing resolved.")
    else:
        print("FAILED: Target sequences not found or already patched. The file was not modified.")

if __name__ == "__main__":
    patch_file()