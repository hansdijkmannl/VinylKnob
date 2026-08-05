#!/usr/bin/env python3
"""
Het brein — draait straks op de Pi, nu op je Mac.

Luistert, herkent, koppelt aan je Discogs-collectie, en houdt een wachtrij bij
van platen die niet herkend zijn zodat je ze zelf kunt koppelen.

    /usr/bin/python3 -m venv .venv          # let op: Apple's Python 3.9
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python server.py

Dit is de API en niet de website: de webinterface is één pagina met tabbladen en
die wordt door luister.py geserveerd, op poort 8791 en op poort 80. Alles wat
hier onder /api/ staat wordt daar doorgegeven, zodat de browser één adres ziet.

Waarom Apple's Python 3.9 en niet je nieuwere: shazamio leunt op een
Rust-extensie die op Python 3.14 segfault, en op pydub dat de `audioop`-module
nodig heeft die sinds 3.13 uit Python is gesloopt.

Op de Mac neemt de browser op met zijn eigen microfoon. Op de Pi komt daar de
USB-dasspeldmicrofoon voor in de plaats en vraagt het CrowPanel om een
opzoeking; de rest van deze code blijft hetzelfde.
"""

import json
import pathlib
import uuid

from aiohttp import web

import avr
import discogs
import local
import recognise
from store import CLIPS, COVERS, KNOWN_INPUTS, Store

HERE = pathlib.Path(__file__).parent
PORT = 8790

store = Store()


def row_to_release(row) -> dict:
    return {
        "id": row["id"],
        "discogsId": row["discogs_id"],
        "artist": row["artist"],
        "title": row["title"],
        "year": row["year"],
        "formats": row["formats"],
        "cover": f"/api/cover/{row['id']}" if (row["cover_url"] or row["cover_file"]) else None,
    }


def row_to_play(row) -> dict:
    return {
        "id": row["id"],
        "at": row["created_at"],
        "status": row["status"],
        "engine": row["engine"],
        "artist": row["artist"],
        "title": row["title"],
        "album": row["album"],
        "cover": row["cover_url"],
        "clip": f"/api/clip/{row['clip_file']}" if row["clip_file"] else None,
        "releaseId": row["release_id"],
        "releaseArtist": row["r_artist"] if "r_artist" in row.keys() else None,
        "releaseTitle": row["r_title"] if "r_title" in row.keys() else None,
        "releaseCover": f"/api/cover/{row['release_id']}" if row["release_id"] else None,
    }


# ---------------------------------------------------------------------------
# Luisteren
# ---------------------------------------------------------------------------
async def api_listen(request):
    audio = await request.read()
    if len(audio) < 1000:
        return web.json_response({"error": "geen audio ontvangen"}, status=400)

    samples = local.decode_wav(audio)

    # Eerst je eigen database. Gratis, geen netwerk, en werkt ook als shazamio
    # ooit breekt. Pas als dat niets oplevert gaan we een dienst lastigvallen.
    if samples is not None:
        found = local.identify(store.db, samples)
        if found:
            row = store.release(found["releaseId"])
            if row is not None:
                play_id = store.add_play(
                    "herkend", engine="lokaal", artist=row["artist"],
                    title=row["title"], album=row["title"],
                    release_id=row["id"], raw={"local": found})
                return web.json_response({
                    "results": [{"engine": "lokaal", "matched": True,
                                 "artist": row["artist"], "title": row["title"],
                                 "album": row["title"], "seconds": 0,
                                 "cover": f"/api/cover/{row['id']}"}],
                    "playId": play_id, "matched": True, "local": found,
                    "release": row_to_release(row),
                })

    results = await recognise.recognise(audio, store.get("audd_token"))
    store.bump_lookups()
    hit = recognise.best(results)

    if not hit:
        # Onbekend: het fragment bewaren, want daarmee koppel je hem straks zelf.
        play_id = store.add_play("onbekend", clip=audio, raw={"results": results})
        return web.json_response({"results": results, "playId": play_id,
                                  "matched": False, "release": None})

    match = store.best_collection_match(hit.get("artist") or "", hit.get("album") or "")
    play_id = store.add_play(
        "herkend", engine=hit["engine"], artist=hit.get("artist") or "",
        title=hit.get("title") or "", album=hit.get("album") or "",
        cover_url=hit.get("cover") or "",
        clip=None if match else audio,          # zonder plaat in de kast: bewaren
        release_id=match["id"] if match else None,
        raw={"results": results})

    # Onthouden voor de volgende keer. Elke luisterbeurt legt een ander stuk van
    # de kant vast, dus de dekking groeit vanzelf naarmate je een plaat vaker
    # draait — zonder dat je iets hoeft in te lezen.
    if match is not None and samples is not None:
        local.remember(store.db, match["id"], samples)

    return web.json_response({
        "results": results, "playId": play_id, "matched": True,
        "release": row_to_release(match) if match else None,
    })


