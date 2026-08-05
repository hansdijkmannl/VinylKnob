#!/usr/bin/env bash
#
# Het CrowPanel flashen terwijl het aan de Pi hangt, vanaf je Mac.
#
# Kan omdat de ESP32-S3 native USB heeft: esptool zet de chip zelf in de
# bootloader via de USB-verbinding, dus de BOOT-knop is alleen nodig als er
# firmware op staat die de USB-stack sloopt.
#
#   ./flash-via-pi.sh [gebruiker@ip]
#
set -euo pipefail

DOEL="${1:-pi@192.168.1.175}"
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIO="${PIO:-$HOME/.platformio-venv/bin/pio}"
BUILD="$HOME/.platformio/build/crowpanel/crowpanel"
BOOTAPP="$(find "$HOME/.platformio/packages/framework-arduinoespressif32" \
           -name boot_app0.bin 2>/dev/null | head -1)"

echo "==> Bouwen"
cd "$HIER" && "$PIO" run -e crowpanel

echo "==> Overzetten naar $DOEL"
ssh "$DOEL" 'mkdir -p ~/paneel-firmware'
scp -q "$BUILD/bootloader.bin" "$BUILD/partitions.bin" "$BUILD/firmware.bin" \
       "$BOOTAPP" "$DOEL:paneel-firmware/"

echo "==> Flashen over /dev/ttyACM0"
ssh "$DOEL" '~/marantzknob/.venv/bin/python -m esptool --chip esp32s3 \
  --port /dev/ttyACM0 --baud 921600 \
  --before default_reset --after hard_reset write_flash \
  -z --flash_mode dio --flash_freq 80m --flash_size 16MB \
  0x0     paneel-firmware/bootloader.bin \
  0x8000  paneel-firmware/partitions.bin \
  0xe000  paneel-firmware/boot_app0.bin \
  0x10000 paneel-firmware/firmware.bin'

echo "==> Klaar. Meekijken kan met:"
echo "    ssh $DOEL 'cat /dev/ttyACM0'"
