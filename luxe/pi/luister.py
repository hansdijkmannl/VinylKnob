#!/usr/bin/env python3
"""
De oren van het apparaat: luistert mee met de USB-dasspeldmicrofoon en vraagt
het brein om een opzoeking zodra er iets begint te spelen.

Waarom niet op een timer — dat staat in ../PLAN.md, fase 0b. shazamio is een
onofficiele client zonder sleutel: een handvol opzoekingen per avond valt niet
op, elke minuut eentje wel. En het is ook gewoon zinloos: een plaatkant duurt
twintig minuten en verandert in die tijd niet van naam.

Dus wordt er geluisterd op een gebeurtenis: **geluid na stilte**. Dat is precies
het moment waarop je de naald neerzet, en het werkt zonder dat deze dienst iets
van de versterker hoeft te weten — belangrijk, want de SR7015 laat maar één
telnet-sessie toe en die is van het CrowPanel.

De drempel is niet vast maar volgt de kamer: we houden de stilste tien procent
van de afgelopen minuut aan als ruisvloer en slaan aan bij een flinke sprong
daarboven. Zo werkt hetzelfde getal in een stille kamer en naast een open raam.

Deze dienst serveert ook de webinterface: één pagina met tabbladen, in
static/index.html. Hij staat hier en niet bij het brein omdat de microfoon, de
Apple TV en de doorgeefpoort naar het paneel hier zitten; het brein levert
alleen nog zijn API, die onder /api/ wordt doorgegeven.

Draait als systemd-dienst, zie marantzknob-luister.service.
"""

from __future__ import annotations

import asyncio
import io
import os
import pathlib
import time
import wave

import numpy as np
import appicoon
from appletv import AppleTV
from aiohttp import ClientSession, ClientTimeout, web

# De hoes wordt hier verkleind en niet op het paneel: een ESP32 die een JPEG van
# 600 pixels moet schalen kost geheugen en tijd die hij niet heeft, terwijl de Pi
# het in tientallen milliseconden doet.
HOES_PX = int(os.environ.get("COVER_PX", "480"))

# -- instellingen, allemaal te overschrijven met omgevingsvariabelen ---------
BREIN        = os.environ.get("BREIN_URL", "http://127.0.0.1:8790")
APPARAAT     = os.environ.get("MIC_DEVICE", "plughw:1,0")
TEMPO        = int(os.environ.get("MIC_RATE", "44100"))
POORT        = int(os.environ.get("LUISTER_PORT", "8791"))

BLOK_S       = 0.1                     # zo vaak meten we het niveau
FRAGMENT_S   = float(os.environ.get("CLIP_SECONDS", "8"))
AANLOOP_S    = float(os.environ.get("SETTLE_SECONDS", "4"))    # naald laten zakken
START_S      = float(os.environ.get("START_SECONDS", "2.5"))   # zo lang geluid = het speelt
STILTE_S     = float(os.environ.get("QUIET_SECONDS", "15"))    # zo lang stil = kant is klaar
HERKANS_S    = float(os.environ.get("RETRY_SECONDS", "60"))    # na een mislukte opzoeking

# Hoe vaak achter elkaar we het opnieuw proberen als er niets herkend wordt.
#
# Zonder grens loopt dit door zolang er geluid is, en dat is precies wat er
# gebeurde: een pratende video op de Apple TV leverde vijfenveertig opzoekingen
# op één ochtend, elke vijfenzeventig seconden eentje, allemaal leeg. Voor een
# plaat helpt herkansen wel — de eerste hap kan een zachte intro zijn — maar
# lukt het drie keer niet, dan ligt er geen plaat en gaan pogingen vier tot
# vijfentwintig daar niets aan veranderen. Wachten op echte stilte is dan de
# juiste zet: dat is het teken dat er iets nieuws kan beginnen.
MAX_HERKANSEN = int(os.environ.get("MAX_RETRIES", "3"))

# Hoe lang de hoes blijft staan nadat het stil werd. Bewust veel langer dan
# QUIET_SECONDS: dat getal bepaalt wanneer er weer geluisterd mag worden, en dat
# wil je kort. Maar het beeld leegmaken is iets anders — bij een marginaal
# signaal zakt een zachte passage al onder de drempel, en dan verdwijnt de hoes
# terwijl de plaat gewoon doorspeelt. Vijf minuten stilte is pas echt afgelopen.
BEELD_HOUD_S = float(os.environ.get("COVER_HOLD_SECONDS", "300"))
SPRONG_DB    = float(os.environ.get("TRIGGER_DB", "12"))       # boven de ruisvloer
# De ruisvloer volgt snel naar beneden en heel langzaam omhoog. Dat is niet
# hetzelfde als het tiende percentiel over de laatste minuut, en het verschil
# doet ertoe: speelt er een minuut aaneengesloten muziek, dan wórdt die muziek
# het tiende percentiel en zakt de gemeten marge naar nul. Precies de reden dat
# een plaat die prima te horen is toch onder de drempel bleef.
VLOER_STIJG_DB = 0.02          # per blok van 0,1 s, dus ~0,2 dB per seconde
VLOER_STIL_DB  = 6.0           # zo dicht bij de vloer telt als "kamer"

