#!/usr/bin/env python3
"""
Trying music recognition out - a small web interface.

The browser handles the microphone (so macOS asks permission properly, with a
pop-up) and this little server does the recognition. The same recording goes to
**two** engines at once, so you can compare them directly:

  shazamio   open-source client for Shazam, no key needed, Python only
  AudD       commercial API that swallows a raw audio upload - and so can be
             called from an ESP32 as well

That comparison is the whole reason this exists. If AudD does just as well, the
final device can manage without a computer and an ESP32 board is enough. If AudD
disappoints, that is an argument for putting a Raspberry Pi next to it that can
run shazamio.

    /usr/bin/python3 -m venv .venv          # note: Apple's Python 3.9
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python server.py

Then open http://localhost:8770.

AudD asks for a key. Get one yourself at audd.io (there is a free tier) and put
it in a file `audd_token.txt` next to this script, or in the environment
variable AUDD_TOKEN. Without a key only shazamio works, and the page says so.

Why Apple's Python 3.9 and not your newer one: shazamio leans on a Rust
extension that segfaults on Python 3.14, and on pydub, which needs the `audioop`
module that was taken out of Python in 3.13. On 3.9 everything works without
contortions.
"""

import asyncio
import os
import pathlib
import time

import aiohttp
from aiohttp import web
from shazamio import Shazam

HERE = pathlib.Path(__file__).parent
PORT = 8770
AUDD_URL = "https://api.audd.io/"


def audd_token():
    token = os.environ.get("AUDD_TOKEN", "").strip()
    if token:
        return token
    path = HERE / "audd_token.txt"
    if path.exists():
        return path.read_text().strip()
    return ""


def blank(engine):
    return {"engine": engine, "matched": False}


# ---------------------------------------------------------------------------
# Engine 1: shazamio
# ---------------------------------------------------------------------------
def simplify_shazam(result):
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
    # Album, year and label are tucked away in the first section's metadata.
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


async def recognise_shazam(audio):
    started = time.time()
    try:
        result = await Shazam().recognize(audio)
        out = simplify_shazam(result)
    except Exception as exc:                      # noqa: BLE001
        out = blank("Shazam")
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.time() - started, 2)
    return out


# ---------------------------------------------------------------------------
# Engine 2: AudD
# ---------------------------------------------------------------------------
def simplify_audd(payload):
    result = (payload or {}).get("result")
    if not result:
        return blank("AudD")

    # The sleeve comes from the streaming services, not the main answer.
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


async def recognise_audd(audio, token):
    if not token:
        out = blank("AudD")
        out["error"] = "no key configured"
        return out

    started = time.time()
    try:
        form = aiohttp.FormData()
        form.add_field("api_token", token)
        form.add_field("return", "apple_music,spotify")
        form.add_field("file", audio, filename="sample.wav",
                       content_type="audio/wav")
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(AUDD_URL, data=form) as response:
                payload = await response.json(content_type=None)
        if payload.get("status") == "error":
            out = blank("AudD")
            out["error"] = str((payload.get("error") or {}).get("error_message"))
        else:
            out = simplify_audd(payload)
    except Exception as exc:                      # noqa: BLE001
        out = blank("AudD")
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.time() - started, 2)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
async def handle_recognize(request):
    audio = await request.read()
    if len(audio) < 1000:
        return web.json_response({"error": "no audio received"}, status=400)

    # Both at once, on the same recording. That is the whole point.
    shazam, audd = await asyncio.gather(
        recognise_shazam(audio),
        recognise_audd(audio, audd_token()),
    )
    return web.json_response({"bytes": len(audio), "results": [shazam, audd]})


async def handle_config(_request):
    return web.json_response({"auddConfigured": bool(audd_token())})


async def handle_index(_request):
    return web.FileResponse(HERE / "index.html")


def main():
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/recognize", handle_recognize)

    print(f"\n  Open http://localhost:{PORT} in your browser.")
    print("  The browser asks for microphone permission itself.")
    print("  AudD key: " + ("found" if audd_token()
                            else "not configured, only Shazam active"))
    print("  Ctrl-C stops.\n")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
