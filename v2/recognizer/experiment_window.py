"""
Hoeveel van een plaatkant moet je vastleggen?

De verwarring die dit beantwoordt: Shazam heeft inderdaad maar ~10 seconden
nodig, maar dat is de lengte van de *opname die je maakt*, niet van wat er in de
database staat. Shazam heeft het hele nummer vastgelegd. Daarom kun je hem
midden in een liedje aanzetten.

Leg je alleen het begin van een kant vast, dan kun je alleen herkennen als de
naald daar staat. Bij een plaat die je net opzet klopt dat, maar niet als je de
kamer binnenloopt terwijl track vier speelt.

Een kant van 20 minuten volledig vastleggen kost bij volle dichtheid ~635.000
hashes. Vierhonderd albums, twee kanten: een half miljard, oftewel 4 GB in het
geheugen. Dat past niet op een Pi. Dit script meet de twee manieren om te
snoeien, met een kant van vijf minuten als proefkonijn:

    venster    alleen het begin vastleggen
    uitdunnen  de hele kant, maar een op de N hashes bewaren

    python experiment_window.py
"""

from __future__ import annotations

import os
import tempfile
import time

from fingerprint import SAMPLE_RATE
from store import Store
from test_roundtrip import add_surface_noise, make_side

SIDE_SECONDS = 300.0        # proxy voor een echte kant; 20 min duurt te lang
N_SIDES = 5
TARGET = 2
QUERY_SECONDS = 15.0

# Waar de naald staat als we gaan luisteren.
QUERY_AT = (10.0, 60.0, 200.0)

REAL_SIDE_SECONDS = 1200.0  # 20 minuten, voor het doorrekenen naar de praktijk
ALBUMS = 400
BYTES_PER_HASH = 8          # gepakte int32-hash + offset + kant-id


def main() -> None:
    print(f"{N_SIDES} kanten van {SIDE_SECONDS:.0f} s aanmaken...")
    music = {i: make_side(4242 + i, seconds=SIDE_SECONDS) for i in range(N_SIDES)}

    variants = [
        ("eerste 45 s",        45.0,  1),
        ("eerste 90 s",        90.0,  1),
        ("hele kant",          None,  1),
        ("hele kant, 1 op 4",  None,  4),
        ("hele kant, 1 op 8",  None,  8),
        ("hele kant, 1 op 16", None, 16),
    ]

    print(f"\n{'variant':<20} {'h/s':>6} {'RAM 400 alb':>12}  "
          + "  ".join(f"{f'@{t:.0f}s':>12}" for t in QUERY_AT))
    print("-" * 80)

    for name, seconds, keep in variants:
        path = os.path.join(tempfile.mkdtemp(), "w.db")
        store = Store(path)
        for i in range(N_SIDES):
            reference = add_surface_noise(music[i], 45.0, seed=600 + i)
            store.enroll(reference, label=f"Plaat {i}", seconds=seconds,
                         keep_one_in=keep)

        covered = seconds if seconds is not None else SIDE_SECONDS
        per_second = store.hash_count() / N_SIDES / covered
        ram = per_second * REAL_SIDE_SECONDS * 2 * ALBUMS * BYTES_PER_HASH / 1e6

        cells = []
        for at in QUERY_AT:
            excerpt = music[TARGET][int(at * SAMPLE_RATE):
                                    int((at + QUERY_SECONDS) * SAMPLE_RATE)]
            query = add_surface_noise(excerpt, 30.0, seed=98765)
            t0 = time.time()
            results = store.identify(query)
            elapsed = time.time() - t0

            if not results or results[0].side_id != TARGET + 1:
                cells.append(f"{'GEMIST':>12}")
                continue
            best = results[0]
            runner = results[1].score if len(results) > 1 else 0
            margin = best.score / runner if runner else float("inf")
            flag = "" if (best.score >= 20 and margin >= 4) else "?"
            cells.append(f"{best.score:>6}/{margin:>4.1f}x{flag}".rjust(12))

        # De dekking klopt alleen als het venster de hele kant beslaat.
        note = "" if seconds is None else f"  (dekt {seconds:.0f} van {SIDE_SECONDS:.0f} s)"
        print(f"{name:<20} {per_second:>6.0f} {ram:>10.0f} MB  "
              + "  ".join(cells) + note)
        store.close()

    print("\nscore/marge per luisterpositie; GEMIST = verkeerde of geen plaat.")
    print(f"RAM is doorgerekend naar {ALBUMS} albums met kanten van "
          f"{REAL_SIDE_SECONDS / 60:.0f} minuten.")


if __name__ == "__main__":
    main()
