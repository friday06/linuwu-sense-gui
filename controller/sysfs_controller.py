# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — sysfs_controller.py
All reads and writes to the linuwu_sense kernel module sysfs nodes.

Permissions are granted to the `acer-nitro` group by the udev rule
installed alongside the app, so no root / pkexec is needed at runtime.
"""

import os
import glob
from typing import Dict, Optional, Tuple, List

from config.constants import (
    PLATFORM_PROFILE_PATH, PLATFORM_PROFILE_CHOICES,
    FAN_SPEED_REL, BATTERY_LIMITER_REL, BATTERY_CALIBRATION_REL,
    BACKLIGHT_TIMEOUT_REL, USB_CHARGING_REL,
    BOOT_ANIMATION_SOUND_REL, LCD_OVERRIDE_REL,
    PER_ZONE_MODE_PATH, FOUR_ZONE_MODE_PATH,
    DEFAULT_ZONE_COLORS, DEFAULT_KB_BRIGHTNESS,
)


def _show_error(title: str, text: str, detail: str = "") -> None:
    """Display a non-blocking Qt critical dialog (imported lazily)."""
    from PyQt6.QtWidgets import QMessageBox
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


class SysfsController:
    """
    Thin wrapper around linuwu_sense sysfs nodes.

    All methods return ``True`` / a value on success and ``False`` / ``None``
    on failure.  Errors are reported via a Qt dialog; permission errors on
    *reads* are silenced (the udev perms may not yet be active).
    """

    def __init__(self, sense_base: str = "") -> None:
        self.sense_base = sense_base

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _path(self, rel: str) -> str:
        return os.path.join(self.sense_base, rel) if self.sense_base else ""

    def _write(self, path: str, value: str, label: str) -> bool:
        if not path:
            return False
        try:
            with open(path, "w") as fh:
                fh.write(str(value))
            return True
        except PermissionError:
            _show_error(
                "Permission Denied",
                f"Cannot write: {label}",
                "Make sure you are a member of the 'acer-nitro' group "
                "and have re-logged in since installation.\n\n"
                "Run:  sudo usermod -aG acer-nitro $USER  then log out and back in.",
            )
            return False
        except OSError as exc:
            import errno
            if exc.errno == errno.EOPNOTSUPP:
                return False   # hardware / kernel doesn't support this silently
            _show_error("Write Error", f"Error writing {label}: {exc}")
            return False
        except Exception as exc:
            _show_error("Write Error", f"Error writing {label}: {exc}")
            return False

    def _read(self, path: str, label: str) -> Optional[str]:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path) as fh:
                return fh.read().strip()
        except PermissionError:
            return None   # silent — udev perms may not be active yet
        except Exception as exc:
            _show_error("Read Error", f"Error reading {label}: {exc}")
            return None

    # ── Thermal profiles ──────────────────────────────────────────────────────

    def get_available_profiles(self) -> List[str]:
        """Return the list of profiles reported by platform_profile_choices."""
        raw = self._read(PLATFORM_PROFILE_CHOICES, "platform profile choices")
        return raw.split() if raw else []

    def get_thermal_profile(self) -> Optional[str]:
        return self._read(PLATFORM_PROFILE_PATH, "thermal profile")

    def set_thermal_profile(self, profile: str) -> bool:
        return self._write(PLATFORM_PROFILE_PATH, profile, "thermal profile")

    # ── Fan speed ─────────────────────────────────────────────────────────────

    def set_fan_speed(self, cpu: int, gpu: int) -> bool:
        """
        Write ``cpu,gpu`` to the fan_speed node (values 0–100).
        Pass ``0, 0`` to return control to the firmware (auto mode).
        """
        return self._write(self._path(FAN_SPEED_REL), f"{cpu},{gpu}", "fan speed")

    def get_fan_speed(self) -> Tuple[Optional[int], Optional[int]]:
        """Return ``(cpu_pct, gpu_pct)`` or ``(None, None)`` on failure."""
        raw = self._read(self._path(FAN_SPEED_REL), "fan speed")
        if raw and "," in raw:
            try:
                a, b = raw.split(",", 1)
                return int(a), int(b)
            except ValueError:
                pass
        return None, None

    # ── Hwmon fan RPM (actual hardware tachometer) ───────────────────────────

    def get_fan_rpm(self) -> tuple[int | None, int | None]:
        """
        Read actual fan RPM from hwmon fan*_input nodes.
        Returns (cpu_rpm, gpu_rpm) — None if node not found.
        Searches for the EC/platform hwmon device which exposes fan tachometers.
        """
        import glob, os
        fans: list[int] = []
        # Try acpi_* / asus_ec / acer_wmi / nct* — common EC hwmon names
        ec_names = ["acpi", "nct", "it8", "acer", "ite", "ec"]
        for base in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            try:
                name = open(os.path.join(os.path.realpath(base), "name")).read().strip().lower()
            except Exception:
                continue
            if not any(k in name for k in ec_names):
                continue
            for inp in sorted(glob.glob(os.path.join(os.path.realpath(base), "fan*_input"))):
                try:
                    fans.append(int(open(inp).read().strip()))
                except Exception:
                    pass
        if len(fans) >= 2:
            return fans[0], fans[1]
        if len(fans) == 1:
            return fans[0], None
        return None, None

    # ── Battery limiter ───────────────────────────────────────────────────────


    def get_battery_limiter(self) -> Optional[bool]:
        raw = self._read(self._path(BATTERY_LIMITER_REL), "battery limiter")
        return (raw == "1") if raw is not None else None

    def set_battery_limiter(self, enabled: bool) -> bool:
        return self._write(
            self._path(BATTERY_LIMITER_REL),
            "1" if enabled else "0",
            "battery limiter",
        )

    # ── Battery calibration ───────────────────────────────────────────────────

    def start_battery_calibration(self) -> bool:
        return self._write(self._path(BATTERY_CALIBRATION_REL), "1",
                           "battery calibration")

    # ── Keyboard backlight timeout ────────────────────────────────────────────

    def get_backlight_timeout(self) -> Optional[bool]:
        raw = self._read(self._path(BACKLIGHT_TIMEOUT_REL), "backlight timeout")
        return (raw == "1") if raw is not None else None

    def set_backlight_timeout(self, enabled: bool) -> bool:
        return self._write(
            self._path(BACKLIGHT_TIMEOUT_REL),
            "1" if enabled else "0",
            "backlight timeout",
        )

    # ── USB charging (while powered off) ─────────────────────────────────────

    def get_usb_charging(self) -> Optional[int]:
        raw = self._read(self._path(USB_CHARGING_REL), "USB charging")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    def set_usb_charging(self, level: int) -> bool:
        return self._write(self._path(USB_CHARGING_REL), str(level),
                           "USB charging")

    # ── Boot animation && sound ──────────────────────────────────────────────────

    def get_boot_animation_sound(self) -> "bool | None":
        raw = self._read(self._path(BOOT_ANIMATION_SOUND_REL), "boot animation")
        return (raw == "1") if raw is not None else None

    def set_boot_animation_sound(self, enabled: bool) -> bool:
        return self._write(self._path(BOOT_ANIMATION_SOUND_REL),
                           "1" if enabled else "0", "boot animation")

    # ── LCD override (reduces latency / ghosting) ─────────────────────────────

    def get_lcd_override(self) -> "bool | None":
        raw = self._read(self._path(LCD_OVERRIDE_REL), "LCD override")
        return (raw == "1") if raw is not None else None

    def set_lcd_override(self, enabled: bool) -> bool:
        return self._write(self._path(LCD_OVERRIDE_REL),
                           "1" if enabled else "0", "LCD override")

    # ── CPU frequency cap ─────────────────────────────────────────────────────

    def set_cpu_freq_limit(self, mhz: int) -> bool:
        """
        Cap all cpufreq policy cores to *mhz* MHz.
        Pass ``0`` to restore the hardware maximum (``cpuinfo_max_freq``).
        """
        policies = sorted(glob.glob(
            "/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq"))
        if not policies:
            _show_error("CPU Frequency",
                        "No cpufreq policy nodes found.",
                        "Is the powersave/acpi-cpufreq driver loaded?")
            return False
        ok = True
        for path in policies:
            if mhz == 0:
                hw_max = self._read(
                    path.replace("scaling_max_freq", "cpuinfo_max_freq"),
                    "cpuinfo_max_freq")
                val = hw_max or "9999999"
            else:
                val = str(mhz * 1000)
            if not self._write(path, val, f"cpu freq ({path})"):
                ok = False
        return ok

    def get_cpu_freq_limit_mhz(self) -> Optional[int]:
        paths = sorted(glob.glob(
            "/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq"))
        if not paths:
            return None
        raw = self._read(paths[0], "cpu freq limit")
        try:
            return int(raw) // 1000 if raw else None
        except ValueError:
            return None

    # ── Keyboard RGB (per-zone static) ────────────────────────────────────────

    def get_per_zone_colors(self) -> Dict[str, str]:
        """Return ``{zone: 'RRGGBB'}`` for all four zones."""
        raw = self._read(PER_ZONE_MODE_PATH, "per-zone colours")
        colors = dict(DEFAULT_ZONE_COLORS)
        if raw:
            for i, zone in enumerate(["zone1", "zone2", "zone3", "zone4"]):
                parts = raw.split(",")
                if i < len(parts):
                    colors[zone] = parts[i].strip().upper().zfill(6)
        return colors

    def set_per_zone_colors(
        self,
        colors: Dict[str, str],
        brightness: int = DEFAULT_KB_BRIGHTNESS,
    ) -> bool:
        """Write ``RRGGBB,RRGGBB,RRGGBB,RRGGBB,BRIGHTNESS`` to per_zone_mode."""
        parts = [
            colors.get(z, "FFFFFF").upper().zfill(6)
            for z in ["zone1", "zone2", "zone3", "zone4"]
        ]
        parts.append(str(brightness))
        return self._write(PER_ZONE_MODE_PATH, ",".join(parts), "per-zone colours")

    def set_four_zone_mode(
        self,
        mode: int,
        speed: int = 5,
        brightness: int = 100,
        r: int = 255,
        g: int = 0,
        b: int = 0,
        direction: int = 2,
    ) -> bool:
        """Write ``MODE,SPEED,BRIGHTNESS,R,G,B,DIRECTION`` to four_zone_mode."""
        value = f"{mode},{speed},{brightness},{r},{g},{b},{direction}"
        return self._write(FOUR_ZONE_MODE_PATH, value, "keyboard effect")
