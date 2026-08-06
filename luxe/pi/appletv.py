"""
Wat er op de Apple TV speelt, rechtstreeks van het apparaat.

De microfoon is voor platen. Voor alles wat over HDMI binnenkomt is meeluisteren
onzin: de Apple TV wéét wat hij afspeelt, inclusief de hoes, en pyatv vraagt het
gewoon. Geen herkenning, geen ruisvloer, geen Shazam.

Koppelen gaat via de webinterface en niet via de opdrachtregel: er verschijnt een
pincode op de tv en die tik je in op je telefoon. De sleutels komen in
data/appletv.json en overleven een herstart.

Let op: een app mag zijn gegevens afschermen. Netflix doet dat; Apple TV+, Music
en de meeste andere niet. Daar valt van deze kant niets aan te doen.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import time

import pyatv
from pyatv.const import Protocol

HERE = pathlib.Path(__file__).parent
CREDENTIALS = HERE.parent / "brein" / "data" / "appletv.json"

# Hoe vaak we controleren of de verbinding nog echt leeft.
#
# Dit is er niet voor niets. Een Apple TV die gaat slapen verbreekt de
# verbinding, en dat gebeurde zonder dat er iets van te merken was: er kwamen
# geen duwtjes meer binnen, `self.apparaat` bleef gevuld, en het paneel toonde
# een nacht lang de titel van de laatste video van de vorige avond. Een
# afwezige melding is geen bewijs dat het goed gaat, dus vragen we het gewoon.
WATCH_S = 60.0

# Zonder deze twee valt er niets te lezen: Companion levert de bediening,
# AirPlay het "nu aan het spelen" met de hoes.
REQUIRED = (Protocol.AirPlay, Protocol.Companion)


def _load() -> dict:
    try:
        return json.loads(CREDENTIALS.read_text())
    except Exception:                                       # noqa: BLE001
        return {}


def _save(data: dict) -> None:
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS.write_text(json.dumps(data, indent=2))


class AppleTV:
    def __init__(self) -> None:
        self.device = None            # verbonden pyatv-interface
        self.pairing = None      # lopende koppelsessie
        self.pairing_name = ""
        self.artist = ""
        self.title = ""
        self.album = ""
        self.playing_now = False
        self.artwork: bytes = b""
        self.app = ""
        self.app_id = ""
        self.error = ""
        self.last_update = 0.0       # wanneer er voor het laatst iets binnenkwam

    # -- ontdekken en koppelen --------------------------------------------
    async def scan(self) -> list[dict]:
        found = await pyatv.scan(asyncio.get_event_loop(), timeout=5)
        out = []
        for a in found:
            # Alleen apparaten die kunnen vertellen wat ze spelen. Een HomePod
            # in de lijst zetten die dat niet levert is alleen verwarrend.
            protocols = {s.protocol for s in a.services}
            if Protocol.AirPlay not in protocols:
                continue
            out.append({
                "id": str(a.identifier),
                "naam": a.name,
                "model": str(a.device_info),
                "adres": str(a.address),
            })
        return out

    async def pair_start(self, identifier: str) -> dict:
        await self.pair_stop()
        found = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                    identifier=identifier)
        if not found:
            return {"ok": False, "fout": "apparaat niet gevonden"}

        self.pairing_name = found[0].name
        self._conf = found[0]
        self._remaining = [p for p in REQUIRED
                           if p in {s.protocol for s in found[0].services}]
        return await self._next_protocol()

    async def _next_protocol(self) -> dict:
        """Elk protocol wil zijn eigen pincode; hier gaan we ze langs."""
        if not self._remaining:
            _save({"id": str(self._conf.identifier), "naam": self.pairing_name,
                     **self._collected})
            await self.connect()
            return {"ok": True, "klaar": True, "naam": self.pairing_name}

        protocol = self._remaining[0]
        self.pairing = await pyatv.pair(self._conf, protocol,
                                               asyncio.get_event_loop())
        await self.pairing.begin()
        return {"ok": True, "klaar": False, "protocol": protocol.name,
                "naam": self.pairing_name,
                "resterend": len(self._remaining)}

    async def pair_pin(self, pin: str) -> dict:
        if not self.pairing:
            return {"ok": False, "fout": "geen koppeling bezig"}
        self.pairing.pin(pin)
        try:
            await self.pairing.finish()
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "fout": f"{type(e).__name__}: {e}"}

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

    # -- verbinding en wat er speelt --------------------------------------
    async def connect(self) -> bool:
        g = self.paired()
        if not g:
            return False
        await self.disconnect()
        try:
            found = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                        identifier=g["id"])
            if not found:
                self.error = "apparaat staat niet op het netwerk"
                return False
            conf = found[0]
            for name, key in g.items():
                if name in ("id", "naam"):
                    continue
                conf.set_credentials(Protocol[name], key)
            self.device = await pyatv.connect(conf, asyncio.get_event_loop())
            # Twee luisteraars, en de tweede is geen luxe: de push-updater meldt
            # alleen wát er speelt, de apparaatluisteraar meldt dát de
            # verbinding weg is. Zonder die tweede blijft een verbroken
            # verbinding onzichtbaar en bevriest het scherm op de laatste titel.
            self.device.listener = self
            self.device.push_updater.listener = self
            self.device.push_updater.start()
            self.error = ""
            # Meteen ophalen wat er nu speelt, in plaats van wachten tot er
            # toevallig iets verandert.
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

    # -- pyatv duwt wijzigingen hierheen ----------------------------------
    def _take_over(self, status) -> None:
        """Eén plek waar de velden gevuld worden, voor duwtjes én controles."""
        # De app is bruikbaar als er verder niets is: bij YouTube blijft het
        # bij titel en kanaal, want er komt geen video-identificatie mee waarmee
        # je een thumbnail zou kunnen opzoeken.
        try:
            app = getattr(self.device.metadata, "app", None)
            self.app_id = (getattr(app, "identifier", None) or "") if app else ""
            # .name geeft "YouTube"; str() zou "App: YouTube (com.google...)"
            # opleveren en dat wil je niet op een scherm van 480 pixels.
            self.app = (getattr(app, "name", None) or "") if app else ""
        except Exception:                                   # noqa: BLE001
            self.app = ""

        fresh = (status.artist or "", status.title or "", status.album or "")
        veranderd = fresh != (self.artist, self.title, self.album)
        self.artist, self.title, self.album = fresh
        self.playing_now = status.device_state is not None and str(
            status.device_state).lower().endswith("playing")
        self.last_update = time.monotonic()
        # De hoes alleen opnieuw ophalen als er werkelijk iets anders speelt;
        # de bewaking komt elke minuut langs en dat is geen reden om elke
        # minuut een afbeelding op te vragen.
        if veranderd:
            asyncio.create_task(self._fetch_artwork())

    def playstatus_update(self, _updater, status) -> None:
        self._take_over(status)

    def playstatus_error(self, _updater, exception) -> None:
        self.error = f"{type(exception).__name__}: {exception}"

    # -- de verbinding zelf ------------------------------------------------
    # pyatv meldt hierlangs dat het apparaat weg is. Voorheen luisterde niemand.
    def connection_lost(self, exception) -> None:
        self.error = f"verbinding weggevallen: {type(exception).__name__}: {exception}"
        self.device = None
        print(f"[appletv] {self.error}", flush=True)

    def connection_closed(self) -> None:
        self.error = "verbinding gesloten door het apparaat"
        self.device = None
        print(f"[appletv] {self.error}", flush=True)

    async def watch(self) -> None:
        """Blijven controleren, en opnieuw verbinden als het nodig is.

        Naast de meldingen hierboven, niet in plaats daarvan: die vangen een
        nette afsluiting, dit vangt ook het geval waarin de verbinding technisch
        overeind staat maar er niets meer doorheen komt. Dat laatste is precies
        wat er gebeurde, en het bleef een nacht lang onopgemerkt.
        """
        while True:
            await asyncio.sleep(WATCH_S)
            # Alles afgevangen: een bewaker die zelf stilletjes kan omvallen is
            # erger dan geen bewaker, want dan lijkt het nog steeds goed te gaan.
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:                          # noqa: BLE001
                print(f"[appletv] bewaking struikelde: {type(e).__name__}: {e}",
                      flush=True)

    async def check_once(self) -> None:
        """Eén ronde van de bewaking. Apart, zodat hij te testen is."""
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
            print(f"[appletv] reageert niet ({type(e).__name__}), "
                  "opnieuw verbinden", flush=True)
            await self.connect()

    async def _fetch_artwork(self) -> None:
        if not self.device:
            return
        try:
            kunst = await self.device.metadata.artwork(width=480, height=480)
            self.artwork = kunst.bytes if kunst else b""
            if not self.artwork:
                print("[appletv] geen afbeelding bij deze titel", flush=True)
        except Exception as e:                              # noqa: BLE001
            self.artwork = b""
            print(f"[appletv] hoes ophalen mislukt: {type(e).__name__}: {e}",
                  flush=True)
