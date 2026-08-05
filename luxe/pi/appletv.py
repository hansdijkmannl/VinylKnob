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

HIER = pathlib.Path(__file__).parent
SLEUTELS = HIER.parent / "brein" / "data" / "appletv.json"

# Hoe vaak we controleren of de verbinding nog echt leeft.
#
# Dit is er niet voor niets. Een Apple TV die gaat slapen verbreekt de
# verbinding, en dat gebeurde zonder dat er iets van te merken was: er kwamen
# geen duwtjes meer binnen, `self.apparaat` bleef gevuld, en het paneel toonde
# een nacht lang de titel van de laatste video van de vorige avond. Een
# afwezige melding is geen bewijs dat het goed gaat, dus vragen we het gewoon.
BEWAAK_S = 60.0

# Zonder deze twee valt er niets te lezen: Companion levert de bediening,
# AirPlay het "nu aan het spelen" met de hoes.
NODIG = (Protocol.AirPlay, Protocol.Companion)


def _laad() -> dict:
    try:
        return json.loads(SLEUTELS.read_text())
    except Exception:                                       # noqa: BLE001
        return {}


def _bewaar(gegevens: dict) -> None:
    SLEUTELS.parent.mkdir(parents=True, exist_ok=True)
    SLEUTELS.write_text(json.dumps(gegevens, indent=2))


