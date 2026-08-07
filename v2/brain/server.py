#!/usr/bin/env python3
"""
The brain.

Recognises, links to your Discogs collection, and keeps a queue of records it
could not place so you can link them yourself.

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python server.py

This is the API, not the website. The web interface is one page with tabs and
is served by listen.py on ports 8791 and 80; everything under /api/ here is
passed through there, so the browser only ever sees one address.

A note on Python versions: shazamio leans on a Rust extension that segfaults on
some newer releases, and on pydub, which needs the `audioop` module that was
removed from the standard library in 3.13. On Python 3.13 or later, install
`audioop-lts` alongside it — the Pi installer does this for you.
"""

import asyncio
import json
import pathlib
import time
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


def track_seen(release_id, title: str) -> dict | None:
    """Where on the record we are, as the sleeve prints it.

    A service names a track; the sleeve names a side and a number. "A4 · Angels"
    is what you would say out loud and "track eight of eleven" is not, and the
    difference is only knowable because the printed position is kept.
    """
    if not release_id or not title:
        return None
    row = store.track_on(release_id, title)
    if row is None:
        return None
    return {"printed": row["printed"], "title": row["title"], "secs": row["secs"]}


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
# Listening
# ---------------------------------------------------------------------------
async def api_listen(request):
    audio = await request.read()
    if len(audio) < 1000:
        return web.json_response({"error": "no audio received"}, status=400)

    samples = local.decode_wav(audio)

    # Your own database first. Free, no network, and it keeps working if
    # shazamio ever breaks. Only when that comes up empty do we bother a
    # service.
    if samples is not None:
        found = local.identify(store.db, samples)
        if found:
            row = store.release(found["releaseId"])
            if row is not None:
                play_id = store.add_play(
                    "recognised", engine="local", artist=row["artist"],
                    title=row["title"], album=row["title"],
                    release_id=row["id"], raw={"local": found})
                return web.json_response({
                    "results": [{"engine": "local", "matched": True,
                                 "artist": row["artist"], "title": row["title"],
                                 "album": row["title"], "seconds": 0,
                                 "cover": f"/api/cover/{row['id']}"}],
                    "playId": play_id, "matched": True, "local": found,
                    "release": row_to_release(row),
                    # Recognised from our own fingerprints, so there is no track
                    # name in the answer — the offset says where on the side we
                    # are, and the tracklist can say which track that is.
                    "track": None,
                })

    results = await recognise.recognise(audio, store.get("audd_token"))
    store.bump_lookups()
    hit = recognise.best(results)

    if not hit:
        # Unknown: keep the clip, because that is what you link it with later.
        play_id = store.add_play("unknown", clip=audio, raw={"results": results})
        return web.json_response({"results": results, "playId": play_id,
                                  "matched": False, "release": None})

    # Which of your records is this, then.
    artist = hit.get("artist") or ""
    match, choices = store.decide_release(artist, hit.get("title") or "",
                                          hit.get("album") or "")

    play_id = store.add_play(
        # Recognised, but on more than one of your records: that is not settled,
        # it is a question, and it has to end up somewhere you will find it. The
        # panel asks it while the needle is still down; the queue asks it the
        # next morning, when you were not standing there.
        "choose" if match is None and len(choices) > 1 else "recognised",
        engine=hit["engine"], artist=artist,
        title=hit.get("title") or "", album=hit.get("album") or "",
        cover_url=hit.get("cover") or "",
        # Keep the clip whenever nothing was linked, because that is what a
        # later choice is hung on — including when there are several to choose
        # between.
        clip=None if match else audio,
        release_id=match["id"] if match else None,
        raw={"results": results})

    # Remember it for next time. Each listen captures a different stretch of
    # the side, so coverage grows on its own the more you play a record —
    # without importing anything up front.
    if match is not None and samples is not None:
        local.remember(store.db, match["id"], samples)

    return web.json_response({
        "results": results, "playId": play_id, "matched": True,
        "release": row_to_release(match) if match else None,
        "track": track_seen(match["id"] if match else None,
                            hit.get("title") or ""),
        # The records this track is on, when there is more than one. Empty
        # otherwise, so nothing downstream has to care about the common case.
        "choices": [row_to_release(r) for r in choices] if len(choices) > 1 else [],
    })


