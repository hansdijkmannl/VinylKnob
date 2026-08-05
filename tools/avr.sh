#!/usr/bin/env bash
# Check by hand whether the receiver accepts telnet commands.
#
#   ./avr.sh 192.168.1.60 SIPHONO
#   ./avr.sh 192.168.1.60 MV?
#   ./avr.sh 192.168.1.60          # interactive: type commands, press enter
#
# Note: the receiver accepts exactly ONE telnet session. If the panel is
# already running this will not connect until you take it off the network.

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
