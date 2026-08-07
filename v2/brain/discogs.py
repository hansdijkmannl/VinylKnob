"""
Discogs: fetching your collection, searching, and caching artwork.

Two things that differ from most APIs, and that you hit without warning:

  1. Discogs **requires its own User-Agent**. Without that header it refuses
     flatly, with a 403 that does not explain why.
  2. The limit is 60 requests per minute. When syncing we take a hundred
     releases per page and wait in between.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib

import aiohttp

BASE = "https://api.discogs.com"
USER_AGENT = "VinylKnob/0.1 +https://github.com/local/vinylknob"
PER_PAGE = 100
PAUSE = 1.1          # seconds between pages, comfortably inside 60/min


class DiscogsError(Exception):
    pass


class NotFound(DiscogsError):
    """One release is not there; everything else still is."""


def headers(token: str) -> dict:
    h = {"User-Agent": USER_AGENT}
    if token:
        h["Authorization"] = f"Discogs token={token}"
    return h


async def _get(session: aiohttp.ClientSession, url: str, token: str, **params):
    async with session.get(url, headers=headers(token), params=params) as response:
        if response.status == 401:
            raise DiscogsError("token rejected (401)")
        if response.status == 404:
            # Its own class: for the collection this means the username is
            # wrong and nothing will work, but for one release it means that
            # release alone is gone and the rest are fine.
            raise NotFound("not found (404)")
        if response.status == 429:
            raise DiscogsError("too many requests (429), wait a moment")
        if response.status != 200:
            raise DiscogsError(f"HTTP {response.status}")
        return await response.json()


def _simplify(item: dict) -> dict:
    """From a collection entry to the part of it we keep."""
    info = item.get("basic_information") or item
    artists = info.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists) or info.get("artist", "")
    # Discogs appends a (2) to duplicate artist names; we do not want to show that.
    artist = artist.split(" (")[0] if artist.endswith(")") and " (" in artist else artist
    formats = ", ".join(f.get("name", "") for f in (info.get("formats") or []))
    return {
        "discogs_id": str(info.get("id") or item.get("id")),
        "artist": artist.strip(),
        "title": (info.get("title") or "").strip(),
        "year": str(info.get("year") or ""),
        "formats": formats,
        "cover_url": info.get("cover_image") or info.get("thumb") or "",
    }


async def fetch_collection(token: str, user: str, on_page=None) -> list[dict]:
    """Fetch the whole collection. `on_page` gets (page, total) for progress."""
    if not user:
        raise DiscogsError("no username set")

    out: list[dict] = []
    url = f"{BASE}/users/{user}/collection/folders/0/releases"

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        page, pages = 1, 1
        while page <= pages:
            data = await _get(session, url, token, page=page, per_page=PER_PAGE,
                              sort="artist")
            pagination = data.get("pagination") or {}
            pages = pagination.get("pages", 1)
            for item in data.get("releases") or []:
                out.append(_simplify(item))
            if on_page:
                on_page(page, pages)
            page += 1
            if page <= pages:
                await asyncio.sleep(PAUSE)

    return out


def _seconds(duration: str) -> int:
    """"3:55" as 235. Zero when Discogs left it blank, which it often does."""
    parts = (duration or "").strip().split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return 0
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total if total < 60 * 60 else 0        # a bad field, not an hour


async def fetch_tracklist(token: str, discogs_id: str) -> list[dict]:
    """The track titles on one release.

    The collection listing does not carry these — it gives the sleeve and the
    title and nothing about what is on the record — so this is a request per
    release. Worth it: a service names the track it heard and often attributes
    it to whichever release its own metadata prefers, which for anything with a
    hit on it is a compilation. Knowing what is actually on your copies turns
    that guess into a lookup.

    Each entry keeps three things and not one. The title is what a service's
    answer is compared against. The printed position — "A1", "B3" — is the only
    thing here that knows a record has sides, and it is what you would say out
    loud: not "track four" but "A4". And the duration turns a single recognition
    into a timeline of the whole side, which is what lets the screen move on to
    the next track without asking anybody anything.
    """
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        data = await _get(session, f"{BASE}/releases/{discogs_id}", token)
    out = []
    for track in data.get("tracklist") or []:
        # Headings and index tracks have no position and are not songs.
        if (track.get("type_") or "track") != "track":
            continue
        title = (track.get("title") or "").strip()
        if title:
            out.append({
                "title": title,
                "printed": (track.get("position") or "").strip(),
                "secs": _seconds(track.get("duration") or ""),
            })
    return out


async def search(token: str, query: str, limit: int = 20) -> list[dict]:
    """Search all of Discogs. Only for what is not on your own shelf."""
    if not token:
        raise DiscogsError("searching all of Discogs needs a token")

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        data = await _get(session, f"{BASE}/database/search", token,
                          q=query, type="release", per_page=limit)

    out = []
    for item in data.get("results") or []:
        title = item.get("title") or ""
        # Discogs returns "Artist - Title" as a single string here.
        artist, _, rest = title.partition(" - ")
        out.append({
            "discogs_id": str(item.get("id")),
            "artist": artist.strip() if rest else "",
            "title": (rest or title).strip(),
            "year": str(item.get("year") or ""),
            "formats": ", ".join(item.get("format") or []),
            "cover_url": item.get("cover_image") or item.get("thumb") or "",
        })
    return out


async def cache_cover(url: str, folder: pathlib.Path) -> str | None:
    """Fetch a cover and put it on disk. Returns the filename.

    Caching locally is not only polite to Discogs, it is necessary: the device
    has a screen that must be able to show the sleeve every time, including
    when the network is briefly gone.
    """
    if not url:
        return None

    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    target = folder / name
    if target.exists():
        return name

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
                if response.status != 200:
                    return None
                target.write_bytes(await response.read())
        return name
    except Exception:                                 # noqa: BLE001
        return None
