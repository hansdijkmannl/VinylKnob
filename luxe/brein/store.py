"""
Opslag voor het brein: instellingen, je Discogs-collectie, en alles wat er
geluisterd is.

Eén SQLite-bestand plus twee mappen op schijf (hoezen en geluidsfragmenten).
Draait straks op de Pi, nu op je Mac — er zit niets in dat platformafhankelijk
is.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import time
import uuid

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
COVERS = DATA / "covers"
CLIPS = DATA / "clips"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Je Discogs-collectie, lokaal gecachet zodat zoeken niet elke keer het
-- netwerk op hoeft en zodat het straks op de Pi ook offline werkt.
CREATE TABLE IF NOT EXISTS releases (
    id          INTEGER PRIMARY KEY,
    discogs_id  TEXT UNIQUE NOT NULL,
    artist      TEXT NOT NULL,
    title       TEXT NOT NULL,
    year        TEXT,
    formats     TEXT,
    cover_url   TEXT,
    cover_file  TEXT,          -- bestandsnaam in data/covers
    added_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rel_artist ON releases(artist);
CREATE INDEX IF NOT EXISTS idx_rel_title  ON releases(title);

-- Elke keer dat er geluisterd is. Herkend of niet, alles komt hierin.
CREATE TABLE IF NOT EXISTS plays (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    status      TEXT NOT NULL,     -- herkend | onbekend | gekoppeld | weggegooid
    engine      TEXT,
    artist      TEXT,
    title       TEXT,
    album       TEXT,
    cover_url   TEXT,
    clip_file   TEXT,              -- bestandsnaam in data/clips
    release_id  INTEGER REFERENCES releases(id) ON DELETE SET NULL,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_plays_status ON plays(status);
"""

DEFAULTS = {
    "discogs_token": "",
    "discogs_user": "",
    "audd_token": "",
    "collection_synced_at": "",
    "lookup_count": "0",

    # Laat de hoes ronddraaien terwijl er iets speelt. Standaard uit: 33 toeren
    # is 1,8 seconde per omwenteling en dat is onrustig om naar te kijken.
    # "uit" | "langzaam" (1 toer per minuut) | "33" (33 1/3 toeren)
    "screen_spin": "uit",

    # Instellingen voor de Marantz. Ze staan hier en niet in de firmware, zodat
    # het CrowPanel ze bij het opstarten ophaalt en je ze kunt wijzigen zonder
    # te flashen. Dezelfde rolverdeling als in versie 1: apparaat toont,
    # webinterface configureert.
    "avr_host": "",
    "avr_port": "23",
    "avr_half_db_per_step": "1",
    "avr_accel_factor": "6",
    "avr_accel_window_ms": "140",
    "avr_enc_divider": "4",
    "avr_vol_max_db": "-15",
    "avr_long_press_ms": "1000",
    "avr_double_press_ms": "350",
    "avr_favourite": "0",
    "avr_inputs": json.dumps([
        {"code": "PHONO", "label": "Platenspeler"},
        {"code": "CD",    "label": "CD"},
        {"code": "TV",    "label": "TV"},
        {"code": "BT",    "label": "Bluetooth"},
    ]),
}

# Ingangen van de SR7015 zoals het protocol ze kent.
KNOWN_INPUTS = [
    "PHONO", "CD", "TUNER", "DVD", "BD", "TV", "SAT/CBL", "MPLAY", "GAME",
    "8K", "AUX1", "AUX2", "NET", "BT", "USB", "HDRADIO", "SPOTIFY", "IRADIO",
    "SERVER", "FAVORITES",
]


def _normalise(text: str) -> str:
    """Voor het vergelijken van titels: kleine letters, geen leestekens."""
    keep = [c.lower() if c.isalnum() else " " for c in (text or "")]
    words = "".join(keep).split()
    # Lidwoorden weglaten; "The Beatles" en "Beatles" horen te matchen.
    skip = {"the", "a", "an", "de", "het", "een"}
    return " ".join(w for w in words if w not in skip)


