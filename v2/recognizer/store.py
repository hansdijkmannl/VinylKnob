"""
Opslag en matchen. SQLite, want de hele platenkast past erin.

Een kant van 20 minuten levert bij volle dichtheid ruim 600.000 hashes op.
Vierhonderd albums, twee kanten: een half miljard rijen. Dat past niet, dus er
moet gesnoeid worden - zie `enroll` en `experiment_window.py`.
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
    score: int          # aantal hashes op hetzelfde tijdsverschil
    total_hits: int     # alle treffers, ook de toevallige
    offset_seconds: float

    @property
    def confidence(self) -> float:
        """Aandeel van de treffers dat op één lijn ligt. Boven ~0,15 is echt."""
        return self.score / self.total_hits if self.total_hits else 0.0


class Store:
    def __init__(self, path: str = "collection.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- vullen ------------------------------------------------------------
    def enroll(self, samples: np.ndarray, label: str,
               discogs_id: str | None = None, side: str | None = None,
               seconds: float | None = None, keep_one_in: int = 4) -> int:
        """Legt een kant vast.

        `seconds` knipt de opname af; None legt de hele kant vast. `keep_one_in`
        dunt de hashes uit: bij 8 wordt er nog maar een op de acht bewaard.

        Die twee knoppen regelen dezelfde afweging vanaf twee kanten. Een korte
        opname vastleggen is goedkoop maar dekt alleen het begin van de kant -
        staat de naald ergens in het midden, dan is er niets om mee te matchen.
        Uitdunnen houdt de hele kant herkenbaar en betaalt met trefkans. Zie
        `experiment_window.py` voor de meting waarop de keuze rust.
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
        """Verkeerd gekoppeld? Weg ermee - dit is de 'dit klopt niet'-knop."""
        self.db.execute("DELETE FROM prints WHERE side_id = ?", (side_id,))
        self.db.execute("DELETE FROM sides WHERE id = ?", (side_id,))
        self.db.commit()

    def sides(self) -> list[tuple[int, str]]:
        return list(self.db.execute("SELECT id, label FROM sides ORDER BY id"))

    def hash_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM prints").fetchone()[0]

    # -- zoeken ------------------------------------------------------------
    def identify(self, samples: np.ndarray, top: int = 3) -> list[Match]:
        """Welke kant is dit?

        De truc zit in het tijdsverschil. Elke treffer levert een verschil op
        tussen 'waar het in de database staat' en 'waar het in het fragment
        staat'. Bij een echte match zijn die verschillen allemaal gelijk, want
        het fragment ligt gewoon een vast stuk verderop in de opname. Bij toeval
        liggen ze willekeurig verspreid. We zoeken dus niet het meeste aantal
        treffers maar de grootste stapel op één en hetzelfde verschil.
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
        for i in range(0, len(keys), 900):     # SQLite-limiet op variabelen
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
            # Het venster van drie opvangt de resterende speling van een frame:
            # anders valt een echte match uiteen over twee naburige bakjes.
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
