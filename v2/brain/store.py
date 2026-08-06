"""
Storage for the brain: settings, your Discogs collection, and everything that
geluisterd is.

One SQLite file plus two directories on disk (sleeves and audio clips).
Runs on the Pi and on a laptop alike — there is nothing platform-specific
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

-- Your Discogs collection, cached locally so that searching does not need the
-- network every time, and so that it works offline.
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

-- Every listen. Recognised or not, all of it lands here.
CREATE TABLE IF NOT EXISTS plays (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    status      TEXT NOT NULL,     -- recognised | unknown | linked | discarded
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

    # Settings for the receiver. They live here rather than in the firmware so
    # the panel can fetch them at boot and you can change them without
    # reflashing. Same division as in version 1: the device shows,
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

# Inputs as the Denon/Marantz protocol names them.
KNOWN_INPUTS = [
    "PHONO", "CD", "TUNER", "DVD", "BD", "TV", "SAT/CBL", "MPLAY", "GAME",
    "8K", "AUX1", "AUX2", "NET", "BT", "USB", "HDRADIO", "SPOTIFY", "IRADIO",
    "SERVER", "FAVORITES",
]


def _normalise(text: str) -> str:
    """For comparing titles: lower case, no punctuation."""
    keep = [c.lower() if c.isalnum() else " " for c in (text or "")]
    words = "".join(keep).split()
    # Lidwoorden weglaten; "The Beatles" en "Beatles" horen te matchen.
    # Dutch articles alongside the English ones: this collection has both,
    # and "De Nachtzuster" should compare equal to "Nachtzuster".
    skip = {"the", "a", "an", "de", "het", "een"}
    return " ".join(w for w in words if w not in skip)


class Store:
    def __init__(self, path: str | None = None):
        DATA.mkdir(exist_ok=True)
        COVERS.mkdir(exist_ok=True)
        CLIPS.mkdir(exist_ok=True)
        self.db = sqlite3.connect(path or (DATA / "brain.db"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        import local                       # our own fingerprint database
        local.ensure_schema(self.db)
        self._migrate()
        for key, value in DEFAULTS.items():
            self.db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                            (key, value))
        self.db.commit()

    def _migrate(self) -> None:
        """Bring an older database up to date.

        The status values used to be Dutch. Renaming them in the code alone
        would have made every existing listen invisible — the queue filters on
        the value, so a database full of 'onbekend' would simply look empty.
        Cheap to run every start, and a no-op once done.
        """
        renamed = {"herkend": "recognised", "onbekend": "unknown",
                   "gekoppeld": "linked", "weggegooid": "discarded"}
        for old, new in renamed.items():
            self.db.execute("UPDATE plays SET status = ? WHERE status = ?", (new, old))
        self.db.execute("UPDATE plays SET engine = 'local' WHERE engine = 'lokaal'")
        self.db.execute("DELETE FROM settings WHERE key = 'screen_spin'")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- settings ----------------------------------------------------------
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
        """Search your own shelf. Loose words; order does not matter."""
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
        """Find the release matching what recognition returned.

        Artist and album are judged **separately** and both have to hold up.
        That is not excessive strictness but necessary: add the words together
        and the artist name alone clears the bar. "Robbie Williams - Britpop"
        against "Robbie Williams - Escapology" then shares two words out of
        four, which is enough to link the wrong record.

        With no album title from recognition we link nothing. That would be
        guessing, and a wrong link is worse than none.

        Word overlap on its own is too strict, though, because **a service often
        names the single where you own the album**. Shazam returned "Natural
        Blues (Reprise Version / Edit) [feat. Gregory Porter & Amythyst Kiah] -
        Single" for what is simply called "Reprise" on the shelf: one word out
        of eleven, or 0.09. So containment counts too — in both directions,
        because "Reprise" against "Reprise (Deluxe Edition)" is the same problem
        reversed.

        That stays safe against the case the strictness was added for:
        "Escapology" is not inside "Britpop", in either direction.
        """
        want_artist = set(_normalise(artist).split())
        want_album = set(_normalise(album or "").split())
        if not want_artist or not want_album:
            return None

        def overlap(a: set, b: set) -> float:
            return len(a & b) / len(a | b) if (a and b) else 0.0

        def contained_in(small: set, large: set) -> bool:
            """Is `small` wholly inside `large`, and does that mean anything?

            The length requirement guards against albums called "1" or "Live":
            those fit inside anything and would otherwise stick to the first
            record by the same artist.
            """
            if not small or not small <= large:
                return False
            return any(len(w) >= 4 for w in small)

        # High enough to clear the thresholds, just below a genuine full
        # overlap, so a literally identical title always wins.
        SCORE_CONTAINED = 0.85

        best, best_score = None, 0.0
        for row in self.db.execute("SELECT * FROM releases"):
            have_artist = set(_normalise(row["artist"]).split())
            have_album = set(_normalise(row["title"]).split())

            score_artist = overlap(want_artist, have_artist)
            score_album = overlap(want_album, have_album)
            if contained_in(have_album, want_album) or contained_in(want_album, have_album):
                score_album = max(score_album, SCORE_CONTAINED)
            if score_artist < 0.5 or score_album < 0.5:
                continue

            # The album weighs more: you usually own several by one artist.
            score = 0.35 * score_artist + 0.65 * score_album
            if score > best_score:
                best, best_score = row, score

        return best if best_score >= 0.55 else None

    # -- listens -----------------------------------------------------------
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
        """The link button in the queue."""
        self.db.execute("UPDATE plays SET release_id = ?, status = 'linked' WHERE id = ?",
                        (release_id, play_id))
        self.db.commit()

    def unlink_play(self, play_id: int) -> None:
        """The 'that is wrong' button: back into the queue."""
        self.db.execute("UPDATE plays SET release_id = NULL, status = 'unknown' WHERE id = ?",
                        (play_id,))
        self.db.commit()

    def dismiss_play(self, play_id: int) -> None:
        row = self.db.execute("SELECT clip_file FROM plays WHERE id = ?", (play_id,)).fetchone()
        if row and row["clip_file"]:
            (CLIPS / row["clip_file"]).unlink(missing_ok=True)
        self.db.execute("UPDATE plays SET status = 'discarded', clip_file = NULL WHERE id = ?",
                        (play_id,))
        self.db.commit()

    def counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) c FROM plays GROUP BY status")
        return {r["status"]: r["c"] for r in rows}
