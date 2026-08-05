#!/usr/bin/env bash
# Snel testen of de SR7015 telnet-commando's aanneemt, vanaf je Mac.
#
#   ./avr.sh 192.168.1.60 SIPHONO
#   ./avr.sh 192.168.1.60 MV?
#   ./avr.sh 192.168.1.60          # interactief, typ commando's + enter
#
# Let op: de receiver accepteert maar EEN telnet-sessie. Draait de firmware
# al, dan werkt dit niet tot je die even van het net haalt.

set -euo pipefail

HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "gebruik: $0 <ip-van-avr> [commando]" >&2
  exit 1
fi

if [[ $# -ge 2 ]]; then
  printf '%s\r' "$2" | nc -w 2 "$HOST" 23
  echo
else
  echo "Verbonden met $HOST:23 - typ commando's (bv. MV?, SIPHONO). Ctrl-C stopt."
  nc "$HOST" 23
fi
