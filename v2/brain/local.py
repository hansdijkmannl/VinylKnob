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
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_prints_hash ON prints(hash);
"""

# Keep one hash in four. The reasoning is in ../recognizer/README.md: thinning
# out is a better dial than truncating.
KEEP_ONE_IN = 4

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
    db.commit()


def remember(db, release_id: int, samples: np.ndarray) -> int:
    """Record a clip against a release. Returns the number of hashes stored."""
    rows = [(h, t, release_id) for h, t in fingerprint(samples)
            if mix(h) % KEEP_ONE_IN == 0]
    if not rows:
        return 0
    db.executemany("INSERT INTO prints (hash, offset, release_id) VALUES (?, ?, ?)", rows)
    db.commit()
    return len(rows)


def forget(db, release_id: int) -> None:
    db.execute("DELETE FROM prints WHERE release_id = ?", (release_id,))
    db.commit()


def count(db) -> tuple[int, int]:
    """(number of hashes, number of releases recognisable locally)"""
    a = db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    b = db.execute("SELECT COUNT(DISTINCT release_id) FROM prints").fetchone()[0]
    return a, b


def identify(db, samples: np.ndarray) -> dict | None:
    """Search locally. Returns None if nothing is convincing.

    The winner is not the most hits but the biggest pile at one and the same
    time offset — that is what separates a real match from a handful of
    coincidental collisions.
    """
    query = fingerprint(samples, dt_tolerance=DT_TOLERANCE)
    if not query:
        return None

    by_hash: dict[int, list[int]] = {}
    for h, t in query:
        by_hash.setdefault(h, []).append(t)

    aligned: dict[int, dict[int, int]] = {}
    keys = list(by_hash)
    for i in range(0, len(keys), 900):                     # SQLite variable limit
        chunk = keys[i:i + 900]
        rows = db.execute(
            "SELECT hash, offset, release_id FROM prints WHERE hash IN "
            f"({','.join('?' * len(chunk))})", chunk)
        for h, db_offset, release_id in rows:
            bucket = aligned.setdefault(release_id, {})
            for q_offset in by_hash[h]:
                delta = db_offset - q_offset
                bucket[delta] = bucket.get(delta, 0) + 1

    scored = []
    for release_id, deltas in aligned.items():
        # A window of three, to absorb the remaining slack of one frame.
        delta, score = max(
            ((d, deltas.get(d - 1, 0) + c + deltas.get(d + 1, 0)) for d, c in deltas.items()),
            key=lambda kv: kv[1])
        scored.append((score, release_id, delta))

    if not scored:
        return None
    scored.sort(reverse=True)
    score, release_id, delta = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0
    margin = score / runner_up if runner_up else float("inf")

    if score < MIN_SCORE or margin < MIN_MARGIN:
        return None
    return {"releaseId": release_id, "score": score,
            "margin": None if margin == float("inf") else round(margin, 1),
            "offsetSeconds": round(delta * SECONDS_PER_FRAME, 1)}
