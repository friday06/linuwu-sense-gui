#!/bin/sh
# set-sysfs-perms.sh
# Grants the acer-nitro group rw access to all linuwu_sense sysfs nodes.
# Called by udev (on device hotplug) and by linuwu-sense-perms.service (on boot).

GROUP="acer-nitro"

fix() {
    [ -e "$1" ] || return 0
    chgrp "$GROUP" "$1" 2>/dev/null || true
    chmod g+rw    "$1" 2>/dev/null || true
}

fix_dir() {
    [ -d "$1" ] || return 0
    find "$1" -maxdepth 1 -type f | while read -r f; do fix "$f"; done
}

# ── nitro_sense / predator_sense ──────────────────────────────────────────
for BASE in \
    /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/nitro_sense \
    /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense
do
    fix_dir "$BASE"
done

# ── four_zoned_kb ─────────────────────────────────────────────────────────
fix_dir /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/four_zoned_kb

# ── ACPI platform profile ─────────────────────────────────────────────────
fix /sys/firmware/acpi/platform_profile
chgrp "$GROUP" /sys/firmware/acpi/platform_profile_choices 2>/dev/null || true

# ── cpufreq scaling_max_freq ──────────────────────────────────────────────
for f in /sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq; do
    fix "$f"
done
