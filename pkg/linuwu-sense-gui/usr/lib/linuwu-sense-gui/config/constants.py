# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — constants.py
Sysfs paths and application-wide constants.
"""

# ── Sysfs base paths ──────────────────────────────────────────────────────────
_WMI_BASE     = "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi"
PREDATOR_BASE = f"{_WMI_BASE}/predator_sense"
NITRO_BASE    = f"{_WMI_BASE}/nitro_sense"

# ── ACPI platform profile ─────────────────────────────────────────────────────
PLATFORM_PROFILE_PATH    = "/sys/firmware/acpi/platform_profile"
PLATFORM_PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"

# Real profiles exposed by the linuwu_sense module on Nitro V hardware:
THERMAL_PROFILES_AC      = ["low-power", "quiet", "balanced", "balanced-performance"]
THERMAL_PROFILES_BATTERY = ["balanced"]

# ── Fan speed (relative to sense base) ───────────────────────────────────────
# Write format: "CPU,GPU"  e.g. "50,70"  (integers 0–100)
# Write "0,0" to return control to firmware (auto mode).
FAN_SPEED_REL = "fan_speed"
FAN_SPEED_MIN = 0
FAN_SPEED_MAX = 100

# ── Battery ───────────────────────────────────────────────────────────────────
BATTERY_LIMITER_REL     = "battery_limiter"      # "0" / "1"
BATTERY_CALIBRATION_REL = "battery_calibration"  # write "1" to start

# ── Keyboard backlight timeout ────────────────────────────────────────────────
BACKLIGHT_TIMEOUT_REL = "backlight_timeout"       # "0" / "1"

# ── USB charging threshold (while laptop is off) ──────────────────────────────
USB_CHARGING_REL = "usb_charging"                 # integer 0/10/20/30

# ── Boot animation & sound ────────────────────────────────────────────────────
BOOT_ANIMATION_SOUND_REL = "boot_animation_sound" # "0" / "1"

# ── LCD override (reduces latency / ghosting) ─────────────────────────────────
LCD_OVERRIDE_REL = "lcd_override"                 # "0" / "1"

# ── Four-zone RGB keyboard ────────────────────────────────────────────────────
_KB_BASE        = f"{_WMI_BASE}/four_zoned_kb"
FOUR_ZONED_KB_BASE  = _KB_BASE
PER_ZONE_MODE_PATH  = f"{_KB_BASE}/per_zone_mode"
FOUR_ZONE_MODE_PATH = f"{_KB_BASE}/four_zone_mode"

# Lighting effects (four_zone_mode first field)
KB_EFFECTS = {
    "Static":    0,
    "Breathing": 1,
    "Wave":      2,
    "Rainbow":   3,
    "Pulse":     4,
    "Flash":     5,
}

# Direction field values (per module source)
KB_DIRECTIONS = {"Left to Right": 2, "Right to Left": 1}

# Speed field: 0–9
KB_SPEED_MIN = 0
KB_SPEED_MAX = 9

DEFAULT_KB_BRIGHTNESS = 100
DEFAULT_ZONE_COLORS = {
    "zone1": "FF0000",
    "zone2": "00FF00",
    "zone3": "0000FF",
    "zone4": "FFFF00",
}

# ── Application ───────────────────────────────────────────────────────────────
APP_NAME    = "linuwu sense"
APP_VERSION = "1.0.0"
ICON_PATH   = "/usr/share/icons/hicolor/scalable/apps/linuwu-sense-gui.svg"