async def api_enrol(request):
    """More of a side we already know, as fingerprints against that release.

    Not a lookup. Nothing is recognised here and nothing is asked of anybody —
    the caller already knows which record is on, and this only widens what this
    device can recognise by itself next time.

    It exists because coverage was the quiet weakness. Each listen enrolled the
    eight seconds it happened to sample, so a twenty-minute side needed dozens
    of plays before the needle was likely to land on a stretch we knew. Forty
    three records out of five hundred and forty nine after a week says it
    plainly enough. Sampling the same side every half minute while it plays
    costs no requests to anyone and covers the whole of it in one go.
    """
    try:
        release_id = int(request.query.get("release", ""))
    except ValueError:
        return web.json_response({"ok": False, "error": "no release"}, status=400)
    if store.release(release_id) is None:
        return web.json_response({"ok": False, "error": "no such release"}, status=404)

    audio = await request.read()
    samples = local.decode_wav(audio)
    if samples is None:
        return web.json_response({"ok": False, "error": "unreadable audio"}, status=400)

    hashes = local.remember(store.db, release_id, samples)
    return web.json_response({"ok": True, "hashes": hashes})


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
async def api_plays(request):
    status = request.query.get("status") or None
    rows = store.plays(status=status, limit=int(request.query.get("limit", 50)))

    out = []
    for row in rows:
        play = row_to_play(row)
        if row["status"] == "choose":
            # Worked out again rather than stored: you may have bought one of
            # the other pressings since, or a tracklist may have arrived that
            # was not there when this played. The question is about the shelf as
            # it is now, not as it was.
            play["choices"] = [row_to_release(r) for r in
                               store.releases_with_track(row["artist"], row["title"])]
        out.append(play)

    return web.json_response({"plays": out, "counts": store.counts()})


def _remember_clip(play_id: int, release_id: int) -> int:
    """Record a listen's saved clip as fingerprints against a release."""
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
    # A hand-made link is the most valuable lesson: exactly what the service
    # did not know.
    hashes = _remember_clip(play_id, release_id)
    return web.json_response({"ok": True, "hashes": hashes})


async def api_unlink(request):
    store.unlink_play(int(request.match_info["id"]))
    return web.json_response({"ok": True})


async def api_dismiss(request):
    store.dismiss_play(int(request.match_info["id"]))
    return web.json_response({"ok": True})


async def api_dismiss_many(request):
    """Discard a whole selection at once.

    Deliberately one request rather than forty from the browser: each discard
    also deletes a clip of about a megabyte and a half, and sending forty
    round trips through the proxy is noticeably slow on a phone.
    """
    body = await request.json()
    ids = [int(i) for i in body.get("ids", [])][:500]
    for play_id in ids:
        store.dismiss_play(play_id)
    return web.json_response({"ok": True, "count": len(ids),
                              "counts": store.counts()})


async def api_manual(request):
    """Enter a record by hand with your own artwork, for what Discogs lacks."""
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

    release_id = store.upsert_release(f"byhand-{uuid.uuid4().hex[:12]}",
                                      artist, title)
    if image:
        name = f"byhand-{release_id}.jpg"
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


async def api_tracks(request):
    """Fetch tracklists for records that have none yet.

    A second pass over the collection, separate from the sync because it is a
    request per release rather than one per fifty — several hundred of them the
    first time, at Discogs' rate limit. So it runs in batches: call it again
    and it carries on where it stopped, and the nightly timer picks up whatever
    was bought since.

    It earns its keep on compilations. A service names the track it heard and
    then names whichever release its metadata prefers, which for anything with
    a hit on it is a greatest-hits. Knowing what is on your own copies turns
    that guess into a lookup.
    """
    token = store.get("discogs_token")
    if not token:
        return web.json_response({"error": "no Discogs token set"}, status=400)

    # Bounded by the clock, not by a count the caller guesses at. The web
    # interface reaches this through the ears, which give a forwarded request
    # sixty seconds; ask for two hundred releases at a request each and the
    # proxy hangs up long before the work is done, and the answer — including
    # how far it got — is lost with it. So it stops early and says so, and you
    # call it again.
    deadline = time.monotonic() + float(request.query.get("seconds", 45))
    rows = store.releases_without_tracks(min(int(request.query.get("batch", 200)), 500))
    done, skipped, failed = 0, 0, []
    for row in rows:
        if time.monotonic() > deadline:
            break
        # Records you typed in yourself are not in Discogs at all — that is why
        # you typed them in. Nothing to fetch, and asking would spend a request
        # to be told so.
        if not (row["discogs_id"] or "").isdigit():
            store.set_tracks(row["id"], [""])
            skipped += 1
            continue
        try:
            titles = await discogs.fetch_tracklist(token, row["discogs_id"])
        except discogs.NotFound:
            # This one release is gone from Discogs; the rest are fine. Mark it
            # answered so the pass moves on instead of stopping here for ever.
            store.set_tracks(row["id"], [""])
            skipped += 1
            await asyncio.sleep(discogs.PAUSE)
            continue
        except discogs.DiscogsError as exc:
            # A bad token or a rate limit is about all of them, not this one.
            failed.append({"title": row["title"], "error": str(exc)})
            break
        # An empty tracklist is still an answer — a blank row keeps it out of
        # the queue next time, instead of being retried for ever.
        store.set_tracks(row["id"], titles or [""])
        done += 1
        await asyncio.sleep(discogs.PAUSE)

    with_tracks, total = store.track_counts()
    return web.json_response({"ok": True, "fetched": done, "skipped": skipped,
                              "failed": failed,
                              "withTracks": with_tracks, "total": total,
                              "remaining": max(0, total - with_tracks)})


