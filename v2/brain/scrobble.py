"""
Telling a listening service what the turntable played.

Vinyl is the hole in everyone's listening history. Streaming services log
themselves; a record leaves no trace, so a shelf you actually play is invisible
in your own statistics. Everything needed to close that is already here — artist,
track, album, the printed position and a timestamp, all of it in the plays table
the moment something is recognised. Nothing is left but to send it.

**ListenBrainz** rather than Last.fm, and the reason is friction. ListenBrainz
wants one token, copied from a settings page and pasted in — the same shape as
the Discogs token already in this project. Last.fm's scrobble API wants an API
key you register as a developer, a secret, a signature over every call, and a
browser handshake to turn all that into a session key. That is a lot of ceremony
for an appliance with a knob, and it is the reason this does one and not both.

Off unless a token is set, deliberately. This is the first thing here that
structurally leaves the house apart from the recognition lookups themselves, and
that deserves a conscious yes rather than a default.
"""

from __future__ import annotations

import time

from aiohttp import ClientSession, ClientTimeout

SUBMIT_URL = "https://api.listenbrainz.org/1/submit-listens"
VALIDATE_URL = "https://api.listenbrainz.org/1/validate-token"

# Short. A scrobble that does not arrive is not worth holding a recognition up
# for, and the next play will be along in a few minutes anyway.
TIMEOUT_S = 10

# Two listens of the same track inside this are one listen. The needle does not
# jump back to the same track a minute later, but a retried lookup does land on
# it twice, and a service is entitled to expect us not to send that twice.
SAME_TRACK_S = 240


async def validate(token: str) -> dict:
    """Is this token any good, and whose is it? Costs nothing and proves a lot."""
    if not token:
        return {"ok": False, "error": "no token"}
    try:
        async with ClientSession(timeout=ClientTimeout(total=TIMEOUT_S)) as s:
            async with s.get(VALIDATE_URL,
                             headers={"Authorization": f"Token {token}"}) as r:
                body = await r.json(content_type=None)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if body.get("valid"):
        return {"ok": True, "user": body.get("user_name") or ""}
    return {"ok": False, "error": body.get("message") or "not accepted"}


def payload(artist: str, track: str, album: str = "", printed: str = "",
            discogs_id: str = "", at: int | None = None) -> dict:
    """One listen, in the shape the service asks for.

    Kept apart from the sending so it can be looked at without a token and
    without anything leaving the house — which is the only way to be sure about
    what would.
    """
    info = {"media_player": "VinylKnob", "submission_client": "VinylKnob"}
    if printed:
        # Not part of the standard vocabulary, but it is the one thing a record
        # knows that a stream does not, and it costs nothing to carry.
        info["tracknumber"] = printed
    if discogs_id and discogs_id.isdigit():
        info["discogs_id"] = int(discogs_id)

    metadata: dict = {"artist_name": artist, "track_name": track,
                      "additional_info": info}
    if album:
        metadata["release_name"] = album
    return {
        "listen_type": "single",
        "payload": [{"listened_at": int(at if at is not None else time.time()),
                     "track_metadata": metadata}],
    }


async def send(token: str, body: dict) -> dict:
    """Hand one listen over. Never raises: a failed scrobble is not an error
    worth breaking a recognition for."""
    if not token:
        return {"ok": False, "error": "no token"}
    try:
        async with ClientSession(timeout=ClientTimeout(total=TIMEOUT_S)) as s:
            async with s.post(SUBMIT_URL, json=body,
                              headers={"Authorization": f"Token {token}"}) as r:
                if r.status == 200:
                    return {"ok": True}
                text = (await r.text())[:200]
                return {"ok": False, "error": f"{r.status}: {text}"}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
