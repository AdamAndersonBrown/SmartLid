# nuclear_audio_fix.py
import os

print("Executing Nuclear Reset and Perfect Rebuild of Audio Driver...")

# 1. Force Git to completely overwrite our mangled file with the pristine original
os.system("git checkout HEAD -- main/hardware/speaker_manager.c")

speaker_c = "main/hardware/speaker_manager.c"
if os.path.exists(speaker_c):
    with open(speaker_c, "r") as f:
        content = f.read()

    # 2. Inject Headers, Variables, AND Forward Declarations safely at the top
    if "freertos/semphr.h" not in content:
        last_inc = content.rfind('#include')
        eol = content.find('\n', last_inc) + 1
        
        top_injection = """
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

// Globals and Forward Declarations to satisfy the C Compiler's strict ordering
static SemaphoreHandle_t audio_semaphore = NULL;
static void speaker_task(void *pvParameters);
"""
        content = content[:eol] + top_injection + content[eol:]

    # 3. Rename the original hardware function so it's safely internal
    content = content.replace("void speaker_play_rattle(void)", "static void speaker_play_rattle_internal(void)")

    # 4. Inject the Semaphore creation and Task spin-up into your init sequence
    target_init = "void speaker_manager_init(void) {"
    fix_init = """void speaker_manager_init(void) {
    audio_semaphore = xSemaphoreCreateBinary();
    xTaskCreatePinnedToCore(speaker_task, "speaker_task", 4096, NULL, 2, NULL, 1);"""
    content = content.replace(target_init, fix_init)

    # 5. Append the Background Task and the Public "Fire-and-Forget" API
    bottom_injection = """
static void speaker_task(void *pvParameters) {
    while(1) {
        if (xSemaphoreTake(audio_semaphore, portMAX_DELAY) == pdTRUE) {
            speaker_play_rattle_internal();
        }
    }
}

void speaker_play_rattle(void) {
    if (audio_semaphore != NULL) {
        xSemaphoreGive(audio_semaphore);
    }
}
"""
    content += bottom_injection

    with open(speaker_c, "w") as f:
        f.write(content)
        
    print("-> speaker_manager.c resurrected from Git and flawlessly patched!")
else:
    print("-> ERROR: Could not find main/hardware/speaker_manager.c")