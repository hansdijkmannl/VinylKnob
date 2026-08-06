"""
Storage for the brain: settings, your Discogs collection, and everything it
has listened to.

One SQLite file plus two directories on disk (sleeves and audio clips).
Runs on the Pi and on a laptop alike — there is nothing platform-specific
about it.
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
    cover_file  TEXT,          -- file name in data/covers
    added_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rel_artist ON releases(artist);
CREATE INDEX IF NOT EXISTS idx_rel_title  ON releases(title);
-- What is actually on each record. Filled in a second pass over the
-- collection, one request per release, because the collection listing does not
-- carry it. `norm` is the comparable form; `title` is kept as printed so a
-- chooser can show it the way the sleeve does.
CREATE TABLE IF NOT EXISTS tracks (
    release_id  INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    norm        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_norm    ON tracks(norm);
CREATE INDEX IF NOT EXISTS idx_tracks_release ON tracks(release_id);

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
    clip_file   TEXT,              -- file name in data/clips
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


# Words that appear in a title without identifying a record: compilation and
# edition boilerplate. They are not dropped from the comparison — "Greatest
# Hits" is a perfectly good album title and matches exactly like any other — but
# they cannot on their own carry a *containment* match. See contained_in below
# for the wrong sleeve that produced this list.
GENERIC_TITLE_WORDS = {
    "greatest", "hits", "best", "collection", "anthology", "singles",
    "essential", "very", "volume", "live", "album", "songs", "music",
    "edition", "deluxe", "remaster", "remastered", "anniversary", "expanded",
    "compilation", "complete", "ultimate", "selected", "favourites",
    "favorites", "more", "vol",
}


def _normalise(text: str) -> str:
    """For comparing titles: lower case, no punctuation."""
    keep = [c.lower() if c.isalnum() else " " for c in (text or "")]
    words = "".join(keep).split()
    # Drop the articles; "The Beatles" and "Beatles" ought to match. The Dutch
    # ones are in there alongside the English: this collection has both, and
    # "De Nachtzuster" should compare equal to "Nachtzuster".
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
        # Records entered by hand carry a made-up id, and that prefix used to be
        # a Dutch word. The sleeve is named after it, so the file has to move
        # with the row or the picture goes missing.
        for row in self.db.execute(
                "SELECT id, discogs_id, cover_file FROM releases "
                "WHERE discogs_id LIKE 'handmatig-%' OR cover_file LIKE 'handmatig-%'"):
            new_id = "byhand-" + row["discogs_id"][len("handmatig-"):] \
                if (row["discogs_id"] or "").startswith("handmatig-") else row["discogs_id"]
            new_cover = row["cover_file"]
            if (new_cover or "").startswith("handmatig-"):
                new_cover = "byhand-" + new_cover[len("handmatig-"):]
                old_path, new_path = COVERS / row["cover_file"], COVERS / new_cover
                if old_path.exists():
                    old_path.rename(new_path)
                elif not new_path.exists():
                    new_cover = None      # the file was already gone; do not point at it
            self.db.execute(
                "UPDATE releases SET discogs_id = ?, cover_file = ? WHERE id = ?",
                (new_id, new_cover, row["id"]))

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

        def drop_artist(heard: set, have: set) -> tuple[set, set]:
            """Both titles with the artist's name taken out, where it is noise.

            Services regularly hand the artist back glued onto the title:
            Shazam called Hans Zimmer's album "Live" simply "HANS ZIMMER LIVE".
            Those two words are not part of the title, they are the artist
            again, and leaving them in turns an exact match into a partial one
            that containment then has to rescue — on the word "live", which is
            exactly what containment should not trust.

            But an artist's name can genuinely be part of a title: "The
            Greatest Showman" by "The Greatest Showman Cast". So only words
            that are *not* on both sides are dropped. Present in both means it
            belongs to the title, not to the artist.
            """
            noise = want_artist - (heard & have)
            return (heard - noise) or heard, (have - noise) or have

        def overlap(a: set, b: set) -> float:
            return len(a & b) / len(a | b) if (a and b) else 0.0

        def contained_in(small: set, large: set) -> bool:
            """Is `small` wholly inside `large`, and does that mean anything?

            The length requirement guards against albums called "1" or "Live":
            those fit inside anything and would otherwise stick to the first
            record by the same artist.

            The second requirement is the same guard for a subtler case, and it
            cost a wrong sleeve to find. Shazam heard "I Will Talk And Hollywood
            Will Listen" and named it from the compilation "In And Out Of
            Consciousness: Greatest Hits 1990 - 2010". The record on the
            turntable was "Swing When You're Winning" — but "Greatest Hits" is
            also a release on this shelf, and those two words sit inside that
            compilation title, so containment fired and the wrong sleeve came
            up.

            Containment therefore needs one word that actually identifies a
            record. "Reprise" does, "Showman" does; "greatest hits" is a phrase
            half the compilations in the world carry. Note this only tightens
            the containment path: own a record genuinely called "Greatest Hits"
            and a service that names it exactly still matches on overlap.
            """
            if not small or not small <= large:
                return False
            return any(len(w) >= 4 and w not in GENERIC_TITLE_WORDS for w in small)

        # High enough to clear the thresholds, just below a genuine full
        # overlap, so a literally identical title always wins.
        SCORE_CONTAINED = 0.85

        best, best_score = None, 0.0
        for row in self.db.execute("SELECT * FROM releases"):
            have_artist = set(_normalise(row["artist"]).split())
            heard_album, have_album = drop_artist(
                want_album, set(_normalise(row["title"]).split()))

            score_artist = overlap(want_artist, have_artist)
            score_album = overlap(heard_album, have_album)
            if contained_in(have_album, heard_album) or contained_in(heard_album, have_album):
                score_album = max(score_album, SCORE_CONTAINED)
            if score_artist < 0.5 or score_album < 0.5:
                continue

            # The album weighs more: you usually own several by one artist.
            score = 0.35 * score_artist + 0.65 * score_album
            if score > best_score:
                best, best_score = row, score

        return best if best_score >= 0.55 else None

    # -- what is on the records --------------------------------------------
    def set_tracks(self, release_id: int, titles: list[str]) -> None:
        self.db.execute("DELETE FROM tracks WHERE release_id = ?", (release_id,))
        self.db.executemany(
            "INSERT INTO tracks (release_id, position, title, norm) VALUES (?, ?, ?, ?)",
            [(release_id, i, t, _normalise(t)) for i, t in enumerate(titles)])
        self.db.commit()

    def releases_without_tracks(self, limit: int = 50) -> list:
        return list(self.db.execute(
            "SELECT r.id, r.discogs_id, r.artist, r.title FROM releases r "
            "LEFT JOIN tracks t ON t.release_id = r.id "
            "WHERE t.release_id IS NULL ORDER BY r.id LIMIT ?", (limit,)))

    def track_counts(self) -> tuple[int, int]:
        """(releases with a tracklist, releases in total)."""
        with_tracks = self.db.execute(
            "SELECT COUNT(DISTINCT release_id) c FROM tracks").fetchone()["c"]
        total = self.release_count()
        return with_tracks, total

    def releases_with_track(self, artist: str, track: str) -> list:
        """Your records by this artist that carry this song.

        The question a recognition service cannot answer, because it does not
        know what you own. It names a track and then attributes it to whichever
        release its own metadata prefers — for anything with a hit on it, that
        is usually a compilation. Which of *your* copies the song is on is a
        different question, and this is it.

        Ordered oldest first, so the original album comes before the collection
        that reissued it.
        """
        want = _normalise(track)
        if not want:
            return []
        rows = self.db.execute(
            "SELECT DISTINCT r.* FROM releases r JOIN tracks t ON t.release_id = r.id "
            "WHERE t.norm = ? ORDER BY r.year, r.id", (want,))
        want_artist = set(_normalise(artist).split())
        out, seen = [], set()
        for row in rows:
            have = set(_normalise(row["artist"]).split())
            if not (want_artist and have):
                continue
            if len(want_artist & have) / len(want_artist | have) < 0.5:
                continue
            # Two copies of the same record are not a choice. Plenty of shelves
            # have a second pressing, or the same album on vinyl and on CD, and
            # offering both would be asking a question with one answer written
            # twice. Oldest first, so it is the original that survives.
            key = (_normalise(row["artist"]), _normalise(row["title"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    def decide_release(self, artist: str, title: str, album: str):
        """Which of your records a recognised track came off.

        Returns ``(match, choices)``. ``match`` is the release to settle on, or
        None when it cannot be settled; ``choices`` is every record of yours that
        carries this track, which is only interesting when there is more than one.

        A service names the track it heard and then names a release to go with it,
        and that second part is its opinion, not yours: for anything with a hit on
        it the metadata prefers a compilation. So ask the tracklists first — which
        of *your* copies actually carries this song — and fall back to comparing
        album titles when the tracklists cannot say.

        Kept out of the request handler because it is the one decision here
        that can be wrong in interesting ways, and a decision you can call from a
        test is a decision you can keep honest.
        """
        choices = self.releases_with_track(artist, title)
        if len(choices) == 1:
            return choices[0], choices
        if len(choices) > 1:
            # Genuinely on more than one record you own: the album and the
            # collection that reissued it. Nothing here can tell which platter is
            # spinning, so it is offered rather than guessed.
            return None, choices
        return self.best_collection_match(artist, album), choices

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
        """Listens, newest first. `status` may name several, comma-separated.

        Several, because two different things are waiting for you and they wait
        in the same place: a record nothing recognised, and a track that is on
        more than one of your records. Both are a question, so both belong in
        the queue.
        """
        if status:
            want = [s for s in status.split(",") if s]
            holes = ",".join("?" * len(want))
            return self.db.execute(
                "SELECT p.*, r.artist AS r_artist, r.title AS r_title, r.cover_file "
                "FROM plays p LEFT JOIN releases r ON r.id = p.release_id "
                f"WHERE p.status IN ({holes}) ORDER BY p.id DESC LIMIT ?",
                (*want, limit)).fetchall()
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
