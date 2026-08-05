#!/usr/bin/env bash
#
# De vijfminutencontrole uit ../BOM.md, uitgevoerd in plaats van beschreven.
#
# Waar het om gaat: een CM108/CM119-dongeltje heeft de automatische
# versterkingsregeling als ALSA-schakelaar, en die zet je uit. Zit die
# schakelaar er niet, dan doet de firmware zelf iets aan het signaal en is het
# de verkeerde microfoon voor dit apparaat — een pompende AGC sloopt
# vingerafdrukken, een lage versterking niet.
#
#   ./microfoon.sh [kaartnummer]
#
set -euo pipefail

KAART="${1:-$(arecord -l 2>/dev/null | awk -F'[ :]' '/^card /{print $2; exit}')}"
if [ -z "$KAART" ]; then
    echo "Geen opnameapparaat gevonden (arecord -l is leeg)."
    exit 1
fi

echo "== kaart $KAART =="
arecord -l | sed -n "/^card $KAART/,/^card [^$KAART]/p" | head -3

REGELAARS=$(amixer -c "$KAART" controls 2>/dev/null || true)
if [ -z "$REGELAARS" ]; then
    echo
    echo "LET OP: deze kaart heeft geen enkele regelaar."
    echo "Dat betekent dat de firmware zelf aan het signaal zit en je er niets"
    echo "aan kunt veranderen. Voor herkenning is dat de verkeerde microfoon."
    exit 2
fi
echo
echo "== regelaars =="
echo "$REGELAARS"

echo
if echo "$REGELAARS" | grep -qi "Auto Gain Control"; then
    echo "-> Auto Gain Control gevonden, wordt uitgezet."
    amixer -c "$KAART" sset 'Auto Gain Control' off >/dev/null && echo "   uit."
else
    echo "-> Geen 'Auto Gain Control'. Dat kan goed zijn (sommige chips noemen"
    echo "   het anders) maar controleer het even in de lijst hierboven."
fi

if amixer -c "$KAART" sget 'Mic' >/dev/null 2>&1; then
    amixer -c "$KAART" sset 'Mic' 100% >/dev/null && echo "-> Mic op 100%."
    # Zonder dit staat hij na een herstart weer op de fabrieksstand.
    sudo alsactl store 2>/dev/null && echo "-> Mixerstand bewaard."
fi

echo
echo "== proefopname van 5 seconden =="
UIT=$(mktemp /tmp/mictest-XXXX.wav)
arecord -D "plughw:${KAART},0" -f S16_LE -r 44100 -c 1 -d 5 "$UIT" 2>/dev/null
echo "Opgeslagen in $UIT"

# Even kijken of er werkelijk signaal in zit; een stille opname is de meest
# voorkomende uitkomst van een verkeerd gekozen apparaat.
python3 - "$UIT" <<'PY'
import array, sys, wave
with wave.open(sys.argv[1]) as w:
    raw = w.readframes(w.getnframes())
mon = array.array("h")
mon.frombytes(raw[:len(raw) // 2 * 2])
piek = max(abs(v) for v in mon) / 32768
rms = (sum(v * v for v in mon) / len(mon)) ** 0.5 / 32768
print(f"piek {piek:.3f}   rms {rms:.4f}")
if piek < 0.002:
    print("-> Vrijwel stil. Verkeerd apparaat, of de microfoon staat gedempt.")
elif piek > 0.99:
    print("-> Overstuurd. Zet 'Mic' een stuk lager.")
else:
    print("-> Ziet er bruikbaar uit.")
PY