BYTES_PER_BLOK = int(TEMPO * BLOK_S) * 2       # 16 bits mono


# Vanaf hier zet de Pi zijn ventilator op de hoogste stand; knijpen begint pas
# bij 80. Onder deze grens is warm gewoon warm en hoeft het scherm er niets over
# te zeggen — een permanente temperatuurmeter op een scherm voor albumhoezen is
# rommel, een waarschuwing als het ertoe doet niet.
HEET_C = float(os.environ.get("WARN_TEMP_C", "75"))


def pi_warmte() -> dict:
    """Temperatuur, ventilator en of er geknepen wordt."""
    uit = {"tempC": None, "fanRpm": None, "geknepen": False, "heet": False}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            uit["tempC"] = round(int(f.read()) / 1000, 1)
    except Exception:                                       # noqa: BLE001
        pass
    for pad in ("/sys/class/hwmon/hwmon0/fan1_input",
                "/sys/class/hwmon/hwmon1/fan1_input",
                "/sys/class/hwmon/hwmon2/fan1_input"):
        try:
            with open(pad) as f:
                uit["fanRpm"] = int(f.read())
                break
        except Exception:                                   # noqa: BLE001
            continue
    try:
        with open("/sys/devices/platform/soc/soc:firmware/get_throttled") as f:
            uit["geknepen"] = int(f.read().strip(), 16) != 0
    except Exception:                                       # noqa: BLE001
        pass
    uit["heet"] = bool(uit["geknepen"] or (uit["tempC"] or 0) >= HEET_C)
    return uit


def db(rms: float) -> float:
    return 20.0 * np.log10(max(rms, 1e-9))


def naar_wav(pcm: bytes) -> bytes:
    """Het brein wil een gewone 16-bits WAV; arecord levert kale PCM."""
    uit = io.BytesIO()
    with wave.open(uit, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TEMPO)
        w.writeframes(pcm)
    return uit.getvalue()


