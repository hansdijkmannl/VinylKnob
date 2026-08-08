"""
Your own fingerprint database: recognition without a service.

Why this exists: shazamio costs nothing but is an unofficial client that can
break, and AudD wants a subscription. What you have recorded yourself keeps
working, including with no internet at all.

It is meant to grow through use. Every time a record is recognised and linked,
the recording from that listen goes into the database. One clip covers only its
own few seconds of a side, but each listen captures a different stretch — after
playing a record a few times it is covered end to end on its own. Nothing has to
be imported up front.

The algorithm and the measurements behind it are in ../recognizer/README.md.
"""

from __future__ import annotations

import io
import wave

import numpy as np

from fingerprint import (DT_TOLERANCE, SAMPLE_RATE, SECONDS_PER_FRAME,
                         fingerprint, mix, resample_to_working_rate)

SCHEMA = """
CREATE TABLE IF NOT EXISTS prints (
    hash       INTEGER NOT NULL,
    offset     INTEGER NOT NULL,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    -- Which track this clip came off, as a place in the running order; -1 when
    -- nobody knew. See remember().
    track_pos  INTEGER NOT NULL DEFAULT -1
);
CREATE INDEX IF NOT EXISTS idx_prints_hash ON prints(hash);
"""

# Keep one hash in four. The reasoning is in ../recognizer/README.md: thinning
# out is a better dial than truncating.
KEEP_ONE_IN = 4

# How much of one record is enough to keep.
#
# Learning a side turned out to need a ceiling, and finding that out cost an
# evening: with none, one record reached 137,527 hashes against an average of
# ten thousand — a third of the whole database — and became a magnet. Everything
# put on after it was recognised as that record, because a release with thirteen
# times the coverage wins any coincidental alignment and the margin over the
# runner-up cannot save you from a runner-up that small.
#
# Forty thousand is about three and a half minutes of a side, spread over
# wherever the needle happened to be. Records that recognise reliably today sit
# between fifteen and thirty-six thousand, so this is comfortably above what
# works and comfortably below what dominates.
HASH_CAP = 40_000


def count_for(db, release_id: int) -> int:
    return db.execute("SELECT COUNT(*) FROM prints WHERE release_id = ?",
                      (release_id,)).fetchone()[0]


def is_full(db, release_id: int) -> bool:
    """Has this record been learnt enough? See HASH_CAP."""
    return count_for(db, release_id) >= HASH_CAP


# When a local hit is good enough to skip the service entirely.
MIN_SCORE = 25
MIN_MARGIN = 3.0


