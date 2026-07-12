import os
import re

TARGET_FILE = os.path.join("main", "hardware", "display_manager.c")

def patch_file():
    if not os.path.exists(TARGET_FILE):
        print(f"CRITICAL: {TARGET_FILE} not found in the current directory.")
        return

    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # The new target color: Amber/Orange for high visibility against Blue and Black
    safe_str = "lv_obj_set_style_bg_color(btn_unlock, lv_color_hex(0xE67E22), 0); // Shifted to Orange"
    
    # Try literal replacements first based on the previous patch variants
    target_str_1 = "lv_obj_set_style_bg_color(btn_unlock, lv_color_hex(0x0044FF), 0); // Shifted to Blue"
    target_str_2 = "lv_obj_set_style_bg_color(btn_unlock, lv_color_hex(0x0044FF), 0);"
    
    changed = False
    
    if target_str_1 in content:
        content = content.replace(target_str_1, safe_str)
        changed = True
    elif target_str_2 in content:
        content = content.replace(target_str_2, safe_str)
        changed = True
    else:
        # Fallback to regex if formatting got mangled by the IDE
        content_new = re.sub(
            r'lv_obj_set_style_bg_color\s*\(\s*btn_unlock\s*,\s*lv_color_hex\s*\([^)]+\)\s*,\s*0\s*\)[^\n]*',
            safe_str,
            content
        )
        if content_new != content:
            content = content_new
            changed = True

    if changed:
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print("SUCCESS: Surgical patch applied. TEST LIFT button changed to Orange.")
    else:
        print("FAILED: Could not find the TEST LIFT button color definition.")

if __name__ == "__main__":
    patch_file()