"""
Recognition. Two engines on the same recording:

  shazamio   open-source client for Shazam, no key needed
  AudD       commercial API; takes a raw audio upload, so it can also be called
             straight from a microcontroller

Shazam is the main engine. AudD sits alongside it so the two stay comparable —
that is what decides whether the device could ever work without a computer.

Neither is the one that matters most. See local.py: what you link by hand is
recognised for free, forever, without asking anyone.
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
    # How far into the song this clip was, in seconds, and how far off the
    # turntable's speed is. Both come out of the match itself and were being
    # thrown away with the rest of the raw answer.
    #
    # The offset is what makes a countdown possible at all. A duration tells you
    # how long a song is and nothing about where you are in it, so on its own it
    # cannot say when this one ends. Measured on a real clip: 170.58 seconds in,
    # with the speed 0.07 per cent out — which over a four-minute side is a sixth
    # of a second and not worth correcting for.
    match = ((result or {}).get("matches") or [{}])[0]
    out = {
        "engine": "Shazam",
        "matched": True,
        "title": track.get("title"),
        "artist": track.get("subtitle"),
        "cover": images.get("coverarthq") or images.get("coverart"),
        "album": None,
        "released": None,
        "label": None,
        "offset": match.get("offset"),
        "skew": match.get("timeskew"),
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

    # The artwork lives with the streaming services, not in the main answer.
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


# A token whose quota has run out, and when to believe in it again.
#
# AudD answers a spent trial with an ordinary error and takes the upload first, so
# without this every lookup ships a megabyte and a half to be told no — and the
# error lands in the listen's record as though something had gone wrong with the
# record rather than with the account. A day, because quotas do reset and a
# permanent "never again" would need you to notice and clear it by hand.
_audd_spent_until = 0.0
_AUDD_BACKOFF_S = 24 * 60 * 60

# What a spent account sounds like, as opposed to a network hiccup.
_AUDD_SPENT = ("limit was reached", "limit reached", "authorization failed",
               "no api_token", "wrong api_token")


def audd_spent() -> bool:
    """Is the key being skipped because it has run out? For the web interface."""
    return time.time() < _audd_spent_until


async def recognise_audd(audio: bytes, token: str) -> dict:
    global _audd_spent_until
    if not token:
        out = blank("AudD")
        out["error"] = "no key set"
        return out
    if audd_spent():
        out = blank("AudD")
        out["error"] = "limit reached — not asking again today"
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
            message = str((payload.get("error") or {}).get("error_message"))
            out["error"] = message
            # A spent trial is not a failed recognition; asking again is asking
            # the same question of the same empty account.
            if any(s in message.lower() for s in _AUDD_SPENT):
                _audd_spent_until = time.time() + _AUDD_BACKOFF_S
                print(f"[audd] {message} — leaving it alone for a day", flush=True)
        else:
            out = _simplify_audd(payload)
    except Exception as exc:                          # noqa: BLE001
        out = blank("AudD")
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.time() - started, 2)
    return out


async def recognise(audio: bytes, audd_token: str = "") -> list[dict]:
    """Both at once, on the same recording."""
    return list(await asyncio.gather(
        recognise_shazam(audio),
        recognise_audd(audio, audd_token),
    ))


def best(results: list[dict]) -> dict | None:
    """Shazam wins; AudD is the fallback."""
    for engine in ("Shazam", "AudD"):
        for r in results:
            if r.get("engine") == engine and r.get("matched"):
                return r
    return None
