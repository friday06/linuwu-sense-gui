# Linuwu Sense GUI
**A sleek, native GNOME/GTK4 frontend for the `linuwu_sense` kernel module.**

Linuwu Sense GUI provides elegant, system-integrated hardware controls for Acer Predator and Nitro series laptops. Written in Python with GTK4 and Libadwaita, it seamlessly blends into the modern Linux desktop, syncing directly with your system's `power-profiles-daemon`.



## Features

- **Thermal & Performance Control:** Easily switch between `low-power`, `quiet`, `balanced`, and `balanced-performance` modes.
- **Desktop Sync:** Seamlessly integrates with GNOME and KDE Quick Settings via `power-profiles-daemon`.
- **Smart CPU Limiting:** Automatically caps CPU frequencies to save battery based on your selected thermal mode.
- **Live Hardware Monitoring:** View beautiful real-time metrics and historical graphs for CPU/GPU temperatures, clocks, and memory loads.
- **Battery Protection:** Toggle 80% charge limits to preserve long-term battery health, and perform deep recalibrations.
- **Advanced Keyboard RGB:** Customize the 4-zone RGB keyboard with static colors, breathing, wave, and pulse effects.



## Installation

### Arch Linux (AUR)

If you are using Arch Linux, you can install the required kernel module dependencies directly from the AUR:

```bash
paru -S linuwu-sense-dkms
```

### Manual Installation

Clone the repository and run the installer script:

```bash
git clone https://github.com/friday06/linuwu-sense-gui.git
cd linuwu-sense-gui
sudo ./install.sh
```

**Requirements:**
- `python3`, `python3-gobject`, `gtk4`, `libadwaita`
- `power-profiles-daemon` (optional but highly recommended for DE integration)
- The [Linuwu-Sense kernel module](https://github.com/0x7375646F/Linuwu-Sense)

## Usage

You can launch the application from your desktop launcher ("linuwu sense") or by running:

```bash
linuwu-sense-gui
```

### Note on Permissions
The installer automatically creates an `acer-nitro` group and grants it permission to read and write to the hardware's sysfs nodes. **You must log out and back in** after installation to apply these group privileges. No `sudo` or `pkexec` is required to run the application!

## Architecture

The application uses a clean MVC-style architecture:
- `views/`: Contains the GTK4/Libadwaita UI components (Pages, Windows, Dialogs).
- `backend/`: Contains the `sysfs_backend.py` which directly interfaces with the kernel module, and `device_detector.py` for feature discovery.
- `config/`: Application constants and hardware scaling presets.

## License
Licensed under the GPL-3.0 License.
