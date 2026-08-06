#!/usr/bin/env bash
#
# The five-minute check from ../BOM.md, performed rather than described.
#
# The point: a CM108/CM119 dongle exposes automatic gain control as an ALSA
# switch, and you turn it off. If that switch is not there, the firmware is
# doing something to the signal itself and it is the wrong microphone for this
# device — a pumping AGC ruins fingerprints, low gain does not.
#
#   ./microphone.sh [card number]
#
set -euo pipefail

CARD="${1:-$(arecord -l 2>/dev/null | awk -F'[ :]' '/^card /{print $2; exit}')}"
if [ -z "$CARD" ]; then
    echo "No recording device found (arecord -l is empty)."
    exit 1
fi

echo "== card $CARD =="
arecord -l | sed -n "/^card $CARD/,/^card [^$CARD]/p" | head -3

CONTROLS=$(amixer -c "$CARD" controls 2>/dev/null || true)
if [ -z "$CONTROLS" ]; then
    echo
    echo "WARNING: this card has no controls at all."
    echo "That means the firmware is processing the signal and you cannot stop"
    echo "it. For recognition, that is the wrong microphone."
    exit 2
fi
echo
echo "== controls =="
echo "$CONTROLS"

echo
if echo "$CONTROLS" | grep -qi "Auto Gain Control"; then
    echo "-> Auto Gain Control found, switching it off."
    amixer -c "$CARD" sset 'Auto Gain Control' off >/dev/null && echo "   off."
else
    echo "-> No 'Auto Gain Control'. That may be fine (some chips name it"
    echo "   differently) but check the list above."
fi

if amixer -c "$CARD" sget 'Mic' >/dev/null 2>&1; then
    amixer -c "$CARD" sset 'Mic' 100% >/dev/null && echo "-> Mic at 100%."
    # Without this it is back at the factory setting after a reboot.
    sudo alsactl store 2>/dev/null && echo "-> Mixer settings stored."
fi

echo
echo "== 5-second test recording =="
OUT=$(mktemp /tmp/mictest-XXXX.wav)
arecord -D "plughw:${CARD},0" -f S16_LE -r 44100 -c 1 -d 5 "$OUT" 2>/dev/null
echo "Saved to $OUT"

# Check there is actually signal in it; a silent recording is the most common
# outcome of picking the wrong device.
python3 - "$OUT" <<'PY'
import array, sys, wave
with wave.open(sys.argv[1]) as w:
    raw = w.readframes(w.getnframes())
mono = array.array("h")
mono.frombytes(raw[:len(raw) // 2 * 2])
peak = max(abs(v) for v in mono) / 32768
rms = (sum(v * v for v in mono) / len(mono)) ** 0.5 / 32768
print(f"peak {peak:.3f}   rms {rms:.4f}")
if peak < 0.002:
    print("-> Near silent. Wrong device, or the microphone is muted.")
elif peak > 0.99:
    print("-> Clipping. Turn 'Mic' down a good deal.")
else:
    print("-> Looks usable.")
PY
