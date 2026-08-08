#!/usr/bin/env bash
#
# Check the volume lattice on this machine, against the function that actually
# ships. Nothing here touches the panel; it is arithmetic on a host compiler.
#
#     v2/crowpanel/test/run.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(mktemp -d)"

# The real function, lifted out of settings.cpp, so this cannot end up testing a
# copy that has drifted from what runs on the device.
python3 - "$HERE/../src/settings.cpp" "$HERE/volume_lattice.cpp" "$OUT/t.cpp" <<'PY'
import pathlib, sys
src, test, out = (pathlib.Path(p) for p in sys.argv[1:4])
text = src.read_text()
mark = "int16_t volumeSnap(int16_t halfSteps, int direction, uint8_t lattice) {"
start = text.index(mark)
end = text.index("\n}\n", start) + 3
out.write_text(test.read_text().replace("__VOLUME_SNAP__", text[start:end]))
PY

c++ -std=c++17 -O1 -o "$OUT/t" "$OUT/t.cpp"
"$OUT/t"