class AppleTV:
    def __init__(self) -> None:
        self.apparaat = None            # verbonden pyatv-interface
        self.bezig_koppelen = None      # lopende koppelsessie
        self.koppel_naam = ""
        self.artiest = ""
        self.titel = ""
        self.album = ""
        self.speelt = False
        self.hoes: bytes = b""
        self.app = ""
        self.app_id = ""
        self.fout = ""
        self.laatste_update = 0.0       # wanneer er voor het laatst iets binnenkwam

    # -- ontdekken en koppelen --------------------------------------------
    async def scan(self) -> list[dict]:
        gevonden = await pyatv.scan(asyncio.get_event_loop(), timeout=5)
        uit = []
        for a in gevonden:
            # Alleen apparaten die kunnen vertellen wat ze spelen. Een HomePod
            # in de lijst zetten die dat niet levert is alleen verwarrend.
            protocollen = {s.protocol for s in a.services}
            if Protocol.AirPlay not in protocollen:
                continue
            uit.append({
                "id": str(a.identifier),
                "naam": a.name,
                "model": str(a.device_info),
                "adres": str(a.address),
            })
        return uit

    async def koppel_start(self, identifier: str) -> dict:
        await self.koppel_stop()
        gevonden = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                    identifier=identifier)
        if not gevonden:
            return {"ok": False, "fout": "apparaat niet gevonden"}

        self.koppel_naam = gevonden[0].name
        self._conf = gevonden[0]
        self._resterend = [p for p in NODIG
                           if p in {s.protocol for s in gevonden[0].services}]
        return await self._volgende_protocol()

    async def _volgende_protocol(self) -> dict:
        """Elk protocol wil zijn eigen pincode; hier gaan we ze langs."""
        if not self._resterend:
            _bewaar({"id": str(self._conf.identifier), "naam": self.koppel_naam,
                     **self._verzameld})
            await self.verbind()
            return {"ok": True, "klaar": True, "naam": self.koppel_naam}

        protocol = self._resterend[0]
        self.bezig_koppelen = await pyatv.pair(self._conf, protocol,
                                               asyncio.get_event_loop())
        await self.bezig_koppelen.begin()
        return {"ok": True, "klaar": False, "protocol": protocol.name,
                "naam": self.koppel_naam,
                "resterend": len(self._resterend)}

    async def koppel_pin(self, pin: str) -> dict:
        if not self.bezig_koppelen:
            return {"ok": False, "fout": "geen koppeling bezig"}
        self.bezig_koppelen.pin(pin)
        try:
            await self.bezig_koppelen.finish()
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "fout": f"{type(e).__name__}: {e}"}

        protocol = self._resterend.pop(0)
        if not hasattr(self, "_verzameld"):
            self._verzameld = {}
        self._verzameld[protocol.name] = self.bezig_koppelen.service.credentials
        await self.bezig_koppelen.close()
        self.bezig_koppelen = None
        return await self._volgende_protocol()

    async def koppel_stop(self) -> None:
        if self.bezig_koppelen:
            try:
                await self.bezig_koppelen.close()
            except Exception:                               # noqa: BLE001
                pass
            self.bezig_koppelen = None
        self._verzameld = {}

    def gekoppeld(self) -> dict | None:
        g = _laad()
        return g if g.get("id") else None

    async def vergeet(self) -> None:
        await self.ontkoppel()
        SLEUTELS.unlink(missing_ok=True)

    # -- verbinding en wat er speelt --------------------------------------
    async def verbind(self) -> bool:
        g = self.gekoppeld()
        if not g:
            return False
        await self.ontkoppel()
        try:
            gevonden = await pyatv.scan(asyncio.get_event_loop(), timeout=5,
                                        identifier=g["id"])
            if not gevonden:
                self.fout = "apparaat staat niet op het netwerk"
                return False
            conf = gevonden[0]
            for naam, sleutel in g.items():
                if naam in ("id", "naam"):
                    continue
                conf.set_credentials(Protocol[naam], sleutel)
            self.apparaat = await pyatv.connect(conf, asyncio.get_event_loop())
            # Twee luisteraars, en de tweede is geen luxe: de push-updater meldt
            # alleen wát er speelt, de apparaatluisteraar meldt dát de
            # verbinding weg is. Zonder die tweede blijft een verbroken
            # verbinding onzichtbaar en bevriest het scherm op de laatste titel.
            self.apparaat.listener = self
            self.apparaat.push_updater.listener = self
            self.apparaat.push_updater.start()
            self.fout = ""
            # Meteen ophalen wat er nu speelt, in plaats van wachten tot er
            # toevallig iets verandert.
            try:
                self._neem_over(await self.apparaat.metadata.playing())
            except Exception:                               # noqa: BLE001
                pass
            return True
        except Exception as e:                              # noqa: BLE001
            self.fout = f"{type(e).__name__}: {e}"
            return False

    async def ontkoppel(self) -> None:
        if self.apparaat:
            try:
                self.apparaat.close()
            except Exception:                               # noqa: BLE001
                pass
            self.apparaat = None
        self.artiest = self.titel = self.album = ""
        self.speelt = False
        self.hoes = b""

    # -- pyatv duwt wijzigingen hierheen ----------------------------------
    def _neem_over(self, status) -> None:
        """Eén plek waar de velden gevuld worden, voor duwtjes én controles."""
        # De app is bruikbaar als er verder niets is: bij YouTube blijft het
        # bij titel en kanaal, want er komt geen video-identificatie mee waarmee
        # je een thumbnail zou kunnen opzoeken.
        try:
            app = getattr(self.apparaat.metadata, "app", None)
            self.app_id = (getattr(app, "identifier", None) or "") if app else ""
            # .name geeft "YouTube"; str() zou "App: YouTube (com.google...)"
            # opleveren en dat wil je niet op een scherm van 480 pixels.
            self.app = (getattr(app, "name", None) or "") if app else ""
        except Exception:                                   # noqa: BLE001
            self.app = ""

        nieuw = (status.artist or "", status.title or "", status.album or "")
        veranderd = nieuw != (self.artiest, self.titel, self.album)
        self.artiest, self.titel, self.album = nieuw
        self.speelt = status.device_state is not None and str(
            status.device_state).lower().endswith("playing")
        self.laatste_update = time.monotonic()
        # De hoes alleen opnieuw ophalen als er werkelijk iets anders speelt;
        # de bewaking komt elke minuut langs en dat is geen reden om elke
        # minuut een afbeelding op te vragen.
        if veranderd:
            asyncio.create_task(self._haal_hoes())

    def playstatus_update(self, _updater, status) -> None:
        self._neem_over(status)

    def playstatus_error(self, _updater, exception) -> None:
        self.fout = f"{type(exception).__name__}: {exception}"

    # -- de verbinding zelf ------------------------------------------------
    # pyatv meldt hierlangs dat het apparaat weg is. Voorheen luisterde niemand.
    def connection_lost(self, exception) -> None:
        self.fout = f"verbinding weggevallen: {type(exception).__name__}: {exception}"
        self.apparaat = None
        print(f"[appletv] {self.fout}", flush=True)

    def connection_closed(self) -> None:
        self.fout = "verbinding gesloten door het apparaat"
        self.apparaat = None
        print(f"[appletv] {self.fout}", flush=True)

    async def bewaak(self) -> None:
        """Blijven controleren, en opnieuw verbinden als het nodig is.

        Naast de meldingen hierboven, niet in plaats daarvan: die vangen een
        nette afsluiting, dit vangt ook het geval waarin de verbinding technisch
        overeind staat maar er niets meer doorheen komt. Dat laatste is precies
        wat er gebeurde, en het bleef een nacht lang onopgemerkt.
        """
        while True:
            await asyncio.sleep(BEWAAK_S)
            # Alles afgevangen: een bewaker die zelf stilletjes kan omvallen is
            # erger dan geen bewaker, want dan lijkt het nog steeds goed te gaan.
            try:
                await self.controleer()
            except asyncio.CancelledError:
                raise
            except Exception as e:                          # noqa: BLE001
                print(f"[appletv] bewaking struikelde: {type(e).__name__}: {e}",
                      flush=True)

    async def controleer(self) -> None:
        """Eén ronde van de bewaking. Apart, zodat hij te testen is."""
        if not self.gekoppeld():
            return
        if self.apparaat is None:
            await self.verbind()
            return
        try:
            status = await asyncio.wait_for(
                self.apparaat.metadata.playing(), timeout=10)
            self._neem_over(status)
        except Exception as e:                              # noqa: BLE001
            print(f"[appletv] reageert niet ({type(e).__name__}), "
                  "opnieuw verbinden", flush=True)
            await self.verbind()

    async def _haal_hoes(self) -> None:
        if not self.apparaat:
            return
        try:
            kunst = await self.apparaat.metadata.artwork(width=480, height=480)
            self.hoes = kunst.bytes if kunst else b""
            if not self.hoes:
                print("[appletv] geen afbeelding bij deze titel", flush=True)
        except Exception as e:                              # noqa: BLE001
            self.hoes = b""
            print(f"[appletv] hoes ophalen mislukt: {type(e).__name__}: {e}",
                  flush=True)
