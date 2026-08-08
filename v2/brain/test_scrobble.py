"""
Exactly what would leave the house, without any of it leaving.

    python test_scrobble.py

The one part of this project that sends your listening somewhere else, so the
thing worth pinning down is the shape of it: what is in a listen, what is not,
and when nothing is sent at all. `scrobble.payload` is deliberately separate from
`scrobble.send` so this can be looked at with no token and no network.
"""

from __future__ import annotations

import sys

import scrobble

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        FAILS.append(what)


def main() -> int:
    body = scrobble.payload(
        artist="Robbie Williams", track="Angels", album="Life Thru A Lens",
        printed="A4", discogs_id="20350645", at=1_700_000_000)

    check(body["listen_type"] == "single", "one listen at a time, not a batch")
    check(len(body["payload"]) == 1, "and one entry in it")

    entry = body["payload"][0]
    meta = entry["track_metadata"]
    info = meta["additional_info"]

    check(entry["listened_at"] == 1_700_000_000,
          "the time is the one passed in, not the time of sending — a retried "
          "lookup should not move the listen")
    check(meta["artist_name"] == "Robbie Williams" and meta["track_name"] == "Angels",
          "artist and track are the two things the service actually needs")
    check(meta["release_name"] == "Life Thru A Lens",
          "and the album, which is your pressing rather than the service's guess")
    check(info.get("tracknumber") == "A4",
          "the side and number as the sleeve prints them — the one thing a "
          "record knows that a stream does not")
    check(info.get("discogs_id") == 20350645,
          "the Discogs id as a number, so the listen points back at your copy")
    check(info.get("media_player") == "VinylKnob",
          "and it says what sent it")

    # -- what is left out -----------------------------------------------------
    bare = scrobble.payload(artist="Moby", track="Natural Blues", at=1)
    meta = bare["payload"][0]["track_metadata"]
    check("release_name" not in meta,
          "no album means the field is absent, not an empty string a service "
          "would have to guess at")
    check("tracknumber" not in meta["additional_info"],
          "same for a track we could not place on a side")

    odd = scrobble.payload(artist="A", track="B", discogs_id="byhand-7", at=1)
    check("discogs_id" not in odd["payload"][0]["track_metadata"]["additional_info"],
          "a record you typed in yourself has no Discogs id, and 'byhand-7' is "
          "not a number to send as one")

    check(scrobble.SAME_TRACK_S > 0,
          "there is a window in which the same track is one listen, because a "
          "retried lookup lands on it twice")

    print()
    print(f"{len(FAILS)} problem(s)" if FAILS else "  all good")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
