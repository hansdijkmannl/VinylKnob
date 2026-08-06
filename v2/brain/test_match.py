"""
What a recognition service says, against what is on your shelf.

    python test_match.py

Every case in here is one that went wrong on a real shelf, or one that a rule
was written for and must keep working. The two are the same list, because each
rule that fixed something also broke something else — which is the reason this
file exists at all.

The collection below is invented, but the shapes are not:

  * an artist with a compilation *and* the album a track really comes from
  * an album whose title is nothing but compilation boilerplate
  * an album with a one-word generic title ("Live")
  * two artists owning a record with the same generic title
  * an album title that is a substring of the single a service names
"""

from __future__ import annotations

import os
import sys
import tempfile

from store import Store

SHELF = [
    ("1", "Robbie Williams", "Swing When You're Winning"),
    ("2", "Robbie Williams", "Greatest Hits"),
    ("3", "Robbie Williams", "Life Thru A Lens"),
    ("4", "Joe Cocker", "Greatest Hits"),
    ("5", "Hans Zimmer", "Live"),
    ("6", "Hans Zimmer", "Gladiator (Music From The Motion Picture)"),
    ("7", "Moby", "Reprise"),
    ("8", "The Greatest Showman Cast", "The Greatest Showman (Original Motion Picture Soundtrack)"),
]

CASES = [
    # (artist a service reports, album it reports, the title we must land on)
    ("Robbie Williams", "Swing When You're Winning", "Swing When You're Winning",
     "the plain case"),

    ("Robbie Williams", "In And Out Of Consciousness: Greatest Hits 1990 - 2010", None,
     "Shazam named a compilation for a track off Swing When You're Winning. "
     "'Greatest Hits' sits inside that title and is a record on this shelf, so "
     "containment used to hand back the wrong sleeve. Better to admit we do not "
     "know and let it be linked by hand"),

    ("Robbie Williams", "Greatest Hits", "Greatest Hits",
     "but a record genuinely called Greatest Hits still matches exactly"),
    ("Joe Cocker", "Greatest Hits", "Greatest Hits",
     "and the artist decides which one"),

    ("Hans Zimmer & The Disruptive Collective", "HANS ZIMMER LIVE", "Live",
     "the service glued the artist onto the title; strip it and this is 'Live' "
     "against 'Live'. Without that it needs containment, and 'live' is exactly "
     "the kind of word containment should not trust"),

    ("Moby", "Natural Blues (Reprise Version / Edit) - Single", "Reprise",
     "the service names the single where you own the album: one word out of "
     "eleven, so overlap alone is not enough and containment has to carry it"),

    ("The Greatest Showman Cast", "The Greatest Showman",
     "The Greatest Showman (Original Motion Picture Soundtrack)",
     "'greatest' is boilerplate but 'showman' is not, so containment still counts"),

    ("Robbie Williams", "Britpop", None,
     "an album that is not on the shelf stays unmatched, rather than sticking "
     "to the first record by that artist"),
]


def main() -> int:
    store = Store(os.path.join(tempfile.mkdtemp(), "shelf.db"))
    for discogs_id, artist, title in SHELF:
        store.upsert_release(discogs_id, artist, title, "")

    bad = 0
    for artist, album, expect, why in CASES:
        row = store.best_collection_match(artist, album)
        got = row["title"] if row else None
        ok = got == expect
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {artist} / {album!r}")
        print(f"        -> {got!r}")
        if not ok:
            print(f"        expected {expect!r}")
        print(f"        {why}")
        print()

    store.close()
    print(f"{len(CASES) - bad} of {len(CASES)} correct")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
