"""
How much of a record side do you have to enrol?

The confusion this answers: Shazam does indeed need only ~10 seconds, but that
is the length of the *recording you make*, not of what is in the database.
Shazam has the whole track enrolled. That is why you can start it in the middle
of a song.

Enrol only the beginning of a side and you can only recognise it while the
needle is there. For a record you have just put on that is true, but not when
you walk into the room while track four is playing.

Enrolling a 20-minute side in full costs ~635,000 hashes at full density. Four
hundred albums, two sides each: half a billion, which is 4 GB in memory. That
does not fit on a Pi. This script measures the two ways of pruning, with a
five-minute side as the guinea pig:

    window     enrol only the beginning
    thinning   the whole side, but keep one hash in N

    python experiment_window.py
"""

from __future__ import annotations

import os
import tempfile
import time

from fingerprint import SAMPLE_RATE
from store import Store
from test_roundtrip import add_surface_noise, make_side

SIDE_SECONDS = 300.0        # proxy for a real side; 20 min takes too long
N_SIDES = 5
TARGET = 2
QUERY_SECONDS = 15.0

# Where the needle is when we start listening.
QUERY_AT = (10.0, 60.0, 200.0)

REAL_SIDE_SECONDS = 1200.0  # 20 minutes, for extrapolating to practice
ALBUMS = 400
BYTES_PER_HASH = 8          # packed int32 hash + offset + side id


def main() -> None:
    print(f"Making {N_SIDES} sides of {SIDE_SECONDS:.0f} s...")
    music = {i: make_side(4242 + i, seconds=SIDE_SECONDS) for i in range(N_SIDES)}

    variants = [
        ("first 45 s",          45.0,  1),
        ("first 90 s",          90.0,  1),
        ("whole side",          None,  1),
        ("whole side, 1 in 4",  None,  4),
        ("whole side, 1 in 8",  None,  8),
        ("whole side, 1 in 16", None, 16),
    ]

    print(f"\n{'variant':<20} {'h/s':>6} {'RAM 400 alb':>12}  "
          + "  ".join(f"{f'@{t:.0f}s':>12}" for t in QUERY_AT))
    print("-" * 80)

    for name, seconds, keep in variants:
        path = os.path.join(tempfile.mkdtemp(), "w.db")
        store = Store(path)
        for i in range(N_SIDES):
            reference = add_surface_noise(music[i], 45.0, seed=600 + i)
            store.enroll(reference, label=f"Record {i}", seconds=seconds,
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
                cells.append(f"{'MISS':>12}")
                continue
            best = results[0]
            runner = results[1].score if len(results) > 1 else 0
            margin = best.score / runner if runner else float("inf")
            flag = "" if (best.score >= 20 and margin >= 4) else "?"
            cells.append(f"{best.score:>6}/{margin:>4.1f}x{flag}".rjust(12))

        # The coverage only holds when the window spans the whole side.
        note = "" if seconds is None else f"  (covers {seconds:.0f} of {SIDE_SECONDS:.0f} s)"
        print(f"{name:<20} {per_second:>6.0f} {ram:>10.0f} MB  "
              + "  ".join(cells) + note)
        store.close()

    print("\nscore/margin per listening position; MISS = wrong record or none.")
    print(f"RAM is extrapolated to {ALBUMS} albums with sides of "
          f"{REAL_SIDE_SECONDS / 60:.0f} minutes.")


if __name__ == "__main__":
    main()
