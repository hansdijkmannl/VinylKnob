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
  * a track on three of your own records, and the same record twice over

Two questions are asked of it. First the fallback on its own: given an artist
and an album title, which record is that. Then the whole decision — tracklists
first, titles only when the tracklists cannot say — which is what actually
runs, and which decides whether you are asked to point at a sleeve.
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
    ("9", "Robbie Williams", "Greatest Hits"),   # the same record a second time
]

# Only for the records a tracklist was actually fetched for. A shelf is never
# fully backfilled — new arrivals sit there without one — and the decision has
# to survive that, so most of the shelf above deliberately has none.
TRACKLISTS = {
    "1": ["Have You Met Miss Jones?", "Mr. Bojangles", "Somethin' Stupid"],
    "2": ["Let Me Entertain You", "Angels", "Somethin' Stupid"],
    "3": ["Let Me Entertain You", "Angels", "Old Before I Die"],
    "9": ["Let Me Entertain You", "Angels", "Somethin' Stupid"],
    "5": ["Time", "Chevaliers De Sangreal"],
    "6": ["Now We Are Free", "Honor Him"],
}

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


# (artist, track, album the service names, the record to settle on, the records
#  to offer — empty whenever there is nothing to ask, why)
DECISIONS = [
    ("Robbie Williams", "Somethin' Stupid",
     "In And Out Of Consciousness: Greatest Hits 1990 - 2010",
     None, ["Swing When You're Winning", "Greatest Hits"],
     "the case that started this. The service named a compilation you do not "
     "own; the song is on two records you do own, and only you can see which "
     "one is turning"),

    ("Robbie Williams", "Let Me Entertain You", "Greatest Hits",
     None, ["Greatest Hits", "Life Thru A Lens"],
     "even when the service names a record you own: it is on two of them, so "
     "the title it happened to pick does not get to decide"),

    ("Robbie Williams", "Old Before I Die", "Life Thru A Lens",
     "Life Thru A Lens", [],
     "on exactly one of your records, so nothing is asked — this is the "
     "ordinary case and it has to stay silent"),

    ("Robbie Williams", "Old Before I Die", "Something Else Entirely",
     "Life Thru A Lens", [],
     "and the tracklist wins over the album the service named, which is the "
     "whole reason for asking it first"),

    ("Hans Zimmer & The Disruptive Collective", "Time", "HANS ZIMMER LIVE",
     "Live", [],
     "the artist as the service writes it is not the artist as Discogs writes "
     "it; overlap has to carry that here too, or the tracklist is never found"),

    ("Robbie Williams", "Angels", "Greatest Hits",
     None, ["Greatest Hits", "Life Thru A Lens"],
     "you own Greatest Hits twice. Two copies of one record is not a choice — "
     "offering it would be a question with one answer written down twice"),

    ("Moby", "Natural Blues", "Natural Blues (Reprise Version / Edit) - Single",
     "Reprise", [],
     "no tracklist was ever fetched for this record, so it falls back to "
     "comparing titles and still lands right"),

    ("Robbie Williams", "Let Me Entertain You", "Life Thru A Lens",
     None, ["Greatest Hits", "Life Thru A Lens"],
     "the same two, whichever of them the service happens to name: the "
     "question does not change because the guess did"),
]


def main() -> int:
    store = Store(os.path.join(tempfile.mkdtemp(), "shelf.db"))
    for discogs_id, artist, title in SHELF:
        store.upsert_release(discogs_id, artist, title, "")
    for discogs_id, titles in TRACKLISTS.items():
        row = store.db.execute("SELECT id FROM releases WHERE discogs_id = ?",
                               (discogs_id,)).fetchone()
        store.set_tracks(row["id"], titles)

    bad = 0
    print("-- the album title on its own ------------------------------------\n")
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

    print("-- the whole decision, tracklists first --------------------------\n")
    for artist, track, album, expect, offer, why in DECISIONS:
        match, choices = store.decide_release(artist, track, album)
        got = match["title"] if match else None
        # Only offered when there is more than one; a single candidate is the
        # answer, not a question. The panel sees it the same way.
        got_offer = [r["title"] for r in choices] if len(choices) > 1 else []
        ok = got == expect and got_offer == offer
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {artist} / {track!r} / {album!r}")
        print(f"        -> {got!r}, offers {got_offer}")
        if not ok:
            print(f"        expected {expect!r}, offers {offer}")
        print(f"        {why}")
        print()

    total = len(CASES) + len(DECISIONS)
    store.close()
    print(f"{total - bad} of {total} correct")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