class Oren:
    def __init__(self) -> None:
        self.vloer_db = -99.0                 # volgt de stilte, niet de muziek
        self.luid_sinds: float | None = None
        self.stil_sinds: float | None = 0.0
        self.bezig = False                    # er speelt iets, niet opnieuw vragen
        self.luistert = False                 # nú aan het opnemen of opzoeken

        # Het paneel vertelt bij elke peiling of luisteren zinvol is: staat de
        # receiver niet op de platenspeler, dan valt er niets te herkennen. Loopt
        # die melding af (paneel uit, kabel eruit), dan luisteren we weer op
        # eigen houtje — anders zou een stuk paneel de herkenning meenemen.
        self.paneel_wil = True
        self.paneel_tot = 0.0

        # Staat de versterker aan? Een plaat die je niet kunt horen draait niet,
        # dus dan is elk geluid in de kamer per definitie iets anders. Alleen
        # blokkeren als we het zéker weten: kan het paneel de receiver niet
        # bereiken, dan is "uit" een gok en luisteren we gewoon door.
        self.versterker_aan = True
        self.herkans_op: float | None = None  # opnieuw proberen na een misser
        self.missers = 0                      # op rij, zonder tussenliggende stilte

        # De laatste opzoeking die niets opleverde. Zolang die er staat kun je
        # vanaf het paneel een album aanwijzen en dat eraan koppelen — precies
        # op het moment dat de plaat nog draait, in plaats van 's avonds met je
        # telefoon door een wachtrij. En dat is ook het moment waarop het
        # fragment nog bij het geluid hoort dat je hoort.
        self.open_play_id: int | None = None
        self.forceer = asyncio.Event()
        self.laatste = "nog niets gehoord"
        self.release_id: int | None = None     # hoes uit je eigen kast
        self.hoes_url: str | None = None       # hoes van de dienst, als tweede keus
        self.artiest = ""                      # los, voor het CrowPanel
        self.titel = ""
        self.album = ""
        self.niveau_db = -99.0

        # Hoe vaak het CrowPanel om /nu vroeg. Puur diagnostisch: zo zie je op
        # /status of het paneel je werkelijk bereikt, zonder elke vier seconden
        # een regel in het logboek te zetten.
        self.vragen_paneel = 0
        self.laatste_paneel = ""

        self.hoes_cache_bron = ""               # verkleinde hoes, één plaat diep
        self.hoes_cache: bytes = b""
        self.koppelen = 0                       # platen die op koppeling wachten
        self.koppelen_tot = 0.0                 # tot wanneer die telling geldt

        # De klok telt geluid, niet wandtijd: elk blok is precies BLOK_S aan
        # audio. Dat is niet hetzelfde. Loopt arecord even achter of springt
        # het systeem in de tijd, dan blijven de drempels hieronder kloppen —
        # met time.time() zou een hapering een kant kunnen overslaan of juist
        # midden in een plaat opnieuw laten vragen.
        self.klok = 0.0

    # -- opname ------------------------------------------------------------
    async def start_arecord(self):
        return await asyncio.create_subprocess_exec(
            "arecord", "-D", APPARAAT, "-f", "S16_LE", "-r", str(TEMPO),
            "-c", "1", "-t", "raw", "-q",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def draai(self) -> None:
        while True:
            proc = await self.start_arecord()
            try:
                await self.lus(proc)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                print("[luister] microfoon viel weg, opnieuw over 5 s", flush=True)
            except Exception as e:                              # noqa: BLE001
                print(f"[luister] fout: {e!r}", flush=True)
            finally:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
            await asyncio.sleep(5)

    async def lus(self, proc) -> None:
        while True:
            blok = await proc.stdout.readexactly(BYTES_PER_BLOK)
            self.klok += BLOK_S
            mon = np.frombuffer(blok, dtype="<i2").astype(np.float32) / 32768.0
            niveau = db(float(np.sqrt(np.mean(mon * mon))))
            self.niveau_db = niveau

            # De vloer volgt de stilte, niet de muziek. Meteen mee omlaag; maar
            # omhoog alleen zolang het niveau dicht bij de vloer ligt, want dan
            # is het de kamer die luider werd. Zit er muziek overheen, dan staat
            # de vloer stil — anders kruipt hij tijdens een lange kant omhoog en
            # verdwijnt de marge waar je hem juist nodig hebt.
            if self.vloer_db <= -98.0:
                self.vloer_db = niveau               # eerste blok: hier beginnen
            elif niveau < self.vloer_db:
                self.vloer_db = niveau
            elif niveau < self.vloer_db + VLOER_STIL_DB:
                self.vloer_db += VLOER_STIJG_DB

            nu = self.klok
            luid = niveau > self.vloer_db + SPRONG_DB

            if luid:
                self.stil_sinds = None
                if self.luid_sinds is None:
                    self.luid_sinds = nu
            else:
                self.luid_sinds = None
                if self.stil_sinds is None:
                    self.stil_sinds = nu
                # Lang genoeg stil: de kant is afgelopen, we mogen weer vragen.
                if self.bezig and nu - self.stil_sinds > STILTE_S:
                    self.bezig = False
                    self.herkans_op = None
                    # Stilte is de streep onder wat er was. Wat hierna komt is
                    # een nieuwe gebeurtenis en verdient weer een volle kans.
                    self.missers = 0

                # Het beeld pas veel later wissen. Zo blijft de hoes staan
                # tijdens een zachte passage, en verdwijnt hij als de plaat er
                # werkelijk af is.
                if self.artiest and nu - self.stil_sinds > BEELD_HOUD_S:
                    self.release_id = None
                    self.hoes_url = None
                    self.artiest = self.titel = self.album = ""
                    # Ook de koppeling laten vallen: wat je nu zou aanwijzen
                    # hoort niet meer bij het geluid van een kwartier geleden.
                    self.open_play_id = None
                    print("[luister] lang stil, beeld leeggemaakt", flush=True)
                    print("[luister] stilte, klaar voor de volgende kant", flush=True)

            gevraagd = self.forceer.is_set()

            # Zelf aftikken mag altijd; vanzelf beginnen alleen als het paneel
            # zegt dat er een plaat op ligt én de versterker aanstaat.
            mag = ((self.paneel_wil or time.monotonic() > self.paneel_tot)
                   and self.versterker_aan)
            begint = (mag
                      and self.luid_sinds is not None
                      and nu - self.luid_sinds > START_S
                      and not self.bezig)

            # Mislukte opzoeking: het blijft spelen, dus een stuk verderop in de
            # plaat kan best lukken. Wachten tot het stil is zou betekenen dat je
            # een hele kant lang niets meer te zien krijgt.
            herkans = (mag and self.herkans_op is not None and nu >= self.herkans_op
                       and self.luid_sinds is not None)
            if herkans:
                self.herkans_op = None

            if gevraagd or begint or herkans:
                self.forceer.clear()
                self.luistert = True
                if not gevraagd and not herkans:
                    # De naald staat er net op; even laten zakken voor we happen.
                    await self.slik(proc, AANLOOP_S)
                pcm = await self.hap(proc, FRAGMENT_S)
                self.bezig = True
                self.luid_sinds = None
                try:
                    await self.vraag(naar_wav(pcm))
                finally:
                    self.luistert = False

    async def slik(self, proc, seconden: float) -> None:
        n = int(seconden / BLOK_S)
        for _ in range(n):
            await proc.stdout.readexactly(BYTES_PER_BLOK)
            self.klok += BLOK_S

    async def hap(self, proc, seconden: float) -> bytes:
        n = int(seconden / BLOK_S)
        uit = []
        for _ in range(n):
            uit.append(await proc.stdout.readexactly(BYTES_PER_BLOK))
            self.klok += BLOK_S
        return b"".join(uit)

    # -- het brein vragen --------------------------------------------------
    async def vraag(self, wav: bytes) -> None:
        print(f"[luister] {len(wav)//1024} kB naar het brein", flush=True)
        try:
            async with ClientSession(timeout=ClientTimeout(total=60)) as s:
                async with s.post(f"{BREIN}/api/listen", data=wav,
                                  headers={"Content-Type": "audio/wav"}) as r:
                    body = await r.json()
        except Exception as e:                                  # noqa: BLE001
            self.laatste = f"brein onbereikbaar: {e!r}"
            print(f"[luister] {self.laatste}", flush=True)
            return

        rel = body.get("release")
        treffer = next((r for r in body.get("results", []) if r.get("matched")), {})

        # Alleen bijwerken als er werkelijk iets herkend is. Een mislukte
        # opzoeking betekent niet dat er een andere plaat op ligt — hij draait
        # gewoon door, en een stuk verderop lukte het even niet. Wél wissen zou
        # de hoes midden in een kant laten verdwijnen, en dat is precies wat er
        # gebeurde toen de herkansing na 60 seconden niets opleverde.
        if body.get("matched"):
            self.missers = 0
            self.open_play_id = None
            self.release_id = rel["id"] if rel else None
            self.hoes_url = treffer.get("cover") or None
            self.artiest = treffer.get("artist") or (rel["artist"] if rel else "")
            self.titel = treffer.get("title") or ""
            self.album = (rel["title"] if rel else "") or treffer.get("album") or ""

        if body.get("matched") and rel:
            self.laatste = f"{rel['artist']} — {rel['title']}"
        elif body.get("matched"):
            self.laatste = (f"{treffer.get('artist','?')} — "
                            f"{treffer.get('title','?')} (niet in de kast)")
        else:
            self.open_play_id = body.get("playId")
            self.missers += 1
            if self.missers < MAX_HERKANSEN:
                self.laatste = "onbekend, in de wachtrij gezet"
                self.herkans_op = self.klok + HERKANS_S
            else:
                self.laatste = (f"{self.missers}x niets herkend — "
                                "wachten tot het stil wordt")
                self.herkans_op = None
        print(f"[luister] {self.laatste}", flush=True)


oren = Oren()
atv = AppleTV()


async def api_luister(_request):
    """Nu meteen luisteren, ongeacht wat de drempel vindt."""
    oren.forceer.set()
    return web.json_response({"ok": True})


HIER = pathlib.Path(__file__).parent


async def index(_request):
    """De hele webinterface: één pagina met tabbladen.

    Hij staat als bestand naast deze code en niet als tekenreeks erin, want het
    is een pagina van honderden regels HTML en CSS — die hoort niet midden in de
    logica van de microfoon te staan.

    De pagina zelf haalt drie dingen op onder hetzelfde adres: /status en de
    Apple TV van deze dienst, /api/* van het brein en /paneel/* van het paneel.
    Waarom dat mag: zie de doorgeeflus hieronder.
    """
    return web.FileResponse(HIER / "static" / "index.html")


async def tel_koppelen() -> int:
    """Hoeveel platen wachten er op een koppeling.

    Met een cache van een halve minuut, want het paneel vraagt elke vier
    seconden en de wachtrij verandert hooguit een paar keer per avond.
    """
    if time.monotonic() < oren.koppelen_tot:
        return oren.koppelen
    try:
        async with ClientSession(timeout=ClientTimeout(total=5)) as s:
            async with s.get(f"{BREIN}/api/plays?status=unknown&limit=99") as r:
                body = await r.json()
        oren.koppelen = len(body.get("plays", []))
    except Exception:                                       # noqa: BLE001
        pass                                                # oude telling houden
    oren.koppelen_tot = time.monotonic() + 30
    return oren.koppelen


def _verklein_bytes(data: bytes, px: int | None = None) -> bytes:
    """Vierkant bijsnijden en terugbrengen tot px (standaard HOES_PX)."""
    from PIL import Image
    px = px or HOES_PX
    beeld = Image.open(io.BytesIO(data)).convert("RGB")
    kant = min(beeld.size)
    links = (beeld.width - kant) // 2
    boven = (beeld.height - kant) // 2
    beeld = beeld.crop((links, boven, links + kant, boven + kant))
    beeld = beeld.resize((px, px), Image.LANCZOS)
    uit = io.BytesIO()
    beeld.save(uit, "JPEG", quality=82, optimize=True)
    return uit.getvalue()


async def api_nu(request):
    """Wat er speelt, in de kortst mogelijke vorm — voor het CrowPanel.

    Bewust apart van /status: dat is een menspagina met dB-waarden, dit is wat
    een microcontroller met 480x480 pixels nodig heeft en niets meer. Korte
    sleutels en platte tekst, zodat de ESP32 het met een handvol bytes aan
    JSON-buffer kan lezen.
    """
    # Alleen tellen wat van het paneel komt. Dat is te zien aan `luister`: die
    # parameter stuurt alleen het paneel mee (zie brein.cpp). Sinds de
    # webinterface dit eindpunt ook gebruikt — om precies te tonen wat er op het
    # schermpje staat — zou meetellen de diagnose juist vertroebelen: dan zegt
    # "paneel polls" evenveel over je telefoon als over het paneel.
    if "luister" in request.query:
        oren.vragen_paneel += 1
        oren.laatste_paneel = request.remote or "?"
        oren.paneel_wil = request.query["luister"] not in ("0", "false", "nee")
        oren.paneel_tot = time.monotonic() + 60

    # Staat de receiver niet op de platenspeler, dan is de Apple TV de bron —
    # als die gekoppeld is en iets afspeelt. Dat is beter dan meeluisteren:
    # het apparaat wéét wat het doet, inclusief de hoes.
    # Ook melden als er niets speelt maar er wel een app open staat: dat de
    # Apple TV op YouTube staat is op zichzelf al informatie, en anders val je
    # terug op de microfoon die daar niets te zoeken heeft.
    if not oren.paneel_wil and atv.apparaat is not None and (
            atv.artiest or atv.titel or atv.app_id):
        return web.json_response({
            "koppelen": await tel_koppelen(),
            "artiest": atv.artiest,
            "titel": atv.titel,
            "album": atv.album or atv.titel,
            "hoes": bool(atv.hoes) or bool(await appicoon.icoon(atv.app_id)),
            # Een logo is geen hoes maar een plaatsvervanger: het paneel verbergt
            # tekst achter een echte hoes, maar bij een logo hoort de titel er
            # juist bij — anders zie je een merk en niet wat er draait.
            "logo": not atv.hoes and bool(await appicoon.icoon(atv.app_id)),
            "kast": False,
            "speelt": atv.speelt,
            "luistert": False,
            "bron": "appletv",
            "app": atv.app,
            "heet": pi_warmte()["heet"],
        })
    return web.json_response({
        "koppelen": await tel_koppelen(),
        "artiest": oren.artiest,
        "titel": oren.titel,
        "album": oren.album,
        "hoes": bool(oren.release_id or oren.hoes_url),   # staat er iets op /hoes
        "kast": oren.release_id is not None,  # gevonden in de eigen collectie
        "speelt": oren.bezig,
        "luistert": oren.luistert,
        # Staat er een opzoeking open die niets opleverde? Dan kun je vanaf het
        # paneel een album aanwijzen en dat eraan hangen.
        "koppelbaar": oren.open_play_id is not None,
        "heet": pi_warmte()["heet"],
    })


async def api_hoes(_request):
    """De hoes, doorgegeven van het brein.

    Zo hoeft het paneel maar één adres te kennen. Het haalt hem hier op en niet
    rechtstreeks bij het brein, want dat scheelt een tweede poort in de
    instellingen en een tweede plek waar iets stuk kan.
    """
    # Eerst je eigen kast, dan pas wat de dienst meestuurde. Die tweede is niet
    # bijzaak: alles wat je níét op vinyl hebt — radio, streaming, een plaat van
    # iemand anders — komt alleen daarlangs aan een hoes.
    # Apple TV gaat voor zolang de platenspeler niet aan de beurt is — en dan
    # ook uitsluitend. Doorvallen naar de plaatroute gaf de hoes van de vorige
    # LP bij een YouTube-video zonder afbeelding, en dat is erger dan niets.
    if not oren.paneel_wil and atv.apparaat is not None:
        if atv.hoes:
            klein = await asyncio.to_thread(_verklein_bytes, atv.hoes)
            return web.Response(body=klein, content_type="image/jpeg")
        # Geen afbeelding bij deze titel — YouTube geeft er geen door. Dan het
        # logo van de app, opgehaald bij Apple's eigen zoekingang.
        logo = await appicoon.icoon(atv.app_id)
        if logo:
            return web.Response(body=logo, content_type="image/jpeg")
        raise web.HTTPNotFound()

    if oren.release_id is not None:
        bron = f"{BREIN}/api/cover/{oren.release_id}"
    elif oren.hoes_url:
        bron = oren.hoes_url
    else:
        raise web.HTTPNotFound()

    if oren.hoes_cache_bron == bron and oren.hoes_cache:
        return web.Response(body=oren.hoes_cache, content_type="image/jpeg")

    async with ClientSession(timeout=ClientTimeout(total=15)) as s:
        async with s.get(bron) as r:
            if r.status != 200:
                raise web.HTTPNotFound()
            rauw = await r.read()

    # Vierkant bijsnijden en terugbrengen tot HOES_PX. Het paneel decodeert dan
    # één op één in een buffer die het van tevoren kan reserveren.
    klein = await asyncio.to_thread(_verklein_bytes, rauw)
    oren.hoes_cache_bron, oren.hoes_cache = bron, klein
    return web.Response(body=klein, content_type="image/jpeg")


# -- de platenkast voor het paneel ------------------------------------------
#
# Het paneel heeft acht megabyte PSRAM en je kast heeft 549 albums. De hoezen
# passen er niet in — één hoes van 480 pixels is al 460 kB — maar de namen wel.
# Dus krijgt het paneel de lijst in één keer en de plaatjes stuk voor stuk, en
# alleen die van de drie die in beeld staan.
#
# De lijst gaat als platte tekst en niet als JSON: een ESP32 die 40 kB JSON moet
# ontleden is daar seconden mee bezig, terwijl regels splitsen op een tab bijna
# niets kost. Eén regel per album, oplopend op artiest zoals het brein hem al
# sorteert.
KAST_PX = int(os.environ.get("SHELF_PX", "138"))
KAST_CACHE = HIER.parent / "brein" / "data" / "kasthoezen"


async def api_kast(_request):
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            async with s.get(f"{BREIN}/api/collection?q=&limit=5000") as r:
                body = await r.json()
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"brein niet bereikbaar: {e!r}")

    regels = []
    for rel in body.get("releases", []):
        # Tabs uit de veldwaarden halen, anders loopt het splitsen mis.
        artiest = (rel.get("artist") or "").replace("\t", " ").strip()
        titel = (rel.get("title") or "").replace("\t", " ").strip()
        regels.append(f"{rel['id']}\t{artiest}\t{titel}")
    return web.Response(text="\n".join(regels), content_type="text/plain")


