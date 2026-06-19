# update_code.py
import os
import re

touch_c = "main/touch_manager.c"
disp_c = "main/display_manager.c"

print("Fixing impossible logic and rogue AXP192 hardware registers...")

# 1. Fix the impossible logic in the Touch Manager
if os.path.exists(touch_c):
    with open(touch_c, "r") as f:
        content = f.read()
        
    target_touch = """// Button B: ML Event Tag 1
                        active_event_tag = 1;
                        if (reset_held_time > 0) { reset_held_time = 0; display_manager_draw_reset_progress(0, false); }
                        if (!is_touched) speaker_play_rattle(); // Play sound on initial press"""
                        
    fix_touch = """// Button B: ML Event Tag 1
                        if (active_event_tag != 1) { speaker_play_rattle(); } // Fire exactly once on press
                        active_event_tag = 1;
                        if (reset_held_time > 0) { reset_held_time = 0; display_manager_draw_reset_progress(0, false); }"""
    
    if "active_event_tag != 1" not in content:
        content = content.replace(target_touch, fix_touch)
        with open(touch_c, "w") as f:
            f.write(content)
        print("-> touch_manager.c patched (Sound logic fixed).")

# 2. Fix the rogue AXP192 power register causing visual artifacts
if os.path.exists(disp_c):
    with open(disp_c, "r") as f:
        content = f.read()

    # Use regex to securely replace the entire AXP array to guarantee it is correct
    pattern_axp = r'uint8_t axp_cmd\[\]\[2\] = \{[\s\S]*?\};\n\s*for\(int i=0; i<\d; i\+\+\) \{'
    
    fix_axp = """uint8_t axp_cmd[][2] = {
        {0x27, 0xCC}, // DCDC3 (LCD Backlight) 
        {0x28, 0xCC}, // LDO2 (LCD Logic) 3.3V
        {0x12, 0x47}, // Enable DCDC1, DCDC3, LDO2, EXTEN
        {0x82, 0xFF}, // Enable Battery ADC
        {0x93, 0x00}, // AXP192 REG 0x93: GPIO2 Control = Output (NOT 0x9A!)
        {0x94, 0x04}  // AXP192 REG 0x94: GPIO2 High (Speaker Amp Enable)
    };
    for(int i=0; i<6; i++) {"""

    if "{0x93, 0x00}" not in content:
        content = re.sub(pattern_axp, fix_axp, content)
        with open(disp_c, "w") as f:
            f.write(content)
        print("-> display_manager.c patched (Visual artifacts cleared, Amp powered).")

print("Surgical patch complete.")