async def api_collection(request):
    # The shelf browser needs the whole collection or the jump index is wrong:
    # with 40 of several hundred albums you never get past the B.
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

    # Store them locally right away, so linking works the same whether it came
    # from your own shelf or from all of Discogs.
    out = []
    for item in found:
        rid = store.upsert_release(**item)
        out.append(row_to_release(store.release(rid)))
    return web.json_response({"releases": out})


async def api_cover(request):
    """Serve a cover, caching it locally the first time."""
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
    """Artwork from an external service, through our own address and cached.

    Two reasons. First, a browser cannot read the colours of an image from
    another domain — the canvas becomes "tainted" — and we need those colours to
    keep the text legible. Second, the device has to be able to show a sleeve
    when the network is briefly gone.
    """
    url = request.query.get("url", "")
    if not url.startswith(("http://", "https://")):
        raise web.HTTPBadRequest(text="not a usable url")

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
# Settings
# ---------------------------------------------------------------------------
async def api_get_settings(_request):
    return web.json_response({
        "discogsUser": store.get("discogs_user"),
        "discogsTokenSet": bool(store.get("discogs_token")),
        "auddTokenSet": bool(store.get("audd_token")),
        "collectionCount": store.release_count(),
        "lookups": int(store.get("lookup_count", "0") or 0),
        "localHashes": local.count(store.db)[0],
        "localReleases": local.count(store.db)[1],
        "counts": store.counts(),
    })


async def api_set_settings(request):
    body = await request.json()
    if "discogsUser" in body:
        store.set("discogs_user", body["discogsUser"].strip())
    # An empty key field means "leave it", not "clear it" — otherwise the web
    # interface would wipe your token every time you changed something else.
    # Clearing is explicit: send null, which is what the remove button does.
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
# These live here rather than in the firmware so the panel fetches them at boot
# via /api/avr and you can change them without reflashing.
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
    """Test what is in the form, not what has been saved.

    Otherwise you would have to save before you could find out whether the
    address is right, which is exactly the wrong way round.
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

    # If the address works, save it now. Otherwise you would still have to
    # press save after a successful test, and you forget that exactly once.
    if result.get("ok"):
        store.set("avr_host", host)
        store.set("avr_port", port)
        result["saved"] = True
    return web.json_response(result)


# -- a connection that stays open, so the screen really drives it -----------
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
    """A raw command over the open connection, for instance MUON or SIPHONO."""
    command = request.query.get("cmd", "")
    if not command:
        return web.json_response({"ok": False, "error": "no command"}, status=400)
    if not avr.link.state["connected"]:
        return web.json_response({"ok": False, "error": "not connected"}, status=409)
    return web.json_response({"ok": await avr.link.send(command)})


async def api_avr_volume(request):
    body = await request.json()
    if not avr.link.state["connected"]:
        return web.json_response({"ok": False, "error": "not connected"}, status=409)
    ok = await avr.link.set_volume_db(float(body["db"]))
    return web.json_response({"ok": ok, "state": avr.link.state})


# ---------------------------------------------------------------------------
async def index(request):
    """The brain has no page of its own any more.

    The web interface became one page with tabs, and the ears (listen.py) serve
    it, because the line feed, the Apple TV and the proxy to the panel all live
    there. What is left here is the API, which that page reaches through /api/*
    on the same address.

    Anyone landing on port 8790 gets redirected. Run the brain on its own with
    no ears and that redirect goes nowhere — in which case this is simply an API
    server and not a website.
    """
    raise web.HTTPFound(f"http://{request.url.host}:8791/")


def main():
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_post("/api/listen", api_listen)
    app.router.add_post("/api/enrol", api_enrol)
    app.router.add_get("/api/plays", api_plays)
    app.router.add_post("/api/plays/{id}/link", api_link)
    app.router.add_post("/api/plays/{id}/unlink", api_unlink)
    # Before the {id} route, or that one catches "dismiss" as a number.
    app.router.add_post("/api/plays/dismiss", api_dismiss_many)
    app.router.add_post("/api/plays/{id}/dismiss", api_dismiss)
    app.router.add_post("/api/plays/{id}/manual", api_manual)
    app.router.add_post("/api/discogs/sync", api_sync)
    app.router.add_post("/api/discogs/tracks", api_tracks)
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

    print(f"\n  Brain API on port {PORT}. The web interface runs with the ears "
          "(listen.py) and reaches it here.")
    print(f"  Collectie: {store.release_count()} releases, "
          f"AudD key {'found' if store.get('audd_token') else 'not set'}.")
    print("  Ctrl-C stopt.\n")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()