async def api_koppel(request):
    """Het album dat je op het paneel aanwees koppelen aan wat er nu speelt.

    Dit is de wachtrij, maar dan op het juiste moment. Normaal koppel je 's
    avonds met je telefoon een fragment aan een plaat die je je half herinnert;
    zo doe je het terwijl de naald er nog in ligt en je de hoes in je hand hebt.

    Het brein doet het echte werk: koppelen én het bewaarde fragment als
    vingerafdruk bij die release vastleggen. Daardoor wordt dezelfde kant de
    volgende keer lokaal herkend, zonder dienst — precies de les die alleen jij
    kon geven.
    """
    if oren.open_play_id is None:
        return web.json_response({"ok": False, "fout": "niets om te koppelen"},
                                 status=409)
    try:
        rel_id = int(request.query.get("id", ""))
    except ValueError:
        return web.json_response({"ok": False, "fout": "geen id"}, status=400)

    play_id = oren.open_play_id
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            # Eerst opzoeken of dit album bestaat, dan pas koppelen. Andersom
            # zou een verkeerd nummer een luisterbeurt aan het niets hangen —
            # en, erger, het fragment als vingerafdruk bij een release zetten
            # die er niet is. Een koppeling is blijvend; die maak je niet op goed
            # vertrouwen.
            async with s.get(f"{BREIN}/api/collection?q=&limit=5000") as r:
                lijst = (await r.json()).get("releases", [])
            rel = next((x for x in lijst if x["id"] == rel_id), None)
            if rel is None:
                return web.json_response(
                    {"ok": False, "fout": f"album {rel_id} bestaat niet"}, status=404)

            async with s.post(f"{BREIN}/api/plays/{play_id}/link",
                              json={"releaseId": rel_id}) as r:
                uit = await r.json()
    except Exception as e:                                  # noqa: BLE001
        return web.json_response({"ok": False, "fout": f"{e!r}"}, status=502)

    oren.release_id = rel_id
    oren.hoes_url = None
    oren.artiest = rel["artist"]
    oren.titel = rel["title"]
    oren.album = rel["title"]
    oren.laatste = f"{rel['artist']} — {rel['title']} (zelf gekoppeld)"
    oren.hoes_cache_bron, oren.hoes_cache = "", b""
    oren.open_play_id = None
    oren.koppelen_tot = 0.0                    # telling opnieuw ophalen

    print(f"[luister] {oren.laatste}, {uit.get('hashes', 0)} vingerafdrukken",
          flush=True)
    return web.json_response({"ok": True, "hashes": uit.get("hashes", 0),
                              "artiest": oren.artiest, "titel": oren.titel})