# ---------------------------------------------------------------------------
# Wachtrij
# ---------------------------------------------------------------------------
async def api_plays(request):
    status = request.query.get("status") or None
    rows = store.plays(status=status, limit=int(request.query.get("limit", 50)))
    return web.json_response({"plays": [row_to_play(r) for r in rows],
                              "counts": store.counts()})


def _remember_clip(play_id: int, release_id: int) -> int:
    """Legt het bewaarde fragment van een luisterbeurt vast bij een release."""
    row = store.db.execute("SELECT clip_file FROM plays WHERE id = ?",
                           (play_id,)).fetchone()
    if not row or not row["clip_file"]:
        return 0
    path = CLIPS / row["clip_file"]
    if not path.exists():
        return 0
    samples = local.decode_wav(path.read_bytes())
    if samples is None:
        return 0
    return local.remember(store.db, release_id, samples)


async def api_link(request):
    play_id = int(request.match_info["id"])
    body = await request.json()
    release_id = int(body["releaseId"])
    store.link_play(play_id, release_id)
    # Zelf gekoppeld is de waardevolste les: precies wat de dienst niet wist.
    hashes = _remember_clip(play_id, release_id)
    return web.json_response({"ok": True, "hashes": hashes})


async def api_unlink(request):
    store.unlink_play(int(request.match_info["id"]))
    return web.json_response({"ok": True})


async def api_dismiss(request):
    store.dismiss_play(int(request.match_info["id"]))
    return web.json_response({"ok": True})


async def api_dismiss_many(request):
    """Een hele selectie in één keer weggooien.

    Bewust één verzoek en niet veertig achter elkaar vanuit de browser: elk
    weggooien verwijdert ook een fragment van anderhalve megabyte, en dat via
    de doorgeefpoort veertig keer heen en weer sturen duurt merkbaar lang op
    een telefoon.
    """
    body = await request.json()
    ids = [int(i) for i in body.get("ids", [])][:500]
    for play_id in ids:
        store.dismiss_play(play_id)
    return web.json_response({"ok": True, "count": len(ids),
                              "counts": store.counts()})


async def api_manual(request):
    """Zelf een plaat opvoeren met een eigen hoes, voor wat Discogs niet kent."""
    play_id = int(request.match_info["id"])
    artist = title = ""
    image = None

    reader = await request.multipart()
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "artist":
            artist = (await part.text()).strip()
        elif part.name == "title":
            title = (await part.text()).strip()
        elif part.name == "cover":
            image = await part.read()

    if not title:
        return web.json_response({"error": "titel is verplicht"}, status=400)

    release_id = store.upsert_release(f"handmatig-{uuid.uuid4().hex[:12]}",
                                      artist, title)
    if image:
        name = f"handmatig-{release_id}.jpg"
        (COVERS / name).write_bytes(image)
        store.set_cover_file(release_id, name)

    store.link_play(play_id, release_id)
    _remember_clip(play_id, release_id)
    return web.json_response({"ok": True, "releaseId": release_id})


# ---------------------------------------------------------------------------
# Discogs
# ---------------------------------------------------------------------------
async def api_sync(request):
    token, user = store.get("discogs_token"), store.get("discogs_user")
    try:
        items = await discogs.fetch_collection(token, user)
    except discogs.DiscogsError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    for item in items:
        store.upsert_release(**item)
    store.set("collection_synced_at", request.loop.time())

    return web.json_response({"ok": True, "count": len(items),
                              "total": store.release_count()})


async def api_collection(request):
    # De platenkast op het schermpje heeft de hele collectie nodig, anders klopt
    # de sprongindex niet: met 40 van de 548 albums kom je niet verder dan de B.
    limit = min(int(request.query.get("limit", 40)), 5000)
    rows = store.search_collection(request.query.get("q", ""), limit=limit)
    return web.json_response({"releases": [row_to_release(r) for r in rows],
                              "total": store.release_count()})


async def api_discogs_search(request):
    try:
        found = await discogs.search(store.get("discogs_token"),
                                     request.query.get("q", ""))
    except discogs.DiscogsError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    # Meteen opnemen in de lokale tabel, zodat koppelen daarna hetzelfde werkt
    # of het nu uit je kast of uit heel Discogs komt.
    out = []
    for item in found:
        rid = store.upsert_release(**item)
        out.append(row_to_release(store.release(rid)))
    return web.json_response({"releases": out})


