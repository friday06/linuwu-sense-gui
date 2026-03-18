#!/usr/bin/env bash
# uninstall.sh — Remove Linuwu-Sense GUI from Arch Linux
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

if [[ "$EUID" -ne 0 ]]; then
    echo -e "${RED}[✗]${NC} Please run as root: sudo ./uninstall.sh"
    exit 1
fi

echo -e "${GREEN}[+]${NC} Removing Linuwu-Sense GUI..."

rm -rf  /usr/lib/linuwu-sense-gui
rm -f   /usr/bin/linuwu-sense-gui
rm -f   /usr/share/applications/linuwu-sense-gui.desktop
rm -f   /usr/share/polkit-1/actions/org.linuwu-sense.gui.policy

update-desktop-database /usr/share/applications 2>/dev/null || true

echo -e "${GREEN}✔ Uninstalled successfully.${NC}"