async def api_kasthoes(request):
    """Eén hoes, klein genoeg om op het paneel te decoderen.

    Twee maten: de plaat in het midden staat groter dan die ernaast. Schalen op
    de ESP32 zou geheugen en tijd kosten die daar niet zijn, en hier is het een
    kwestie van milliseconden — dezelfde afweging als bij /hoes.
    """
    try:
        rel_id = int(request.query.get("id", ""))
        # Tot 480, want kies je een album in de kast dan komt diezelfde hoes
        # schermvullend terug op het volumescherm.
        px = min(int(request.query.get("px", KAST_PX)), 480)
    except ValueError:
        raise web.HTTPBadRequest(text="id en px moeten getallen zijn")

    KAST_CACHE.mkdir(parents=True, exist_ok=True)
    pad = KAST_CACHE / f"{rel_id}-{px}.jpg"
    if pad.exists():
        return web.FileResponse(pad)

    try:
        async with ClientSession(timeout=ClientTimeout(total=20)) as s:
            async with s.get(f"{BREIN}/api/cover/{rel_id}") as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                rauw = await r.read()
    except web.HTTPException:
        raise
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"hoes ophalen mislukt: {e!r}")

    klein = await asyncio.to_thread(_verklein_bytes, rauw, px)
    pad.write_bytes(klein)
    return web.Response(body=klein, content_type="image/jpeg")


