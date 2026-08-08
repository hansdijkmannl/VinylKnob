"""
What the ears do without any sound.

    python test_ears.py

The audio loop needs a receiver on the other end and cannot be tested here.
The decisions around it can: they are the ones that decide what you see on the
panel when nothing is playing, which is most of the time.
"""

from __future__ import annotations

import pathlib
import sys

# store.py lives with the brain; the ears import it only here, for the title
# comparison the chooser depends on.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "brain"))

import listen

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        FAILS.append(what)


def playing_ears() -> listen.Ears:
    """An Ears that thinks a record is on, without one being on."""
    ears = listen.Ears.__new__(listen.Ears)
    ears.amplifier_on = True
    ears.artist, ears.title, ears.album = "Katie Melua", "Perfect Circle", "Pictures"
    ears.release_id, ears.cover_url = 259, "http://example/cover.jpg"
    ears.open_play_id, ears.choices = 41, [259, 256]
    ears.playing, ears.misses, ears.retry_at = True, 2, 123.0
    return ears


def main() -> int:
    # -- switching off empties the screen -----------------------------------
    ears = playing_ears()
    ears.amplifier_is(False)
    check(ears.artist == "" and ears.title == "" and ears.album == "",
          "the amplifier goes off and the record's name goes with it")
    check(ears.cover_url is None and ears.release_id is None,
          "and the sleeve, so switching on again is not a record that stopped "
          "playing half an hour ago")
    check(ears.choices == [] and ears.open_play_id is None,
          "and the open question, which was about a record no longer on")
    check(ears.playing is False and ears.retry_at is None,
          "and it is not still waiting to try the lookup again")

    # -- but only on the change ---------------------------------------------
    # watch_amplifier() calls this every ten seconds with the same answer.
    ears = playing_ears()
    ears.amplifier_is(True)
    check(ears.artist == "Katie Melua",
          "the amplifier is still on, so nothing is cleared")

    ears = playing_ears()
    ears.amplifier_is(False)
    ears.artist, ears.title = "Moby", "Natural Blues"      # a new side, amp off
    ears.amplifier_is(False)
    check(ears.artist == "Moby",
          "off and staying off does not keep wiping the screen — it clears on "
          "the change, not on the state")

    # -- coming back on ------------------------------------------------------
    ears = playing_ears()
    ears.amplifier_is(False)
    ears.amplifier_is(True)
    check(ears.amplifier_on is True,
          "switching back on opens the gate for the next side")

    # -- asking again about something nobody could name -----------------------
    ears = playing_ears()
    ears.release_id, ears.retry_at, ears.loud_since = None, 100.0, 50.0
    check(ears.wants_retry(200.0) is True,
          "nobody knows what this is and the minute is up, so it asks again")
    check(ears.wants_retry(50.0) is False,
          "but not before the minute is up")

    ears.loud_since = None
    check(ears.wants_retry(200.0) is False,
          "and not once it has gone quiet — that is a new side, not a retry")

    # This is the one that was wrong, and it is what put a linked record in the
    # queue as unknown while its own sleeve was on the screen.
    ears = playing_ears()
    ears.release_id, ears.retry_at, ears.loud_since = 259, 100.0, 50.0
    check(ears.wants_retry(200.0) is False,
          "a record that is already identified is never looked up again, even "
          "with a retry left standing from before it was")

    ears.release_id = None
    check(ears.wants_retry(200.0) is True,
          "and the same state without a record does ask, so it is the record "
          "that settles it and not something else")

    # -- the bare title, which is what a live record needs --------------------
    from store import _bare, _normalise
    cases = [
        ("Thank You, Stars (Live at The O2 Arena)", "thank you stars",
         "a venue in brackets is the pressing's opinion, not the song's name"),
        ("Spider's Web - Remastered 2011", "spider s web",
         "and so is a dash and a year"),
        ("Nine Million Bicycles", "",
         "a title with nothing to strip returns nothing, so it never becomes a "
         "second way to match what already matched exactly"),
        ("(Intro)", "",
         "and a title that is only a qualifier returns nothing rather than an "
         "empty string that would match every other one"),
    ]
    for title, want, why in cases:
        got = _bare(title)
        check(got == want, f"{title!r} -> {got!r} — {why}")

    print()
    print(f"{len(FAILS)} problem(s)" if FAILS else "  all good")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