class Store:
    def __init__(self, path: str | None = None):
        DATA.mkdir(exist_ok=True)
        COVERS.mkdir(exist_ok=True)
        CLIPS.mkdir(exist_ok=True)
        self.db = sqlite3.connect(path or (DATA / "brein.db"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        import local                       # eigen fingerprint-database
        local.ensure_schema(self.db)
        for key, value in DEFAULTS.items():
            self.db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                            (key, value))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- instellingen ------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, str(value)))
        self.db.commit()

    def bump_lookups(self) -> int:
        n = int(self.get("lookup_count", "0") or 0) + 1
        self.set("lookup_count", n)
        return n

    # -- collectie ---------------------------------------------------------
    def upsert_release(self, discogs_id: str, artist: str, title: str,
                       year: str = "", formats: str = "", cover_url: str = "") -> int:
        self.db.execute(
            """INSERT INTO releases (discogs_id, artist, title, year, formats, cover_url)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(discogs_id) DO UPDATE SET
                 artist=excluded.artist, title=excluded.title,
                 year=excluded.year, formats=excluded.formats,
                 cover_url=COALESCE(NULLIF(excluded.cover_url,''), releases.cover_url)""",
            (str(discogs_id), artist, title, year, formats, cover_url))
        self.db.commit()
        row = self.db.execute("SELECT id FROM releases WHERE discogs_id = ?",
                              (str(discogs_id),)).fetchone()
        return row["id"]

    def set_cover_file(self, release_id: int, filename: str) -> None:
        self.db.execute("UPDATE releases SET cover_file = ? WHERE id = ?",
                        (filename, release_id))
        self.db.commit()

    def release(self, release_id: int):
        return self.db.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()

    def release_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) c FROM releases").fetchone()["c"]

    def search_collection(self, query: str, limit: int = 25):
        """Zoekt eerst in je eigen kast. Losse woorden, volgorde maakt niet uit."""
        words = _normalise(query).split()
        if not words:
            return self.db.execute(
                "SELECT * FROM releases ORDER BY artist, title LIMIT ?", (limit,)).fetchall()

        where = " AND ".join(["(LOWER(artist) LIKE ? OR LOWER(title) LIKE ?)"] * len(words))
        params: list = []
        for w in words:
            params += [f"%{w}%", f"%{w}%"]
        params.append(limit)
        return self.db.execute(
            f"SELECT * FROM releases WHERE {where} ORDER BY artist, title LIMIT ?",
            params).fetchall()

    def best_collection_match(self, artist: str, album: str):
        """Zoekt de release die past bij wat de herkenning teruggaf.

        Artiest en album worden **apart** beoordeeld en moeten allebei kloppen.
        Dat is niet overdreven streng maar noodzakelijk: telde je de woorden bij
        elkaar op, dan haalt de artiestennaam alleen de drempel al. "Robbie
        Williams - Britpop" tegen "Robbie Williams - Escapology" geeft dan twee
        van de vier woorden gemeen en dat is genoeg om verkeerd te koppelen.

        Zonder albumtitel uit de herkenning koppelen we niets. Dan is het gokken,
        en een verkeerde koppeling is vervelender dan geen.

        Woordoverlap alleen is daarbij te streng, want **een dienst noemt vaak de
        single en jij hebt het album**. Shazam gaf "Natural Blues (Reprise
        Version / Edit) [feat. Gregory Porter & Amythyst Kiah] - Single" terug
        voor wat in de kast gewoon "Reprise" heet: één woord van de elf, oftewel
        0,09. Daarom telt ook of de ene titel volledig in de andere zit — in
        beide richtingen, want "Reprise" tegen "Reprise (Deluxe Edition)" is
        hetzelfde probleem omgekeerd.

        Dat blijft veilig tegen het geval waarvoor de strengheid er kwam:
        "Escapology" zit niet in "Britpop", in geen van beide richtingen.
        """
        want_artist = set(_normalise(artist).split())
        want_album = set(_normalise(album or "").split())
        if not want_artist or not want_album:
            return None

        def overlap(a: set, b: set) -> float:
            return len(a & b) / len(a | b) if (a and b) else 0.0

        def zit_erin(klein: set, groot: set) -> bool:
            """Zit `klein` helemaal in `groot`, en zegt dat ook iets?

            De lengte-eis is er tegen albums die "1" of "Live" heten: die passen
            anders overal in en zouden aan de eerste de beste plaat van dezelfde
            artiest blijven plakken.
            """
            if not klein or not klein <= groot:
                return False
            return any(len(w) >= 4 for w in klein)

        # Hoog genoeg om de drempels te halen, net onder een echte volledige
        # overlap, zodat een letterlijk gelijke titel altijd voorgaat.
        SCORE_BEVAT = 0.85

        best, best_score = None, 0.0
        for row in self.db.execute("SELECT * FROM releases"):
            have_artist = set(_normalise(row["artist"]).split())
            have_album = set(_normalise(row["title"]).split())

            score_artist = overlap(want_artist, have_artist)
            score_album = overlap(want_album, have_album)
            if (zit_erin(have_album, want_album) or zit_erin(want_album, have_album)):
                score_album = max(score_album, SCORE_BEVAT)
            if score_artist < 0.5 or score_album < 0.5:
                continue

            # Het album weegt zwaarder: van een artiest heb je er meestal meer.
            score = 0.35 * score_artist + 0.65 * score_album
            if score > best_score:
                best, best_score = row, score

        return best if best_score >= 0.55 else None

    # -- luisterbeurten ----------------------------------------------------
    def add_play(self, status: str, engine: str = "", artist: str = "", title: str = "",
                 album: str = "", cover_url: str = "", clip: bytes | None = None,
                 release_id: int | None = None, raw: dict | None = None) -> int:
        clip_file = None
        if clip:
            clip_file = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.wav"
            (CLIPS / clip_file).write_bytes(clip)

        cur = self.db.execute(
            """INSERT INTO plays (status, engine, artist, title, album, cover_url,
                                  clip_file, release_id, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (status, engine, artist, title, album, cover_url, clip_file, release_id,
             json.dumps(raw) if raw else None))
        self.db.commit()
        return cur.lastrowid

    def plays(self, status: str | None = None, limit: int = 50):
        if status:
            return self.db.execute(
                "SELECT p.*, r.artist AS r_artist, r.title AS r_title, r.cover_file "
                "FROM plays p LEFT JOIN releases r ON r.id = p.release_id "
                "WHERE p.status = ? ORDER BY p.id DESC LIMIT ?", (status, limit)).fetchall()
        return self.db.execute(
            "SELECT p.*, r.artist AS r_artist, r.title AS r_title, r.cover_file "
            "FROM plays p LEFT JOIN releases r ON r.id = p.release_id "
            "ORDER BY p.id DESC LIMIT ?", (limit,)).fetchall()

    def link_play(self, play_id: int, release_id: int) -> None:
        """De koppelknop uit de wachtrij."""
        self.db.execute("UPDATE plays SET release_id = ?, status = 'gekoppeld' WHERE id = ?",
                        (release_id, play_id))
        self.db.commit()

    def unlink_play(self, play_id: int) -> None:
        """De 'dit klopt niet'-knop: terug de wachtrij in."""
        self.db.execute("UPDATE plays SET release_id = NULL, status = 'onbekend' WHERE id = ?",
                        (play_id,))
        self.db.commit()

    def dismiss_play(self, play_id: int) -> None:
        row = self.db.execute("SELECT clip_file FROM plays WHERE id = ?", (play_id,)).fetchone()
        if row and row["clip_file"]:
            (CLIPS / row["clip_file"]).unlink(missing_ok=True)
        self.db.execute("UPDATE plays SET status = 'weggegooid', clip_file = NULL WHERE id = ?",
                        (play_id,))
        self.db.commit()

    def counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) c FROM plays GROUP BY status")
        return {r["status"]: r["c"] for r in rows}
