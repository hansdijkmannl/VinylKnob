"""
Storage and matching. SQLite, because the whole record shelf fits in it.

A 20-minute side yields over 600,000 hashes at full density. Four hundred
albums, two sides each: half a billion rows. That does not fit, so it has to be
pruned - see `enroll` and `experiment_window.py`.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from fingerprint import DT_TOLERANCE, SECONDS_PER_FRAME, fingerprint, mix

SCHEMA = """
CREATE TABLE IF NOT EXISTS sides (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    discogs_id   TEXT,
    side         TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prints (
    hash     INTEGER NOT NULL,
    offset   INTEGER NOT NULL,
    side_id  INTEGER NOT NULL REFERENCES sides(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_prints_hash ON prints(hash);
"""


@dataclass
class Match:
    side_id: int
    label: str
    score: int          # hashes at the same time difference
    total_hits: int     # every hit, coincidental ones included
    offset_seconds: float

    @property
    def confidence(self) -> float:
        """Share of the hits that line up. Above ~0.15 it is real."""
        return self.score / self.total_hits if self.total_hits else 0.0


class Store:
    def __init__(self, path: str = "collection.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- filling -----------------------------------------------------------
    def enroll(self, samples: np.ndarray, label: str,
               discogs_id: str | None = None, side: str | None = None,
               seconds: float | None = None, keep_one_in: int = 4) -> int:
        """Enrols a side.

        `seconds` cuts the recording off; None enrols the whole side.
        `keep_one_in` thins the hashes out: at 8 only one in eight is kept.

        Those two knobs work the same trade-off from opposite ends. Enrolling a
        short recording is cheap but only covers the start of the side - with
        the needle somewhere in the middle there is nothing to match against.
        Thinning out keeps the whole side recognisable and pays in hit rate. See
        `experiment_window.py` for the measurement the choice rests on.
        """
        if seconds is not None:
            from fingerprint import SAMPLE_RATE
            samples = samples[: int(seconds * SAMPLE_RATE)]

        cur = self.db.execute(
            "INSERT INTO sides (label, discogs_id, side) VALUES (?, ?, ?)",
            (label, discogs_id, side),
        )
        side_id = cur.lastrowid

        rows = [(h, t, side_id) for h, t in fingerprint(samples)
                if keep_one_in <= 1 or mix(h) % keep_one_in == 0]
        self.db.executemany("INSERT INTO prints (hash, offset, side_id) VALUES (?, ?, ?)", rows)
        self.db.commit()
        return side_id

    def forget(self, side_id: int) -> None:
        """Linked to the wrong thing? Out with it - this is the 'that is wrong' button."""
        self.db.execute("DELETE FROM prints WHERE side_id = ?", (side_id,))
        self.db.execute("DELETE FROM sides WHERE id = ?", (side_id,))
        self.db.commit()

    def sides(self) -> list[tuple[int, str]]:
        return list(self.db.execute("SELECT id, label FROM sides ORDER BY id"))

    def hash_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]

    # -- searching ---------------------------------------------------------
    def identify(self, samples: np.ndarray, top: int = 3) -> list[Match]:
        """Which side is this?

        The trick is in the time difference. Every hit yields a difference
        between 'where it sits in the database' and 'where it sits in the clip'.
        On a real match those differences are all the same, because the clip is
        simply a fixed distance further into the recording. By coincidence they
        scatter at random. So we are not looking for the most hits but for the
        biggest pile at one and the same difference.
        """
        query = fingerprint(samples, dt_tolerance=DT_TOLERANCE)
        if not query:
            return []

        by_hash: dict[int, list[int]] = defaultdict(list)
        for h, t in query:
            by_hash[h].append(t)

        aligned: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        totals: dict[int, int] = defaultdict(int)

        keys = list(by_hash)
        for i in range(0, len(keys), 900):     # SQLite's limit on variables
            chunk = keys[i:i + 900]
            placeholders = ",".join("?" * len(chunk))
            rows = self.db.execute(
                f"SELECT hash, offset, side_id FROM prints WHERE hash IN ({placeholders})",
                chunk,
            )
            for h, db_offset, side_id in rows:
                totals[side_id] += 1
                for q_offset in by_hash[h]:
                    aligned[side_id][db_offset - q_offset] += 1

        labels = dict(self.db.execute("SELECT id, label FROM sides"))

        results = []
        for side_id, deltas in aligned.items():
            # The window of three catches the remaining slack of one frame:
            # otherwise a real match falls apart across two neighbouring buckets.
            delta, score = max(
                ((d, deltas.get(d - 1, 0) + c + deltas.get(d + 1, 0))
                 for d, c in deltas.items()),
                key=lambda kv: kv[1],
            )
            results.append(Match(
                side_id=side_id,
                label=labels.get(side_id, "?"),
                score=score,
                total_hits=totals[side_id],
                offset_seconds=delta * SECONDS_PER_FRAME,
            ))

        results.sort(key=lambda m: m.score, reverse=True)
        return results[:top]
