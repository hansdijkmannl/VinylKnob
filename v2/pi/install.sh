#!/usr/bin/env bash
#
# Set the brain and the ears up on a fresh Raspberry Pi OS Lite (64-bit).
# Running it more than once is fine; it only overwrites what has to differ.
#
#   git clone <this repo> ~/vinylknob        (or rsync from your machine)
#   cd ~/vinylknob/v2/pi && ./install.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WHO="${SUDO_USER:-$USER}"
VENV="$ROOT/.venv"

echo "==> VinylKnob at $ROOT, as user $WHO"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "==> Packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential \
    libsndfile1 avahi-daemon \
    ffmpeg

# ffmpeg is not optional: shazamio has pydub convert the recording before
# sending it, and without ffmpeg that fails silently — you end up with nothing
# but unrecognised records in the queue and no sign of an error anywhere.

# numpy and scipy from apt rather than pip: building scipy on a Pi 5 with 1 GB
# takes over an hour and barely fits in memory.
sudo apt-get install -y python3-numpy python3-scipy

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
if [ ! -d "$VENV" ]; then
    echo "==> Virtualenv (with the system numpy included)"
    python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
echo "==> Python packages"
# Two lists, one virtualenv: the brain's recogniser and the ears' Apple TV
# client. pyatv used to be missing here and was only ever installed by hand,
# which nobody noticed until the venv was rebuilt and the ears would not start.
"$VENV/bin/pip" install --quiet -r "$ROOT/v2/brain/requirements.txt"
"$VENV/bin/pip" install --quiet -r "$ROOT/v2/pi/requirements.txt"

# Python 3.13 removed the audioop module from the standard library, and pydub —
# which shazamio leans on — imports it in three of its files. Raspberry Pi OS on
# Debian 13 ships 3.13, so this is not an edge case but the normal situation.
# audioop-lts is the official continuation.
if "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,13) else 1)'; then
    echo "==> Python 3.13+: adding audioop-lts (pydub needs it)"
    "$VENV/bin/pip" install --quiet audioop-lts
fi

PYV=$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "    Python $PYV"

# Check right away that recognition actually imports. Better to fail here with a
# clear message than later on the first record.
if "$VENV/bin/python" -c 'import shazamio' 2>/dev/null; then
    echo "    shazamio imports"
else
    echo "    WARNING: shazamio does not import. For the error, run:"
    echo "            $VENV/bin/python -c 'import shazamio'"
fi

# ---------------------------------------------------------------------------
# 3. The sound
# ---------------------------------------------------------------------------
# There is no microphone to find. The receiver digitises its own analog inputs
# and serves them over HTTP; the ears read the turntable one. Which input that
# is cannot be settled here, because it needs a record playing to tell the
# inputs apart — ./line.sh does that when you are ready.
echo "==> Sound comes from the receiver's line feed; run ./line.sh to check it"

# ---------------------------------------------------------------------------
# 4. Services
# ---------------------------------------------------------------------------
echo "==> systemd"
for unit in vinylknob-brain vinylknob-listen vinylknob-sync; do
    sed -e "s|__ROOT__|$ROOT|g" \
        -e "s|__USER__|$WHO|g" \
        "$ROOT/v2/pi/$unit.service" | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now vinylknob-brain vinylknob-listen

# The timer separately: it belongs to the .service but is enabled on its own.
sudo install -m 644 "$ROOT/v2/pi/vinylknob-sync.timer" /etc/systemd/system/
sudo systemctl enable --now vinylknob-sync.timer

# ---------------------------------------------------------------------------
# 5. Sparing the SD card
# ---------------------------------------------------------------------------
# This device runs day and night and would otherwise write logs continuously to
# a card that cannot take it. See ../BOM.md on High Endurance cards.
echo "==> Limiting wear"
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=32M\n' \
    | sudo tee /etc/systemd/journald.conf.d/vinylknob.conf >/dev/null
sudo systemctl restart systemd-journald
if [ -f /etc/dphys-swapfile ]; then
    sudo dphys-swapfile swapoff 2>/dev/null || true
    sudo systemctl disable dphys-swapfile 2>/dev/null || true
fi

echo
echo "==> Done."
echo "    Web interface : http://$(hostname).local"
echo "    Raw levels    : http://$(hostname).local/status"
echo "    Logs          : journalctl -u vinylknob-brain -u vinylknob-listen -f"
echo
echo "    Put a record on and run ./line.sh to see which input carries it."
