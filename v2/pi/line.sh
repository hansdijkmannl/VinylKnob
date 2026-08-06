#!/usr/bin/env bash
#
# Find the receiver's line feeds and see which one carries your turntable.
#
# Denon and Marantz receivers digitise their analog inputs and serve each one as
# a plain HTTP stream — the mechanism behind sharing an input with HEOS
# speakers. That is what this device listens on instead of a microphone, so this
# script answers the two questions that decide whether it will work: which
# inputs does your receiver offer, and does the turntable one have signal on it.
#
# Put a record on before you run it. Performed rather than described.
#
#   ./line.sh [receiver address]
#
set -euo pipefail

AVR="${1:-}"
if [ -z "$AVR" ]; then
    # The panel knows the address; it needs it for telnet.
    AVR=$(curl -s --max-time 4 "http://127.0.0.1:8791/panel/api/settings" \
          | sed -n 's/.*"avrHost":"\([^"]*\)".*/\1/p') || true
fi
if [ -z "$AVR" ]; then
    echo "Which receiver? Give its address: ./line.sh 192.168.1.60" >&2
    exit 1
fi
echo "== receiver $AVR =="

# The receiver serves one client at a time, and in normal operation that client
# is the ears. Without stepping aside every reading below is a scrap of a
# stream someone else is holding — which reads as "no signal anywhere" and
# sends you looking for a fault that is not there.
STOPPED=""
if systemctl is-active --quiet vinylknob-listen 2>/dev/null; then
    echo "   (pausing the ears; they hold the one connection the receiver allows)"
    sudo systemctl stop vinylknob-listen
    STOPPED=yes
fi
restore() {
    if [ -n "$STOPPED" ]; then sudo systemctl start vinylknob-listen; fi
}
trap restore EXIT

# The list comes from the receiver's own UPnP directory rather than from a table
# in here: the path is the protocol name, but which inputs exist and what you
# have named them differs per unit.
SOAP='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1"><ObjectID>inputs/</ObjectID><BrowseFlag>BrowseDirectChildren</BrowseFlag><Filter>*</Filter><StartingIndex>0</StartingIndex><RequestedCount>50</RequestedCount><SortCriteria></SortCriteria></u:Browse></s:Body></s:Envelope>'
INPUTS=$(curl -s --max-time 8 \
    -H 'Content-Type: text/xml; charset="utf-8"' \
    -H 'SOAPACTION: "urn:schemas-upnp-org:service:ContentDirectory:1#Browse"' \
    --data "$SOAP" \
    "http://$AVR:60006/upnp/control/ams_dvc/ContentDirectory" \
    | sed -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&quot;/"/g' \
    | tr '<' '\n' \
    | sed -n 's|^res[^>]*>http://[^/]*/analoginput/analog/analog/0/\(.*\)|\1|p')

if [ -z "$INPUTS" ]; then
    echo
    echo "This receiver does not offer its inputs over HTTP."
    echo "That is the whole basis for listening without a microphone, so on this"
    echo "model the device cannot recognise records. Everything else works."
    exit 2
fi

echo
echo "== inputs, with the level over three seconds =="
echo "   (put a record on; the turntable input should stand out from the rest)"
echo
for name in $INPUTS; do
    OUT=$(mktemp)
    curl -s --max-time 4 -o "$OUT" \
        "http://$AVR:8015/analoginput/analog/analog/0/$name" || true
    python3 - "$OUT" "$name" <<'PY'
import array, math, sys
path, name = sys.argv[1], sys.argv[2]
raw = open(path, "rb").read()
if len(raw) < 4000:
    print(f"  {name:<14} no data")
else:
    a = array.array("h")
    a.frombytes(raw[:len(raw) // 2 * 2])
    peak = max(abs(v) for v in a) / 32768
    rms = (sum(v * v for v in a) / len(a)) ** 0.5 / 32768
    db = 20 * math.log10(rms) if rms > 1e-9 else -99.0
    mark = "  <- signal" if db > -60 else ""
    print(f"  {name:<14} {len(raw)/176400:4.1f}s  peak {peak:.4f}  {db:6.1f} dBFS{mark}")
PY
    rm -f "$OUT"
done

echo
echo "Put the one with signal in LINE_INPUT in vinylknob-listen.service."
echo "Nothing above -60 dBFS with a record playing? Then the receiver is not on"
echo "the turntable, or that input is not one it digitises — only the analog"
echo "inputs are, so anything arriving over HDMI stays silent here."