# Where the panel lives.
#
# You should not have to configure this. The panel polls /nu every four seconds
# and every one of those requests carries its address, so the Pi simply
# remembers who called. Setting PANEL_HOST overrides that — useful if you have
# two panels, or if you want to reach one that is not polling yet.
#
# The alternative was asking for an IP during setup, which is a poor question:
# at that moment the panel usually has no network yet, so you would be typing
# an address that does not exist.
PANEEL = os.environ.get("PANEL_HOST", os.environ.get("PANEEL_HOST", ""))


def paneel_host() -> str:
    return PANEEL or oren.laatste_paneel


async def _doorgeef(request, doel: str, wat: str):
    """Een verzoek onveranderd doorzetten en het antwoord teruggeven.

    Zo staat de hele webinterface op één adres terwijl de drie delen blijven
    waar ze horen: de wachtrij en de collectie in het brein, de instellingen op
    het paneel zelf, de microfoon hier. De browser ziet er niets van, en dat is
    het punt — anders liep je met drie poortnummers in je hoofd rond.

    Let op: Content-Type gaat mee zoals hij binnenkwam. Bij het handmatig
    opvoeren van een plaat is dat multipart mét de scheidingstekens, en die
    weggooien maakt het formulier onleesbaar aan de andere kant.
    """
    if request.query_string:
        doel += "?" + request.query_string

    body = await request.read() if request.method != "GET" else None
    kop = {}
    if request.headers.get("Content-Type"):
        kop["Content-Type"] = request.headers["Content-Type"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=60)) as s:
            async with s.request(request.method, doel, data=body, headers=kop) as r:
                rauw = await r.read()
                return web.Response(body=rauw, status=r.status,
                                    content_type=r.content_type)
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"{wat} niet bereikbaar: {e!r}")


