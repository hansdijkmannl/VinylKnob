#!/usr/bin/env python3
"""
Muziekherkenning uitproberen - klein webinterfaceje.

De browser doet de microfoon (dan regelt macOS de toestemming netjes via een
pop-up), dit servertje doet de herkenning. Dezelfde opname gaat naar **twee**
motoren tegelijk, zodat je ze rechtstreeks kunt vergelijken:

  shazamio   open-source client voor Shazam, geen sleutel nodig, alleen Python
  AudD       commerciele API die een rauwe audio-upload slikt - en dus ook
             vanaf een ESP32 aan te roepen is

Die vergelijking is de hele reden dat dit bestaat. Draait AudD net zo goed, dan
kan het uiteindelijke apparaat het zonder computer af en volstaat een
ESP32-bordje. Valt AudD tegen, dan is dat een argument om er een Raspberry Pi
bij te zetten die shazamio kan draaien.

    /usr/bin/python3 -m venv .venv          # let op: Apple's Python 3.9
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python server.py

Daarna http://localhost:8770 openen.

AudD vraagt een sleutel. Haal er zelf een op bij audd.io (er is een gratis
proefniveau) en zet hem in een bestand `audd_token.txt` naast dit script, of in
de omgevingsvariabele AUDD_TOKEN. Zonder sleutel werkt alleen shazamio en zegt
de pagina dat erbij.

Waarom Apple's Python 3.9 en niet je nieuwere: shazamio leunt op een
Rust-extensie die op Python 3.14 segfault, en op pydub dat de `audioop`-module
nodig heeft die sinds 3.13 uit Python is gesloopt. Op 3.9 werkt alles zonder
kunstgrepen.
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
# Motor 1: shazamio
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
    # Album, jaar en label zitten weggestopt in de metadata van de eerste sectie.
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
# Motor 2: AudD
# ---------------------------------------------------------------------------
def simplify_audd(payload):
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


async def recognise_audd(audio, token):
    if not token:
        out = blank("AudD")
        out["error"] = "geen sleutel ingesteld"
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
        return web.json_response({"error": "geen audio ontvangen"}, status=400)

    # Allebei tegelijk, op dezelfde opname. Dat is het hele punt.
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

    print(f"\n  Open http://localhost:{PORT} in je browser.")
    print("  De browser vraagt zelf toestemming voor de microfoon.")
    print("  AudD-sleutel: " + ("gevonden" if audd_token()
                                else "niet ingesteld, alleen Shazam actief"))
    print("  Ctrl-C stopt.\n")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
