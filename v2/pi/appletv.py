"""
What is playing on the Apple TV, straight from the device.

The microphone is for records. For anything arriving over HDMI, listening in is
nonsense: the Apple TV *knows* what it is playing, artwork included, and pyatv
simply asks. No recognition, no noise floor, no Shazam.

Pairing happens through the web interface rather than the command line: a PIN
appears on the television and you type it on your phone. The credentials land in
data/appletv.json and survive a restart.

Note: an app may withhold its metadata. Netflix does; Apple TV+, Music and most
others do not. There is nothing to be done about that from this side.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import time

import pyatv
from pyatv.const import Protocol

HERE = pathlib.Path(__file__).parent
CREDENTIALS = HERE.parent / "brain" / "data" / "appletv.json"

# How often we check that the connection is genuinely alive.
#
# This is not idle. An Apple TV going to sleep drops the connection, and that
# happened with nothing to show for it: no more push updates arrived,
# `self.device` stayed populated, and the panel showed the title of the previous
# evening's last video all night. An absent error is no proof that things are
# fine, so we simply ask.
WATCH_S = 60.0

# Without these two there is nothing to read: Companion provides control,
# AirPlay the "now playing" with its artwork.
REQUIRED = (Protocol.AirPlay, Protocol.Companion)


def _load() -> dict:
    try:
        stored = json.loads(CREDENTIALS.read_text())
    except Exception:                                       # noqa: BLE001
        return {}
    # The device name used to be stored under "naam". Read it either way, so a
    # pairing made before the rename keeps working; it is written back as
    # "name" on the next save.
    if "naam" in stored:
        stored["name"] = stored.pop("naam")
    return stored


def _save(data: dict) -> None:
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS.write_text(json.dumps(data, indent=2))


class AppleTV:
    def __init__(self) -> None:
        self.device = None            # the connected pyatv interface
        self.pairing = None           # pairing session in progress
        self.pairing_name = ""
        self.artist = ""
        self.title = ""
        self.album = ""
        self.playing_now = False
        self.artwork: bytes = b""
        self.app = ""
        self.app_id = ""
        self.error = ""
        self.last_update = 0.0       # when something last came in

    # -- discovery and pairing ---------------------------------------------
    async def scan(self) -> list[dict]:
        found = await pyatv.scan(asyncio.get_event_loop(), timeout=5)
        out = []
        for a in found:
            # Only devices that can say what they are playing. Listing a
            # HomePod that cannot is merely confusing.
            protocols = {s.protocol for s in a.services}
            if Protocol.AirPlay not in protocols:
                continue
            out.append({
                "id": str(a.identifier),
                "name": a.name,
                "model": str(a.device_info),
                "address": str(a.address),
            })
        return out

    async def pair_start(self, identifier: str) -> dict:
        await self.pair_stop()
        found = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                    identifier=identifier)
        if not found:
            return {"ok": False, "error": "device not found"}

        self.pairing_name = found[0].name
        self._conf = found[0]
        self._remaining = [p for p in REQUIRED
                           if p in {s.protocol for s in found[0].services}]
        return await self._next_protocol()

    async def _next_protocol(self) -> dict:
        """Each protocol wants its own PIN; this walks through them."""
        if not self._remaining:
            _save({"id": str(self._conf.identifier), "name": self.pairing_name,
                     **self._collected})
            await self.connect()
            return {"ok": True, "done": True, "name": self.pairing_name}

        protocol = self._remaining[0]
        self.pairing = await pyatv.pair(self._conf, protocol,
                                               asyncio.get_event_loop())
        await self.pairing.begin()
        return {"ok": True, "done": False, "protocol": protocol.name,
                "name": self.pairing_name,
                "remaining": len(self._remaining)}

    async def pair_pin(self, pin: str) -> dict:
        if not self.pairing:
            return {"ok": False, "error": "no pairing in progress"}
        self.pairing.pin(pin)
        try:
            await self.pairing.finish()
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        protocol = self._remaining.pop(0)
        if not hasattr(self, "_collected"):
            self._collected = {}
        self._collected[protocol.name] = self.pairing.service.credentials
        await self.pairing.close()
        self.pairing = None
        return await self._next_protocol()

    async def pair_stop(self) -> None:
        if self.pairing:
            try:
                await self.pairing.close()
            except Exception:                               # noqa: BLE001
                pass
            self.pairing = None
        self._collected = {}

    def paired(self) -> dict | None:
        g = _load()
        return g if g.get("id") else None

    async def forget(self) -> None:
        await self.disconnect()
        CREDENTIALS.unlink(missing_ok=True)

    # -- the connection, and what is playing -------------------------------
    async def connect(self) -> bool:
        g = self.paired()
        if not g:
            return False
        await self.disconnect()
        try:
            found = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                        identifier=g["id"])
            if not found:
                self.error = "device is not on the network"
                return False
            conf = found[0]
            for name, key in g.items():
                if name in ("id", "name"):
                    continue
                conf.set_credentials(Protocol[name], key)
            self.device = await pyatv.connect(conf, asyncio.get_event_loop())
            # Two listeners, and the second is not a luxury: the push updater
            # reports only *what* is playing, the device listener reports *that*
            # the connection is gone. Without the second, a dropped connection
            # stays invisible and the screen freezes on the last title.
            self.device.listener = self
            self.device.push_updater.listener = self
            self.device.push_updater.start()
            self.error = ""
            # Fetch what is playing right away, rather than waiting for
            # something to happen to change.
            try:
                self._take_over(await self.device.metadata.playing())
            except Exception:                               # noqa: BLE001
                pass
            return True
        except Exception as e:                              # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            return False

    async def disconnect(self) -> None:
        if self.device:
            try:
                self.device.close()
            except Exception:                               # noqa: BLE001
                pass
            self.device = None
        self.artist = self.title = self.album = ""
        self.playing_now = False
        self.artwork = b""

    # -- pyatv pushes changes to here --------------------------------------
    def _take_over(self, status) -> None:
        """One place where the fields get filled, for pushes and checks alike."""
        # The app name is useful when there is nothing else: with YouTube you
        # get title and channel and no more, because no video identifier comes
        # along that you could look a thumbnail up with.
        try:
            app = getattr(self.device.metadata, "app", None)
            self.app_id = (getattr(app, "identifier", None) or "") if app else ""
            # .name gives "YouTube"; str() would give "App: YouTube
            # (com.google...)", and you do not want that on a 480-pixel screen.
            self.app = (getattr(app, "name", None) or "") if app else ""
        except Exception:                                   # noqa: BLE001
            self.app = ""

        fresh = (status.artist or "", status.title or "", status.album or "")
        veranderd = fresh != (self.artist, self.title, self.album)
        self.artist, self.title, self.album = fresh
        self.playing_now = status.device_state is not None and str(
            status.device_state).lower().endswith("playing")
        self.last_update = time.monotonic()
        # Only re-fetch the artwork when something genuinely different is
        # playing; the watchdog comes past every minute and that is no reason to
        # request an image every minute.
        if veranderd:
            asyncio.create_task(self._fetch_artwork())

    def playstatus_update(self, _updater, status) -> None:
        self._take_over(status)

    def playstatus_error(self, _updater, exception) -> None:
        self.error = f"{type(exception).__name__}: {exception}"

    # -- the connection itself ---------------------------------------------
    # pyatv reports a lost device through here. Previously nobody listened.
    def connection_lost(self, exception) -> None:
        self.error = f"connection dropped: {type(exception).__name__}: {exception}"
        self.device = None
        print(f"[appletv] {self.error}", flush=True)

    def connection_closed(self) -> None:
        self.error = "connection closed by the device"
        self.device = None
        print(f"[appletv] {self.error}", flush=True)

    async def watch(self) -> None:
        """Keep checking, and reconnect when needed.

        Alongside the callbacks above, not instead of them: those catch a clean
        shutdown, this also catches the case where the connection is technically
        up but nothing comes through any more. That last one is exactly what
        happened, and it went unnoticed for a night.
        """
        while True:
            await asyncio.sleep(WATCH_S)
            # Everything caught: a watchdog that can quietly fall over itself
            # is worse than none, because it still looks like things are fine.
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:                          # noqa: BLE001
                print(f"[appletv] bewaking struikelde: {type(e).__name__}: {e}",
                      flush=True)

    async def check_once(self) -> None:
        """One round of the watchdog. Separate, so that it can be tested."""
        if not self.paired():
            return
        if self.device is None:
            await self.connect()
            return
        try:
            status = await asyncio.wait_for(
                self.device.metadata.playing(), timeout=10)
            self._take_over(status)
        except Exception as e:                              # noqa: BLE001
            print(f"[appletv] not responding ({type(e).__name__}), "
                  "reconnecting", flush=True)
            await self.connect()

    async def _fetch_artwork(self) -> None:
        if not self.device:
            return
        try:
            kunst = await self.device.metadata.artwork(width=480, height=480)
            self.artwork = kunst.bytes if kunst else b""
            if not self.artwork:
                print("[appletv] no image for this title", flush=True)
        except Exception as e:                              # noqa: BLE001
            self.artwork = b""
            print(f"[appletv] fetching the artwork failed: {type(e).__name__}: {e}",
                  flush=True)