async def api_cover(request):
    """Hoes serveren, en bij de eerste keer meteen lokaal cachen."""
    row = store.release(int(request.match_info["id"]))
    if row is None:
        raise web.HTTPNotFound()

    if row["cover_file"] and (COVERS / row["cover_file"]).exists():
        return web.FileResponse(COVERS / row["cover_file"])

    name = await discogs.cache_cover(row["cover_url"], COVERS)
    if not name:
        raise web.HTTPNotFound()
    store.set_cover_file(row["id"], name)
    return web.FileResponse(COVERS / name)


async def api_artwork(request):
    """Hoes van een externe dienst, via ons eigen adres en lokaal gecachet.

    Twee redenen. Ten eerste kan de browser de kleuren van een afbeelding van
    een ander domein niet uitlezen — een canvas raakt daarvan "besmet" — en die
    kleuren hebben we nodig om de tekst leesbaar te houden. Ten tweede moet het
    apparaat straks een hoes kunnen tonen als het netwerk er even uit ligt.
    """
    url = request.query.get("url", "")
    if not url.startswith(("http://", "https://")):
        raise web.HTTPBadRequest(text="geen bruikbare url")

    name = await discogs.cache_cover(url, COVERS)
    if not name:
        raise web.HTTPNotFound()
    return web.FileResponse(COVERS / name)


async def api_clip(request):
    path = CLIPS / request.match_info["name"]
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


# ---------------------------------------------------------------------------
# Instellingen
# ---------------------------------------------------------------------------
async def api_get_settings(_request):
    return web.json_response({
        "discogsUser": store.get("discogs_user"),
        "discogsTokenSet": bool(store.get("discogs_token")),
        "auddTokenSet": bool(store.get("audd_token")),
        "collectionCount": store.release_count(),
        "lookups": int(store.get("lookup_count", "0") or 0),
        "screenSpin": store.get("screen_spin", "uit"),
        "localHashes": local.count(store.db)[0],
        "localReleases": local.count(store.db)[1],
        "counts": store.counts(),
    })


async def api_set_settings(request):
    body = await request.json()
    if "discogsUser" in body:
        store.set("discogs_user", body["discogsUser"].strip())
    if body.get("screenSpin") in ("uit", "langzaam", "33"):
        store.set("screen_spin", body["screenSpin"])
    # Een leeg sleutelveld betekent "laat staan", niet "wis het" — anders wist de
    # webinterface je token elke keer dat je iets anders aanpast. Expliciet
    # wissen doe je door null te sturen; dat doet de wisknop.
    for field, key in (("discogsToken", "discogs_token"), ("auddToken", "audd_token")):
        if field in body and body[field] is None:
            store.set(key, "")
            continue
        value = (body.get(field) or "").strip()
        if value:
            store.set(key, value)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Marantz
#
# De instellingen staan hier en niet in de firmware, zodat het CrowPanel ze bij
# het opstarten ophaalt via /api/avr en je ze kunt wijzigen zonder te flashen.
# ---------------------------------------------------------------------------
AVR_FIELDS = {
    "host":          ("avr_host", str),
    "port":          ("avr_port", int),
    "halfDbPerStep": ("avr_half_db_per_step", int),
    "accelFactor":   ("avr_accel_factor", int),
    "accelWindowMs": ("avr_accel_window_ms", int),
    "encDivider":    ("avr_enc_divider", int),
    "volMaxDb":      ("avr_vol_max_db", int),
    "longPressMs":   ("avr_long_press_ms", int),
    "doublePressMs": ("avr_double_press_ms", int),
    "favourite":     ("avr_favourite", int),
}


async def api_get_avr(_request):
    out = {}
    for name, (key, cast) in AVR_FIELDS.items():
        raw = store.get(key)
        try:
            out[name] = cast(raw) if raw != "" else ("" if cast is str else 0)
        except ValueError:
            out[name] = "" if cast is str else 0
    out["inputs"] = json.loads(store.get("avr_inputs") or "[]")
    out["knownInputs"] = KNOWN_INPUTS
    return web.json_response(out)


async def api_set_avr(request):
    body = await request.json()
    for name, (key, cast) in AVR_FIELDS.items():
        if name not in body:
            continue
        value = body[name]
        if cast is int:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        store.set(key, value)

    if isinstance(body.get("inputs"), list):
        clean = []
        for item in body["inputs"]:
            code = (item.get("code") or "").strip()
            if not code:
                continue
            clean.append({"code": code,
                          "label": (item.get("label") or "").strip() or code})
        store.set("avr_inputs", json.dumps(clean[:8]))
    return web.json_response({"ok": True})


