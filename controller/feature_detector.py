# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — feature_detector.py
Probes sysfs at startup to determine which hardware features are present,
then tells the main window which tabs to show.
"""

import os
from typing import Dict, List

from config.constants import (
    PREDATOR_BASE, NITRO_BASE,
    PLATFORM_PROFILE_PATH,
    FAN_SPEED_REL, BATTERY_LIMITER_REL, BATTERY_CALIBRATION_REL,
    BACKLIGHT_TIMEOUT_REL, USB_CHARGING_REL,
    BOOT_ANIMATION_SOUND_REL, LCD_OVERRIDE_REL,
    FOUR_ZONED_KB_BASE, PER_ZONE_MODE_PATH,
)


class FeatureDetector:
    """
    Detect which linuwu_sense features are available on the current machine.

    Call ``detect_features()`` to (re-)probe; the result is cached in
    ``available_features``.
    """

    def __init__(self) -> None:
        self.sense_base: str = self._find_sense_base()
        self.available_features: Dict[str, bool] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_sense_base(self) -> str:
        for candidate in (PREDATOR_BASE, NITRO_BASE):
            if os.path.isdir(candidate):
                return candidate
        return ""

    def _sense_path(self, rel: str) -> str:
        return os.path.join(self.sense_base, rel) if self.sense_base else ""

    def _exists(self, path: str) -> bool:
        return bool(path) and os.path.exists(path)

    # ── Public API ────────────────────────────────────────────────────────────

    def detect_features(self) -> Dict[str, bool]:
        """Probe sysfs and return (and cache) a feature availability dict."""
        self.sense_base = self._find_sense_base()
        self.available_features = {
            "sense_base":          bool(self.sense_base),
            "thermal_profiles":    self._exists(PLATFORM_PROFILE_PATH),
            "fan_control":         self._exists(self._sense_path(FAN_SPEED_REL)),
            "battery_limiter":     self._exists(self._sense_path(BATTERY_LIMITER_REL)),
            "battery_calibration": self._exists(self._sense_path(BATTERY_CALIBRATION_REL)),
            "backlight_timeout":   self._exists(self._sense_path(BACKLIGHT_TIMEOUT_REL)),
            "usb_charging":        self._exists(self._sense_path(USB_CHARGING_REL)),
            "boot_animation_sound":self._exists(self._sense_path(BOOT_ANIMATION_SOUND_REL)),
            "lcd_override":        self._exists(self._sense_path(LCD_OVERRIDE_REL)),
            "keyboard_rgb":        self._exists(PER_ZONE_MODE_PATH),
            "four_zoned_kb":       os.path.isdir(FOUR_ZONED_KB_BASE),
        }
        return self.available_features

    def get_sense_base(self) -> str:
        return self.sense_base

    def get_available_tabs(self) -> List[str]:
        """Return the ordered list of tab keys the main window should create."""
        f = self.detect_features()
        tabs: List[str] = []
        if f["thermal_profiles"] or f["fan_control"]:
            tabs.append("thermal_fan")
        if f["fan_control"]:
            tabs.append("fan_control")
        if f["battery_limiter"] or f["battery_calibration"]:
            tabs.append("battery")
        if f["keyboard_rgb"] or f["four_zoned_kb"]:
            tabs.append("keyboard")
        if f["usb_charging"]:
            tabs.append("advanced")
        return tabs

    def is_available(self, feature: str) -> bool:
        return self.available_features.get(feature, False)