async def brein_proxy(request):
    """/api/* hoort bij het brein, een poort verderop op dezelfde Pi."""
    return await _doorgeef(request, f"{BREIN}/api/{request.match_info['staart']}",
                           "brein")


async def paneel_proxy(request):
    """Het CrowPanel doorgeven.

    De pagina van het paneel gebruikt relatieve paden, dus hem onder /paneel/
    hangen werkt zonder er iets aan te herschrijven — zowel voor de eigen
    pagina van het paneel als voor de tabbladversie hier.
    """
    host = paneel_host()
    if not host:
        raise web.HTTPServiceUnavailable(
            text="the panel has not been seen yet; it announces itself as soon "
                 "as it polls this Pi")
    return await _doorgeef(request,
                           f"http://{host}/{request.match_info.get('staart', '')}",
                           "paneel")


async def paneel_wortel(request):
    # Zonder afsluitende schuine streep kloppen de relatieve paden niet.
    if not request.path.endswith("/"):
        raise web.HTTPFound(request.path + "/")
    return await paneel_proxy(request)


# -- Apple TV ---------------------------------------------------------------
async def atv_scan(_request):
    return web.json_response({"apparaten": await atv.scan()})


async def atv_pair(request):
    body = await request.json()
    return web.json_response(await atv.koppel_start(body.get("id", "")))


async def atv_pin(request):
    body = await request.json()
    return web.json_response(await atv.koppel_pin(str(body.get("pin", ""))))


async def atv_vergeet(_request):
    await atv.vergeet()
    return web.json_response({"ok": True})


