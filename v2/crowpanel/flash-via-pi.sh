#!/usr/bin/env bash
#
# Flash the CrowPanel while it stays plugged into the Pi, from your desktop.
#
# This works because the ESP32-S3 has native USB: esptool puts the chip into
# the bootloader over that same connection, so the BOOT button is only needed
# if the firmware already on it has broken the USB stack.
#
#   ./flash-via-pi.sh                 # uses $KNOB_PI, or asks
#   ./flash-via-pi.sh pi@knob.local   # or name the host outright
#
# Set KNOB_PI in your shell to stop repeating yourself:
#
#   export KNOB_PI=pi@knob.local
#
set -euo pipefail

TARGET="${1:-${KNOB_PI:-}}"
if [ -z "$TARGET" ]; then
  echo "Which Pi is the panel plugged into? Give it as user@host, or set" >&2
  echo "KNOB_PI in your shell. Example: ./flash-via-pi.sh pi@knob.local" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIO="${PIO:-$HOME/.platformio-venv/bin/pio}"
BUILD="$HOME/.platformio/build/crowpanel/crowpanel"
BOOTAPP="$(find "$HOME/.platformio/packages/framework-arduinoespressif32" \
           -name boot_app0.bin 2>/dev/null | head -1)"

# Where the project lives on the Pi. The installer puts it in your home
# directory; override if you moved it.
REMOTE="${KNOB_PI_PATH:-vinylknob}"

echo "==> Building"
cd "$HERE" && "$PIO" run -e crowpanel

echo "==> Copying to $TARGET"
ssh "$TARGET" 'mkdir -p ~/panel-firmware'
scp -q "$BUILD/bootloader.bin" "$BUILD/partitions.bin" "$BUILD/firmware.bin" \
       "$BOOTAPP" "$TARGET:panel-firmware/"

# esptool lives in the Pi's virtualenv, and it is the one thing there that is
# not needed to *run* anything — so a rebuilt venv comes back without it and
# flashing stops working for no obvious reason. Put it there rather than say so.
ssh "$TARGET" "~/$REMOTE/.venv/bin/python -c 'import esptool' 2>/dev/null || \
  ~/$REMOTE/.venv/bin/pip install --quiet esptool"

echo "==> Flashing over /dev/ttyACM0"
ssh "$TARGET" "~/$REMOTE/.venv/bin/python -m esptool --chip esp32s3 \
  --port /dev/ttyACM0 --baud 921600 \
  --before default_reset --after hard_reset write_flash \
  -z --flash_mode dio --flash_freq 80m --flash_size 16MB \
  0x0     panel-firmware/bootloader.bin \
  0x8000  panel-firmware/partitions.bin \
  0xe000  panel-firmware/boot_app0.bin \
  0x10000 panel-firmware/firmware.bin"

echo "==> Done. To watch it boot:"
echo "    ssh $TARGET 'cat /dev/ttyACM0'"
