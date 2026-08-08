"""
Naming the track from your own fingerprints.

    python test_local.py

On real clips out of data/clips, one each off three different records. Synthetic
audio is a dishonest fixture for a fingerprinter — pure tones share hundreds of
hashes with each other — and the three most recent clips are usually three
stretches of one side, so the real database is asked which play each clip
belongs to.

What this is *not* about: whether unknown audio is rejected. Any two records
share ten per cent of their hashes and always have; what keeps that from
becoming a false match is the margin over the runner-up, and that rule cannot
work in a database with one record in it. The tuning behind it was measured
properly in ../recognizer/README.md and does not belong here. So both records
are enrolled before anything is asked, which is what a real shelf looks like.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile

import local
from store import Store

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        FAILS.append(what)


def three_different_records() -> list[str]:
    """One clip each off three different records.

    Which records they are matters more than it looks. The first version simply
    took the three most recent clips, and on a real shelf those are three
    stretches of the *same side* — so the clip meant to stand for "audio this
    device has never heard" was in fact the record it had just enrolled, and
    three assertions failed for being right. The real database says which play
    each clip belongs to, so ask it.
    """
    here = pathlib.Path(__file__).parent
    db_path = here / "data" / "brain.db"
    folder = here / "data" / "clips"
    if not db_path.exists() or not folder.exists():
        return []

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT clip_file, release_id FROM plays "
        "WHERE clip_file != '' AND clip_file IS NOT NULL AND release_id IS NOT NULL "
        "ORDER BY id DESC").fetchall()
    db.close()

    out, seen = [], set()
    for row in rows:
        if row["release_id"] in seen:
            continue
        path = folder / row["clip_file"]
        if not path.exists():
            continue
        seen.add(row["release_id"])
        out.append(str(path))
        if len(out) == 3:
            break
    return out


def main() -> int:
    clips = three_different_records()
    if len(clips) < 3:
        print("  fewer than three records have a clip saved — nothing to test "
              "against yet")
        return 0

    audio = [local.decode_wav(pathlib.Path(c).read_bytes()) for c in clips]
    if any(a is None for a in audio):
        print("  a clip would not decode")
        return 1
    side_a2, side_b1, elsewhere = audio
    for c in clips:
        print(f"  using {pathlib.Path(c).name}")
    print()

    store = Store(os.path.join(tempfile.mkdtemp(), "shelf.db"))
    db = store.db
    local._index["loaded"] = False

    store.upsert_release("1", "A Band", "First Record", "")
    store.upsert_release("2", "A Band", "Second Record", "")
    first = db.execute("SELECT id FROM releases WHERE discogs_id = '1'").fetchone()["id"]
    second = db.execute("SELECT id FROM releases WHERE discogs_id = '2'").fetchone()["id"]
    store.set_tracks(first, [
        {"title": "One", "printed": "A1", "secs": 200},
        {"title": "Two", "printed": "A2", "secs": 210},
        {"title": "Three", "printed": "B1", "secs": 190},
    ])

    # -- a clip enrolled as a track names that track back ---------------------
    local.remember(db, first, side_a2, track_pos=1)          # "A2 Two"
    local._index["loaded"] = False
    hit = local.identify(db, side_a2)
    check(hit is not None and hit["releaseId"] == first,
          "a clip enrolled against a record is recognised as that record")
    check(hit is not None and hit.get("trackPos") == 1,
          "and it says which track it came off, because that was stored with it")
    named = store.track_at(first, (hit or {}).get("trackPos"))
    check(named is not None and named["printed"] == "A2" and named["title"] == "Two",
          "which the tracklist turns into 'A2 Two' — the whole point of tagging")

    # -- an untagged clip still works, it just cannot name itself -------------
    local.remember(db, first, side_b1)                       # nobody knew
    local._index["loaded"] = False
    hit = local.identify(db, side_b1)
    check(hit is not None and hit["releaseId"] == first,
          "a clip enrolled with no track still recognises the record")
    check(hit is not None and hit.get("trackPos") is None,
          "and says nothing about the track rather than letting a few hashes it "
          "shares with a tagged clip name the wrong one")

    # -- a second record, so the margin rule is live --------------------------
    # Not decoration: with one record enrolled there is no runner-up, the margin
    # is infinite and the only thing standing between coincidence and a match is
    # the raw score. A shelf always has more than one record on it.
    local.remember(db, second, elsewhere, track_pos=0)
    local._index["loaded"] = False
    check((local.identify(db, elsewhere) or {}).get("releaseId") == second,
          "a second record is recognised as itself and not as the first")
    hit = local.identify(db, side_a2)
    check(hit is not None and hit["releaseId"] == first and hit.get("trackPos") == 1,
          "and the first still answers exactly as it did before")

    # -- forgetting one leaves the other alone --------------------------------
    local.forget(db, second)
    check((local.identify(db, side_a2) or {}).get("releaseId") == first,
          "forgetting one record does not take another one with it")
    check((local.identify(db, side_b1) or {}).get("trackPos") is None,
          "and the untagged clip is still untagged afterwards")

    # -- and there is a ceiling on how much of one record is kept -------------
    # Without one, a side played through learns until it is a third of the whole
    # database and every record put on after it is recognised as that one. It
    # happened, at 137,527 hashes against an average of ten thousand.
    check(local.HASH_CAP > 0, "there is a cap at all")
    check(not local.is_full(db, first),
          "a record with a normal amount of coverage is not full")
    was, local.HASH_CAP = local.HASH_CAP, 10
    check(local.is_full(db, first),
          "and one past the cap is, so the enrolling stops rather than running on")
    local.HASH_CAP = was

    store.close()
    print()
    print(f"{len(FAILS)} problem(s)" if FAILS else "  all good")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