async def api_avr_test(request):
    """Test wat er in het formulier staat, niet wat er is opgeslagen.

    Anders moet je eerst opslaan voordat je kunt proberen of het adres klopt,
    en dat is precies de verkeerde volgorde.
    """
    host, port = "", 0
    try:
        body = await request.json()
        host = (body.get("host") or "").strip()
        port = int(body.get("port") or 0)
    except Exception:                                      # noqa: BLE001
        pass

    host = host or store.get("avr_host")
    port = port or int(store.get("avr_port") or 23)
    result = await avr.probe(host, port)

    # Werkt het adres, dan meteen bewaren. Anders moet je na een geslaagde test
    # alsnog op opslaan drukken, en dat vergeet je precies één keer.
    if result.get("ok"):
        store.set("avr_host", host)
        store.set("avr_port", port)
        result["saved"] = True
    return web.json_response(result)


# -- blijvende verbinding, zodat het schermpje echt bedient -----------------
async def api_avr_connect(request):
    try:
        body = await request.json()
    except Exception:                                      # noqa: BLE001
        body = {}
    host = (body.get("host") or store.get("avr_host")).strip()
    port = int(body.get("port") or store.get("avr_port") or 23)
    return web.json_response(await avr.link.connect(host, port))


async def api_avr_disconnect(_request):
    await avr.link.disconnect()
    return web.json_response(avr.link.state)


async def api_avr_state(_request):
    return web.json_response(avr.link.state)


async def api_avr_send(request):
    """Ruw commando over de open verbinding, bijvoorbeeld MUON of SIPHONO."""
    command = request.query.get("cmd", "")
    if not command:
        return web.json_response({"ok": False, "error": "geen commando"}, status=400)
    if not avr.link.state["connected"]:
        return web.json_response({"ok": False, "error": "niet verbonden"}, status=409)
    return web.json_response({"ok": await avr.link.send(command)})


async def api_avr_volume(request):
    body = await request.json()
    if not avr.link.state["connected"]:
        return web.json_response({"ok": False, "error": "niet verbonden"}, status=409)
    ok = await avr.link.set_volume_db(float(body["db"]))
    return web.json_response({"ok": ok, "state": avr.link.state})


# ---------------------------------------------------------------------------
async def index(request):
    """Het brein heeft geen eigen pagina meer.

    De webinterface is één pagina met tabbladen geworden, en die wordt geserveerd
    door de oren (luister.py) omdat daar ook de microfoon, de Apple TV en de
    doorgeefpoort naar het paneel zitten. Wat hier overblijft is de API — die
    pagina haalt hem op via /api/*, doorgegeven op hetzelfde adres.

    Wie hier toch op poort 8790 belandt, sturen we door. Draait het brein los op
    een Mac zonder luister.py, dan komt die verwijzing nergens uit; dan is dit
    ook gewoon een API-server en geen website.
    """
    raise web.HTTPFound(f"http://{request.url.host}:8791/")


def main():
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_post("/api/listen", api_listen)
    app.router.add_get("/api/plays", api_plays)
    app.router.add_post("/api/plays/{id}/link", api_link)
    app.router.add_post("/api/plays/{id}/unlink", api_unlink)
    # Vóór de route met {id}, anders vangt die "dismiss" op als nummer.
    app.router.add_post("/api/plays/dismiss", api_dismiss_many)
    app.router.add_post("/api/plays/{id}/dismiss", api_dismiss)
    app.router.add_post("/api/plays/{id}/manual", api_manual)
    app.router.add_post("/api/discogs/sync", api_sync)
    app.router.add_get("/api/collection", api_collection)
    app.router.add_get("/api/discogs/search", api_discogs_search)
    app.router.add_get("/api/cover/{id}", api_cover)
    app.router.add_get("/api/artwork", api_artwork)
    app.router.add_get("/api/clip/{name}", api_clip)
    app.router.add_get("/api/avr", api_get_avr)
    app.router.add_post("/api/avr", api_set_avr)
    app.router.add_post("/api/avr/test", api_avr_test)
    app.router.add_post("/api/avr/send", api_avr_send)
    app.router.add_post("/api/avr/connect", api_avr_connect)
    app.router.add_post("/api/avr/disconnect", api_avr_disconnect)
    app.router.add_get("/api/avr/state", api_avr_state)
    app.router.add_post("/api/avr/volume", api_avr_volume)
    app.router.add_get("/api/settings", api_get_settings)
    app.router.add_post("/api/settings", api_set_settings)

    print(f"\n  Brein-API op poort {PORT}. De webinterface draait bij de oren "
          "(luister.py) en haalt hem hier op.")
    print(f"  Collectie: {store.release_count()} releases, "
          f"AudD-sleutel {'gevonden' if store.get('audd_token') else 'niet ingesteld'}.")
    print("  Ctrl-C stopt.\n")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()

