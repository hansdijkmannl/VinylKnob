"""
Discogs: je collectie ophalen, zoeken, en hoezen cachen.

Twee dingen die anders zijn dan bij de meeste API's en waar je zonder waarschuwing
op stukloopt:

  1. Discogs **eist een eigen User-Agent**. Zonder die header weigert hij botweg,
     met een 403 die niet uitlegt waarom.
  2. De limiet is 60 aanvragen per minuut. Bij het synchroniseren halen we
     honderd releases per pagina op en wachten we ertussen.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib

import aiohttp

BASE = "https://api.discogs.com"
USER_AGENT = "MarantzKnob/0.1 +https://github.com/local/marantzknob"
PER_PAGE = 100
PAUSE = 1.1          # seconden tussen pagina's, ruim binnen 60/min


class DiscogsError(Exception):
    pass


def headers(token: str) -> dict:
    h = {"User-Agent": USER_AGENT}
    if token:
        h["Authorization"] = f"Discogs token={token}"
    return h


async def _get(session: aiohttp.ClientSession, url: str, token: str, **params):
    async with session.get(url, headers=headers(token), params=params) as response:
        if response.status == 401:
            raise DiscogsError("token afgewezen (401)")
        if response.status == 404:
            raise DiscogsError("niet gevonden (404) - klopt de gebruikersnaam?")
        if response.status == 429:
            raise DiscogsError("te veel aanvragen (429), even wachten")
        if response.status != 200:
            raise DiscogsError(f"HTTP {response.status}")
        return await response.json()


def _simplify(item: dict) -> dict:
    """Van een collectieregel naar wat wij ervan bewaren."""
    info = item.get("basic_information") or item
    artists = info.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists) or info.get("artist", "")
    # Discogs zet een (2) achter dubbele artiestennamen; dat willen we niet tonen.
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
    """Haalt de hele collectie op. `on_page` krijgt (pagina, totaal) voor voortgang."""
    if not user:
        raise DiscogsError("geen gebruikersnaam ingesteld")

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


async def search(token: str, query: str, limit: int = 20) -> list[dict]:
    """Zoekt in heel Discogs. Alleen gebruiken als het niet in je eigen kast staat."""
    if not token:
        raise DiscogsError("zoeken in heel Discogs vraagt een token")

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        data = await _get(session, f"{BASE}/database/search", token,
                          q=query, type="release", per_page=limit)

    out = []
    for item in data.get("results") or []:
        title = item.get("title") or ""
        # Discogs geeft hier "Artiest - Titel" als één string terug.
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
    """Haalt een hoes op en zet hem op schijf. Geeft de bestandsnaam terug.

    Lokaal cachen is niet alleen netjes tegenover Discogs, het is ook nodig:
    straks hangt het apparaat aan een scherm dat de hoes bij elke weergave moet
    kunnen tonen, ook als het netwerk er even uit ligt.
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
