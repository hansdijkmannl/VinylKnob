#!/usr/bin/env bash
#
# Zet het brein en de oren op een verse Raspberry Pi OS Lite (64-bits).
# Meerdere keren draaien mag; hij overschrijft alleen wat af moet wijken.
#
#   git clone <deze map> /opt/marantzknob      (of rsync vanaf je Mac)
#   cd /opt/marantzknob/luxe/pi && ./installeer.sh
#
set -euo pipefail

WORTEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEBRUIKER="${SUDO_USER:-$USER}"
VENV="$WORTEL/.venv"

echo "==> MarantzKnob op $WORTEL, als gebruiker $GEBRUIKER"

# ---------------------------------------------------------------------------
# 1. Systeempakketten
# ---------------------------------------------------------------------------
echo "==> Pakketten"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential \
    alsa-utils libsndfile1 avahi-daemon \
    ffmpeg

# ffmpeg is geen luxe: shazamio laat pydub de opname omzetten voor hij hem
# opstuurt, en zonder ffmpeg mislukt dat stil — je krijgt dan alleen maar
# onherkende platen in de wachtrij, zonder dat er iets op een fout lijkt.

# numpy en scipy uit apt in plaats van uit pip: op een Pi 5 met 1 GB duurt het
# zelf bouwen van scipy ruim een uur en is er nauwelijks genoeg geheugen voor.
sudo apt-get install -y python3-numpy python3-scipy

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
if [ ! -d "$VENV" ]; then
    echo "==> Virtuele omgeving (met de systeem-numpy erbij)"
    python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
echo "==> Python-pakketten"
"$VENV/bin/pip" install --quiet -r "$WORTEL/luxe/brein/requirements.txt"

# Python 3.13 heeft de audioop-module uit de standaardbibliotheek gesloopt, en
# pydub — waar shazamio op leunt — importeert die in drie van zijn bestanden.
# Raspberry Pi OS op Debian 13 (trixie) levert 3.13, dus daar is dit geen
# randgeval maar de standaardsituatie. audioop-lts is de officiele voortzetting.
if "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,13) else 1)'; then
    echo "==> Python 3.13+: audioop-lts erbij (pydub kan niet zonder)"
    "$VENV/bin/pip" install --quiet audioop-lts
fi

PYV=$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "    Python $PYV"

# Meteen controleren of de herkenning werkelijk importeert. Beter hier falen met
# een duidelijke melding dan straks bij de eerste plaat.
if "$VENV/bin/python" -c 'import shazamio' 2>/dev/null; then
    echo "    shazamio importeert"
else
    echo "    LET OP: shazamio importeert niet. Draai voor de melding:"
    echo "            $VENV/bin/python -c 'import shazamio'"
fi

# ---------------------------------------------------------------------------
# 3. Microfoon vinden
# ---------------------------------------------------------------------------
echo "==> Microfoon"
KAART=$(arecord -l 2>/dev/null | awk -F'[ :]' '/^card /{print $2; exit}')
if [ -z "$KAART" ]; then
    echo "    GEEN opnameapparaat gevonden. Zit de USB-microfoon erin?"
    echo "    De dienst wordt wel geinstalleerd; corrigeer MIC_DEVICE later."
    MIC="plughw:1,0"
else
    MIC="plughw:${KAART},0"
    echo "    kaart $KAART -> $MIC"
    "$WORTEL/luxe/pi/microfoon.sh" "$KAART" || true
fi

# ---------------------------------------------------------------------------
# 4. Diensten
# ---------------------------------------------------------------------------
echo "==> systemd"
for dienst in marantzknob-brein marantzknob-luister marantzknob-sync; do
    sed -e "s|__WORTEL__|$WORTEL|g" \
        -e "s|__GEBRUIKER__|$GEBRUIKER|g" \
        -e "s|__MIC__|$MIC|g" \
        "$WORTEL/luxe/pi/$dienst.service" | sudo tee "/etc/systemd/system/$dienst.service" >/dev/null
done
sudo usermod -aG audio "$GEBRUIKER"
sudo systemctl daemon-reload
sudo systemctl enable --now marantzknob-brein marantzknob-luister

# De timer los: die hoort bij .service maar wordt apart ingeschakeld.
sudo install -m 644 "$WORTEL/luxe/pi/marantzknob-sync.timer" /etc/systemd/system/
sudo systemctl enable --now marantzknob-sync.timer

# ---------------------------------------------------------------------------
# 5. De SD-kaart sparen
# ---------------------------------------------------------------------------
# Dit apparaat staat dag en nacht aan en schrijft anders continu logs naar een
# kaart die daar niet tegen kan. Zie ../BOM.md over High Endurance-kaarten.
echo "==> Slijtage beperken"
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=32M\n' \
    | sudo tee /etc/systemd/journald.conf.d/marantzknob.conf >/dev/null
sudo systemctl restart systemd-journald
if [ -f /etc/dphys-swapfile ]; then
    sudo dphys-swapfile swapoff 2>/dev/null || true
    sudo systemctl disable dphys-swapfile 2>/dev/null || true
fi

echo
echo "==> Klaar."
echo "    Web interface : http://$(hostname).local"
echo "    Raw levels    : http://$(hostname).local/status"
echo "    Logs          : journalctl -u marantzknob-brein -u marantzknob-luister -f"
echo
echo "    Je bent net aan de groep 'audio' toegevoegd; log een keer uit en in"
echo "    als je zelf arecord wilt draaien."
