"""
Herkenning. Twee motoren op dezelfde opname:

  shazamio   open-source client voor Shazam, geen sleutel nodig
  AudD       commerciele API; slikt een rauwe audio-upload en is dus ook
             rechtstreeks vanaf een microcontroller aan te roepen

Shazam is de hoofdmotor. AudD staat erbij zodat je kunt blijven vergelijken —
dat bepaalt of het apparaat ooit zonder computer zou kunnen.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp

AUDD_URL = "https://api.audd.io/"


def blank(engine: str) -> dict:
    return {"engine": engine, "matched": False}


# ---------------------------------------------------------------------------
# Shazam
# ---------------------------------------------------------------------------
def _simplify_shazam(result) -> dict:
    track = (result or {}).get("track")
    if not track:
        return blank("Shazam")

    images = track.get("images") or {}
    out = {
        "engine": "Shazam",
        "matched": True,
        "title": track.get("title"),
        "artist": track.get("subtitle"),
        "cover": images.get("coverarthq") or images.get("coverart"),
        "album": None,
        "released": None,
        "label": None,
    }
    for section in track.get("sections") or []:
        for item in section.get("metadata") or []:
            key = (item.get("title") or "").lower()
            if key == "album":
                out["album"] = item.get("text")
            elif key in ("released", "uitgebracht"):
                out["released"] = item.get("text")
            elif key == "label":
                out["label"] = item.get("text")
    return out


async def recognise_shazam(audio: bytes) -> dict:
    started = time.time()
    try:
        from shazamio import Shazam
        out = _simplify_shazam(await Shazam().recognize(audio))
    except Exception as exc:                          # noqa: BLE001
        out = blank("Shazam")
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.time() - started, 2)
    return out


# ---------------------------------------------------------------------------
# AudD
# ---------------------------------------------------------------------------
def _simplify_audd(payload) -> dict:
    result = (payload or {}).get("result")
    if not result:
        return blank("AudD")

    # De hoes zit bij de streamingdiensten, niet in het hoofdantwoord.
    cover = None
    apple = (result.get("apple_music") or {}).get("artwork") or {}
    if apple.get("url"):
        cover = apple["url"].replace("{w}", "600").replace("{h}", "600")
    if not cover:
        images = ((result.get("spotify") or {}).get("album") or {}).get("images") or []
        if images:
            cover = images[0].get("url")

    return {
        "engine": "AudD",
        "matched": True,
        "title": result.get("title"),
        "artist": result.get("artist"),
        "album": result.get("album"),
        "released": result.get("release_date"),
        "label": result.get("label"),
        "cover": cover,
    }


async def recognise_audd(audio: bytes, token: str) -> dict:
    if not token:
        out = blank("AudD")
        out["error"] = "geen sleutel ingesteld"
        return out

    started = time.time()
    try:
        form = aiohttp.FormData()
        form.add_field("api_token", token)
        form.add_field("return", "apple_music,spotify")
        form.add_field("file", audio, filename="sample.wav", content_type="audio/wav")
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(AUDD_URL, data=form) as response:
                payload = await response.json(content_type=None)
        if payload.get("status") == "error":
            out = blank("AudD")
            out["error"] = str((payload.get("error") or {}).get("error_message"))
        else:
            out = _simplify_audd(payload)
    except Exception as exc:                          # noqa: BLE001
        out = blank("AudD")
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.time() - started, 2)
    return out


async def recognise(audio: bytes, audd_token: str = "") -> list[dict]:
    """Allebei tegelijk op dezelfde opname."""
    return list(await asyncio.gather(
        recognise_shazam(audio),
        recognise_audd(audio, audd_token),
    ))


def best(results: list[dict]) -> dict | None:
    """Shazam heeft voorrang; AudD is de reserve."""
    for engine in ("Shazam", "AudD"):
        for r in results:
            if r.get("engine") == engine and r.get("matched"):
                return r
    return None