async def atv_status(_request):
    g = atv.gekoppeld()
    return web.json_response({
        "gekoppeld": bool(g),
        "naam": (g or {}).get("naam", ""),
        "verbonden": atv.apparaat is not None,
        "speelt": atv.speelt,
        "artiest": atv.artiest,
        "titel": atv.titel,
        "album": atv.album,
        "hoes": bool(atv.hoes),
        "hoesBytes": len(atv.hoes),
        "app": atv.app,
        "appId": atv.app_id,
        "fout": atv.fout,
        # Hoe oud deze gegevens zijn. Zonder dit ziet een bevroren verbinding
        # er precies hetzelfde uit als een Apple TV die al een uur dezelfde
        # video speelt, en dat verschil wil je juist kunnen zien.
        "seconden": (round(time.monotonic() - atv.laatste_update)
                     if atv.laatste_update else None),
    })


async def api_status(_request):
    return web.json_response({
        "niveauDb": round(oren.niveau_db, 1),
        "ruisvloerDb": round(oren.vloer_db, 1),
        "drempelDb": round(oren.vloer_db + SPRONG_DB, 1),
        "speelt": oren.bezig,
        "luistert": oren.luistert,
        "laatste": oren.laatste,
        "releaseId": oren.release_id,
        "hoesUrl": oren.hoes_url,
        "apparaat": APPARAAT,
        "luisterenToegestaan": ((oren.paneel_wil or time.monotonic() > oren.paneel_tot)
                                and oren.versterker_aan),
        "versterkerAan": oren.versterker_aan,
        "missers": oren.missers,
        "maxHerkansen": MAX_HERKANSEN,
        "pi": pi_warmte(),
        "paneelVragen": oren.vragen_paneel,
        "paneelVan": oren.laatste_paneel,
    })


async def bewaak_versterker() -> None:
    """Bijhouden of de versterker aanstaat, los van de audiolus.

    Apart en niet in lus(): daar wordt elke tiende seconde een blok gelezen, en
    daar hoort geen netwerkverzoek tussen. Tien seconden is ruim genoeg — je
    zet de versterker niet aan en uit tussen twee kanten door.
    """
    while True:
        host = paneel_host()
        if host:
            try:
                async with ClientSession(timeout=ClientTimeout(total=4)) as s:
                    async with s.get(f"http://{host}/api/state") as r:
                        st = await r.json()
                # Alleen bij zekerheid dichtzetten: geen verbinding met de
                # receiver betekent dat het paneel het ook niet weet.
                oren.versterker_aan = not (st.get("connected") and
                                           not st.get("powered"))
            except Exception:                                   # noqa: BLE001
                oren.versterker_aan = True      # paneel weg: niet gaan raden
        await asyncio.sleep(10)


async def start(app):
    app["oren"] = asyncio.create_task(oren.draai())
    app["avr"] = asyncio.create_task(bewaak_versterker())
    if atv.gekoppeld():
        app["atv"] = asyncio.create_task(atv.verbind())
        app["atv_bewaking"] = asyncio.create_task(atv.bewaak())


async def stop(app):
    for naam in ("oren", "avr", "atv_bewaking"):
        if naam in app:
            app[naam].cancel()


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/luister", api_luister)
    app.router.add_get("/status", api_status)
    app.router.add_get("/nu", api_nu)
    app.router.add_get("/hoes", api_hoes)
    app.router.add_get("/kast", api_kast)
    app.router.add_get("/kasthoes", api_kasthoes)
    app.router.add_post("/koppel", api_koppel)
    app.router.add_get("/appletv/scan", atv_scan)
    app.router.add_get("/appletv/status", atv_status)
    app.router.add_post("/appletv/pair", atv_pair)
    app.router.add_post("/appletv/pin", atv_pin)
    app.router.add_post("/appletv/vergeet", atv_vergeet)

    # De twee doorgeefroutes. Ze staan achteraan omdat ze met een joker eindigen
    # en anders de vaste routes hierboven zouden opslokken.
    app.router.add_route("*", "/api/{staart:.*}", brein_proxy)
    app.router.add_route("*", "/paneel", paneel_wortel)
    app.router.add_route("*", "/paneel/{staart:.*}", paneel_proxy)

    app.on_startup.append(start)
    app.on_cleanup.append(stop)

    async def draaien():
        # Eén applicatie op twee poorten, en niet twee applicaties. Poort 80 was
        # eerst een apart portaaltje met drie links naar de andere pagina's; nu
        # er nog maar één pagina is, is dat tussenstation weg en luistert
        # dezelfde interface gewoon op allebei.
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", POORT).start()
        print(f"[luister] microfoon {APPARAAT}, brein op {BREIN}, "
              f"panel {PANEEL or 'auto'}, port {POORT}", flush=True)

        # Poort 80 is een extraatje: lukt het niet (geen rechten), dan blijft de
        # rest gewoon draaien in plaats van dat de dienst omvalt.
        try:
            await web.TCPSite(runner, "0.0.0.0", 80).start()
            print("[luister] ook op poort 80", flush=True)
        except Exception as e:                              # noqa: BLE001
            print(f"[luister] geen poort 80: {e!r}", flush=True)

        await asyncio.Event().wait()

    try:
        asyncio.run(draaien())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