def decode_wav(data: bytes) -> np.ndarray | None:
    """From the WAV we are handed to mono float at the working rate."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except Exception:                                      # noqa: BLE001
        return None

    if width != 2:                                         # we always send 16-bit
        return None
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if len(samples) < SAMPLE_RATE // 2:
        return None
    return resample_to_working_rate(samples, rate)


def ensure_schema(db) -> None:
    db.executescript(SCHEMA)
    # Fingerprints from before there was a track to tag them with. They keep
    # working — they recognise the record perfectly well — they just cannot say
    # which song, and there is no way to work that out after the fact.
    cols = {r[1] for r in db.execute("PRAGMA table_info(prints)")}
    if "track_pos" not in cols:
        db.execute("ALTER TABLE prints ADD COLUMN track_pos INTEGER NOT NULL DEFAULT -1")
    db.commit()


def remember(db, release_id: int, samples: np.ndarray, track_pos: int = -1) -> int:
    """Record a clip against a release. Returns the number of hashes stored.

    `track_pos` is which track the clip came off, as a place in the running
    order, and it is the difference between knowing the record and knowing the
    song. A service that says "A4" is telling us that about *this stretch of
    audio*; storing it with the fingerprints means the next time we recognise
    that stretch ourselves we can say A4 too, with nobody asked.

    Left at -1 when nobody knew — a hand-made link, or a clip from a record
    whose tracklist has no positions. Those hashes still work for recognising
    the record; they simply cannot name the track.
    """
    rows = [(h, t, release_id, track_pos) for h, t in fingerprint(samples)
            if mix(h) % KEEP_ONE_IN == 0]
    if not rows:
        return 0
    db.executemany(
        "INSERT INTO prints (hash, offset, release_id, track_pos) VALUES (?, ?, ?, ?)",
        rows)
    db.commit()
    if _index["loaded"]:
        _index["buffer"].extend(rows)
        if len(_index["buffer"]) > _BUFFER_MAX:
            _fold_in()
    return len(rows)


def forget(db, release_id: int) -> None:
    db.execute("DELETE FROM prints WHERE release_id = ?", (release_id,))
    db.commit()
    _index["loaded"] = False        # cheaper to reload than to cut a hole in it


def count(db) -> tuple[int, int]:
    """(number of hashes, number of releases recognisable locally)"""
    a = db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    b = db.execute("SELECT COUNT(DISTINCT release_id) FROM prints").fetchone()[0]
    return a, b


# -- the index --------------------------------------------------------------
# The hashes as three sorted numpy arrays instead of rows in SQLite.
#
# This was written down as the ceiling before any of it was built. From
# ../recognizer/README.md: "That is the limit of this design and the next thing
# to be tackled." Measured again here on the real shelf, and it is linear —
# 0.7 s at 308 thousand hashes, 8.2 s at 4.9 million. The cost is not the
# database finding the rows, it is Python touching each one.
#
# Sorted by hash, so `np.searchsorted` turns each of the two thousand hashes in
# a query into two binary searches over one contiguous array. The whole of it is
# sixteen bytes a hash: five million is eighty megabytes, which a Pi has and a
# lookup that takes eight seconds does not deserve.
#
# New hashes go to a small append buffer rather than into the sorted arrays,
# because inserting into the middle of those means rebuilding them. The buffer
# is searched exhaustively — it is thousands of entries against millions — and
# folded in once it is big enough to be worth the sort.
_BUFFER_MAX = 200_000

# Release and time offset packed into one integer so the counting is a single
# np.unique. The bias makes a negative offset positive; the span is wider than
# any record is long, in frames.
_DELTA_BIAS = 1 << 20
_DELTA_SPAN = 1 << 21

_index: dict = {"hash": None, "offset": None, "release": None, "track": None,
                "buffer": [], "loaded": False}


_CHUNK = 100_000


def _load(db) -> None:
    """Read the table into three arrays, without ever holding it twice.

    Streamed in chunks into arrays allocated up front, rather than fetched into
    a list of tuples and converted. The obvious version brought a Pi with a
    gigabyte to its knees at five million rows — the tuples alone are an order
    of magnitude bigger than the arrays they become, and the machine spent
    several minutes swapping instead of answering. This costs one chunk of
    working room on top of the result.
    """
    total = db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    hashes = np.empty(total, dtype=np.int64)
    offsets = np.empty(total, dtype=np.int32)
    releases = np.empty(total, dtype=np.int32)
    tracks = np.empty(total, dtype=np.int32)

    cursor = db.execute("SELECT hash, offset, release_id, track_pos FROM prints")
    at = 0
    while at < total:
        rows = cursor.fetchmany(_CHUNK)
        if not rows:
            break
        block = np.array(rows, dtype=np.int64)
        n = len(block)
        hashes[at:at + n] = block[:, 0]
        offsets[at:at + n] = block[:, 1]
        releases[at:at + n] = block[:, 2]
        tracks[at:at + n] = block[:, 3]
        at += n
        del block
    if at < total:                       # rows vanished under us; use what came
        hashes, offsets = hashes[:at], offsets[:at]
        releases, tracks = releases[:at], tracks[:at]

    order = np.argsort(hashes, kind="stable")
    _index["hash"] = hashes[order]
    _index["offset"] = offsets[order]
    _index["release"] = releases[order]
    _index["track"] = tracks[order]
    _index["buffer"] = []
    _index["loaded"] = True


def _fold_in() -> None:
    """Merge the append buffer into the sorted arrays."""
    if not _index["buffer"]:
        return
    extra = np.array(_index["buffer"], dtype=np.int64)
    h = np.concatenate([_index["hash"], extra[:, 0]])
    o = np.concatenate([_index["offset"], extra[:, 1].astype(np.int32)])
    r = np.concatenate([_index["release"], extra[:, 2].astype(np.int32)])
    k = np.concatenate([_index["track"], extra[:, 3].astype(np.int32)])
    order = np.argsort(h, kind="stable")
    _index["hash"], _index["offset"] = h[order], o[order]
    _index["release"], _index["track"] = r[order], k[order]
    _index["buffer"] = []


def index_ready(db) -> dict:
    """Load it if it is not loaded, and say how big it is."""
    if not _index["loaded"]:
        _load(db)
    return {"hashes": int(len(_index["hash"])) + len(_index["buffer"]),
            "buffered": len(_index["buffer"])}


def identify(db, samples: np.ndarray) -> dict | None:
    """Search locally. Returns None if nothing is convincing.

    The winner is not the most hits but the biggest pile at one and the same
    time offset — that is what separates a real match from a handful of
    coincidental collisions.
    """
    query = fingerprint(samples, dt_tolerance=DT_TOLERANCE)
    if not query:
        return None

    if not _index["loaded"]:
        _load(db)
    if len(_index["hash"]) == 0 and not _index["buffer"]:
        return None

    # All of it as arrays, with no Python loop over the hits.
    #
    # Two binary searches per query hash give the run of rows that match it;
    # what remains is arithmetic over those runs, and that is the part worth
    # vectorising. The loop it replaces touched every hit one at a time, which
    # is why the lookup grew with the database no matter how the rows were
    # found.
    q_hash = np.fromiter((h for h, _ in query), dtype=np.int64, count=len(query))
    q_time = np.fromiter((s for _, s in query), dtype=np.int64, count=len(query))

    table, offsets, releases = _index["hash"], _index["offset"], _index["release"]
    left = np.searchsorted(table, q_hash, side="left")
    right = np.searchsorted(table, q_hash, side="right")
    counts = (right - left).astype(np.int64)
    total = int(counts.sum())

    keys = np.empty(0, dtype=np.int64)
    hit_track = np.empty(0, dtype=np.int32)
    if total:
        # The ragged ranges [left, right) flattened into one array of row
        # numbers, without building any of them as lists.
        starts = np.repeat(left, counts)
        within = np.arange(total, dtype=np.int64) - np.repeat(
            np.concatenate(([0], np.cumsum(counts)[:-1])), counts)
        rows = starts + within

        delta = offsets[rows].astype(np.int64) - np.repeat(q_time, counts)
        keys = releases[rows].astype(np.int64) * _DELTA_SPAN + (delta + _DELTA_BIAS)
        hit_track = _index["track"][rows]

    # And whatever has been learnt since the arrays were last sorted. Thousands
    # against millions, so a plain scan is the cheaper thing here.
    if _index["buffer"]:
        want = {}
        for h, s in query:
            want.setdefault(h, []).append(s)
        pairs = [(rel * _DELTA_SPAN + (off - s + _DELTA_BIAS), pos)
                 for h, off, rel, pos in _index["buffer"] if h in want
                 for s in want[h]]
        if pairs:
            keys = np.concatenate([keys, np.array([k for k, _ in pairs], dtype=np.int64)])
            hit_track = np.concatenate(
                [hit_track, np.array([p for _, p in pairs], dtype=np.int32)])

    if len(keys) == 0:
        return None

    packed, tally = np.unique(keys, return_counts=True)
    release_of = packed // _DELTA_SPAN
    delta_of = packed % _DELTA_SPAN

    # A window of three, to absorb the remaining slack of one frame. Neighbours
    # are found by looking the shifted keys up in the same sorted array.
    left_n = np.searchsorted(packed, packed - 1)
    right_n = np.searchsorted(packed, packed + 1)
    has_left = (left_n < len(packed)) & (packed[np.minimum(left_n, len(packed) - 1)] == packed - 1)
    has_right = (right_n < len(packed)) & (packed[np.minimum(right_n, len(packed) - 1)] == packed + 1)
    windowed = (tally
                + np.where(has_left, tally[np.minimum(left_n, len(packed) - 1)], 0)
                + np.where(has_right, tally[np.minimum(right_n, len(packed) - 1)], 0))

    scored = []
    for release_id in np.unique(release_of):
        mine = release_of == release_id
        best = int(np.argmax(windowed[mine]))
        scored.append((int(windowed[mine][best]), int(release_id),
                       int(delta_of[mine][best] - _DELTA_BIAS)))

    if not scored:
        return None
    scored.sort(reverse=True)
    score, release_id, delta = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0
    margin = score / runner_up if runner_up else float("inf")

    if score < MIN_SCORE or margin < MIN_MARGIN:
        return None

    # Which track, if the hits that won say so clearly enough.
    #
    # They are the stretches of audio that lined up at one and the same offset,
    # so whatever they were enrolled as is what this is. But a majority and not
    # merely the commonest: two clips off one record share a few hundred hashes,
    # and taking the most frequent tag among only the tagged hits let five
    # strays outvote a thousand untagged ones and name the wrong track. Half of
    # everything that won, or we say nothing.
    # Over the whole window and not just its middle. The score is the sum of
    # three neighbouring offsets, so when two of them tie the winner reported is
    # whichever came first — and that can be the neighbour of the one holding
    # the hits. Reading the track out of that single bucket found eight stray
    # tagged hashes and confidently named the wrong song, while three thousand
    # untagged ones sat one offset away.
    won = release_id * _DELTA_SPAN + (delta + _DELTA_BIAS)
    window = np.array([won - 1, won, won + 1], dtype=np.int64)
    mine = (hit_track[np.isin(keys, window)] if len(hit_track) == len(keys)
            else np.empty(0, np.int32))
    track_pos = None
    known = mine[mine >= 0]
    if len(known):
        counts = np.bincount(known)
        best = int(counts.argmax())
        if counts[best] * 2 > len(mine):
            track_pos = best

    return {"releaseId": release_id, "score": score,
            "margin": None if margin == float("inf") else round(margin, 1),
            "offsetSeconds": round(delta * SECONDS_PER_FRAME, 1),
            "trackPos": track_pos}
