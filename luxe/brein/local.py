"""
De eigen fingerprint-database: herkennen zonder dienst.

Waarom dit er is: shazamio kost niets maar is een onofficiele client die kan
breken, en AudD vraagt een abonnement. Wat je zelf hebt vastgelegd blijft altijd
werken, ook zonder internet.

De opzet is dat dit groeit door gebruik. Elke keer dat een plaat herkend en
gekoppeld wordt, gaat het fragment van die luisterbeurt in de database. Een
fragment van acht seconden dekt maar acht seconden van een kant, maar je legt
elke keer een ander stuk vast — na een paar keer draaien is een plaat vanzelf
over de hele lengte gedekt. Je hoeft dus niets vooraf in te lezen.

Het algoritme en de gemeten onderbouwing staan in ../recognizer/README.md.
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

# Een op de vier hashes bewaren. Onderbouwing in ../recognizer/README.md:
# uitdunnen is een betere knop dan afkappen.
KEEP_ONE_IN = 4

# Wanneer is een lokale treffer goed genoeg om de dienst over te slaan.
MIN_SCORE = 25
MIN_MARGIN = 3.0


def decode_wav(data: bytes) -> np.ndarray | None:
    """Van de wav die de browser stuurt naar mono float op de werkfrequentie."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except Exception:                                      # noqa: BLE001
        return None

    if width != 2:                                         # we sturen zelf 16 bits
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
    """Legt een fragment vast bij een release. Geeft het aantal hashes terug."""
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
    """(aantal hashes, aantal releases dat lokaal herkend kan worden)"""
    a = db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    b = db.execute("SELECT COUNT(DISTINCT release_id) FROM prints").fetchone()[0]
    return a, b


def identify(db, samples: np.ndarray) -> dict | None:
    """Zoekt lokaal. Geeft None als er niets overtuigends bij zit.

    Niet het meeste aantal treffers wint, maar de grootste stapel op één en
    hetzelfde tijdsverschil — dat onderscheidt een echte match van een handvol
    toevallige botsingen.
    """
    query = fingerprint(samples, dt_tolerance=DT_TOLERANCE)
    if not query:
        return None

    by_hash: dict[int, list[int]] = {}
    for h, t in query:
        by_hash.setdefault(h, []).append(t)

    aligned: dict[int, dict[int, int]] = {}
    keys = list(by_hash)
    for i in range(0, len(keys), 900):                     # SQLite-limiet
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
        # Venster van drie: de resterende speling van een frame opvangen.
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
