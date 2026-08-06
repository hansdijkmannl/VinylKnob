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
import appicon
from appletv import AppleTV
from aiohttp import ClientSession, ClientTimeout, web

# De hoes wordt hier verkleind en niet op het paneel: een ESP32 die een JPEG van
# 600 pixels moet schalen kost geheugen en tijd die hij niet heeft, terwijl de Pi
# het in tientallen milliseconden doet.
COVER_PX = int(os.environ.get("COVER_PX", "480"))

# -- instellingen, allemaal te overschrijven met omgevingsvariabelen ---------
BRAIN        = os.environ.get("BREIN_URL", "http://127.0.0.1:8790")
MIC_DEVICE_NAME     = os.environ.get("MIC_DEVICE", "plughw:1,0")
RATE        = int(os.environ.get("MIC_RATE", "44100"))
PORT        = int(os.environ.get("LUISTER_PORT", "8791"))

BLOCK_S       = 0.1                     # zo vaak meten we het niveau
CLIP_S   = float(os.environ.get("CLIP_SECONDS", "8"))
SETTLE_S    = float(os.environ.get("SETTLE_SECONDS", "4"))    # naald laten zakken
START_S      = float(os.environ.get("START_SECONDS", "2.5"))   # zo lang geluid = het speelt
QUIET_S     = float(os.environ.get("QUIET_SECONDS", "15"))    # zo lang stil = kant is klaar
RETRY_S    = float(os.environ.get("RETRY_SECONDS", "60"))    # na een mislukte opzoeking

# Hoe vaak achter elkaar we het opnieuw proberen als er niets herkend wordt.
#
# Zonder grens loopt dit door zolang er geluid is, en dat is precies wat er
# gebeurde: een pratende video op de Apple TV leverde vijfenveertig opzoekingen
# op één ochtend, elke vijfenzeventig seconden eentje, allemaal leeg. Voor een
# plaat helpt herkansen wel — de eerste hap kan een zachte intro zijn — maar
# lukt het drie keer niet, dan ligt er geen plaat en gaan pogingen vier tot
# vijfentwintig daar niets aan veranderen. Wachten op echte stilte is dan de
# juiste zet: dat is het teken dat er iets nieuws kan beginnen.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# Hoe lang de hoes blijft staan nadat het stil werd. Bewust veel langer dan
# QUIET_SECONDS: dat getal bepaalt wanneer er weer geluisterd mag worden, en dat
# wil je kort. Maar het beeld leegmaken is iets anders — bij een marginaal
# signaal zakt een zachte passage al onder de drempel, en dan verdwijnt de hoes
# terwijl de plaat gewoon doorspeelt. Vijf minuten stilte is pas echt afgelopen.
COVER_HOLD_S = float(os.environ.get("COVER_HOLD_SECONDS", "300"))
TRIGGER_DB    = float(os.environ.get("TRIGGER_DB", "12"))       # boven de ruisvloer
# De ruisvloer volgt snel naar beneden en heel langzaam omhoog. Dat is niet
# hetzelfde als het tiende percentiel over de laatste minuut, en het verschil
# doet ertoe: speelt er een minuut aaneengesloten muziek, dan wórdt die muziek
# het tiende percentiel en zakt de gemeten marge naar nul. Precies de reden dat
# een plaat die prima te horen is toch onder de drempel bleef.
FLOOR_RISE_DB = 0.02          # per blok van 0,1 s, dus ~0,2 dB per seconde
FLOOR_QUIET_DB  = 6.0           # zo dicht bij de vloer telt als "kamer"

BYTES_PER_BLOCK = int(RATE * BLOCK_S) * 2       # 16 bits mono


# Vanaf hier zet de Pi zijn ventilator op de hoogste stand; knijpen begint pas
# bij 80. Onder deze grens is warm gewoon warm en hoeft het scherm er niets over
# te zeggen — een permanente temperatuurmeter op een scherm voor albumhoezen is
# rommel, een waarschuwing als het ertoe doet niet.
HOT_C = float(os.environ.get("WARN_TEMP_C", "75"))


def pi_heat() -> dict:
    """Temperatuur, ventilator en of er geknepen wordt."""
    out = {"tempC": None, "fanRpm": None, "geknepen": False, "heet": False}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["tempC"] = round(int(f.read()) / 1000, 1)
    except Exception:                                       # noqa: BLE001
        pass
    for pad in ("/sys/class/hwmon/hwmon0/fan1_input",
                "/sys/class/hwmon/hwmon1/fan1_input",
                "/sys/class/hwmon/hwmon2/fan1_input"):
        try:
            with open(pad) as f:
                out["fanRpm"] = int(f.read())
                break
        except Exception:                                   # noqa: BLE001
            continue
    try:
        with open("/sys/devices/platform/soc/soc:firmware/get_throttled") as f:
            out["geknepen"] = int(f.read().strip(), 16) != 0
    except Exception:                                       # noqa: BLE001
        pass
    out["heet"] = bool(out["geknepen"] or (out["tempC"] or 0) >= HOT_C)
    return out


def db(rms: float) -> float:
    return 20.0 * np.log10(max(rms, 1e-9))


def to_wav(pcm: bytes) -> bytes:
    """Het brein wil een gewone 16-bits WAV; arecord levert kale PCM."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


class Ears:
    def __init__(self) -> None:
        self.floor_db = -99.0                 # volgt de stilte, niet de muziek
        self.loud_since: float | None = None
        self.quiet_since: float | None = 0.0
        self.playing = False                    # er speelt iets, niet opnieuw vragen
        self.listening = False                 # nú aan het opnemen of opzoeken

        # Het paneel vertelt bij elke peiling of luisteren zinvol is: staat de
        # receiver niet op de platenspeler, dan valt er niets te herkennen. Loopt
        # die melding af (paneel uit, kabel eruit), dan luisteren we weer op
        # eigen houtje — anders zou een stuk paneel de herkenning meenemen.
        self.panel_wants = True
        self.panel_until = 0.0

        # Staat de versterker aan? Een plaat die je niet kunt horen draait niet,
        # dus dan is elk geluid in de kamer per definitie iets anders. Alleen
        # blokkeren als we het zéker weten: kan het paneel de receiver niet
        # bereiken, dan is "uit" een gok en luisteren we gewoon door.
        self.amplifier_on = True
        self.retry_at: float | None = None  # opnieuw proberen na een misser
        self.misses = 0                      # op rij, zonder tussenliggende stilte

        # De laatste opzoeking die niets opleverde. Zolang die er staat kun je
        # vanaf het paneel een album aanwijzen en dat eraan koppelen — precies
        # op het moment dat de plaat nog draait, in plaats van 's avonds met je
        # telefoon door een wachtrij. En dat is ook het moment waarop het
        # fragment nog bij het geluid hoort dat je hoort.
        self.open_play_id: int | None = None
        self.force = asyncio.Event()
        self.last = "nog niets gehoord"
        self.release_id: int | None = None     # hoes uit je eigen kast
        self.cover_url: str | None = None       # hoes van de dienst, als tweede keus
        self.artist = ""                      # los, voor het CrowPanel
        self.title = ""
        self.album = ""
        self.level_db = -99.0

        # Hoe vaak het CrowPanel om /nu vroeg. Puur diagnostisch: zo zie je op
        # /status of het paneel je werkelijk bereikt, zonder elke vier seconden
        # een regel in het logboek te zetten.
        self.panel_polls = 0
        self.last_panel_ip = ""

        self.cover_cache_src = ""               # verkleinde hoes, één plaat diep
        self.cover_cache: bytes = b""
        self.linkable = 0                       # platen die op koppeling wachten
        self.linkable_until = 0.0                 # tot wanneer die telling geldt

        # De klok telt geluid, niet wandtijd: elk blok is precies BLOK_S aan
        # audio. Dat is niet hetzelfde. Loopt arecord even achter of springt
        # het systeem in de tijd, dan blijven de drempels hieronder kloppen —
        # met time.time() zou een hapering een kant kunnen overslaan of juist
        # midden in een plaat opnieuw laten vragen.
        self.clock = 0.0

    # -- opname ------------------------------------------------------------
    async def start_arecord(self):
        return await asyncio.create_subprocess_exec(
            "arecord", "-D", MIC_DEVICE_NAME, "-f", "S16_LE", "-r", str(RATE),
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
            block = await proc.stdout.readexactly(BYTES_PER_BLOCK)
            self.clock += BLOCK_S
            mon = np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768.0
            level = db(float(np.sqrt(np.mean(mon * mon))))
            self.level_db = level

            # De vloer volgt de stilte, niet de muziek. Meteen mee omlaag; maar
            # omhoog alleen zolang het niveau dicht bij de vloer ligt, want dan
            # is het de kamer die luider werd. Zit er muziek overheen, dan staat
            # de vloer stil — anders kruipt hij tijdens een lange kant omhoog en
            # verdwijnt de marge waar je hem juist nodig hebt.
            if self.floor_db <= -98.0:
                self.floor_db = level               # eerste blok: hier beginnen
            elif level < self.floor_db:
                self.floor_db = level
            elif level < self.floor_db + FLOOR_QUIET_DB:
                self.floor_db += FLOOR_RISE_DB

            nu = self.clock
            luid = level > self.floor_db + TRIGGER_DB

            if luid:
                self.quiet_since = None
                if self.loud_since is None:
                    self.loud_since = nu
            else:
                self.loud_since = None
                if self.quiet_since is None:
                    self.quiet_since = nu
                # Lang genoeg stil: de kant is afgelopen, we mogen weer vragen.
                if self.playing and nu - self.quiet_since > QUIET_S:
                    self.playing = False
                    self.retry_at = None
                    # Stilte is de streep onder wat er was. Wat hierna komt is
                    # een nieuwe gebeurtenis en verdient weer een volle kans.
                    self.misses = 0

                # Het beeld pas veel later wissen. Zo blijft de hoes staan
                # tijdens een zachte passage, en verdwijnt hij als de plaat er
                # werkelijk af is.
                if self.artist and nu - self.quiet_since > COVER_HOLD_S:
                    self.release_id = None
                    self.cover_url = None
                    self.artist = self.title = self.album = ""
                    # Ook de koppeling laten vallen: wat je nu zou aanwijzen
                    # hoort niet meer bij het geluid van een kwartier geleden.
                    self.open_play_id = None
                    print("[luister] lang stil, beeld leeggemaakt", flush=True)
                    print("[luister] stilte, klaar voor de volgende kant", flush=True)

            gevraagd = self.force.is_set()

            # Zelf aftikken mag altijd; vanzelf beginnen alleen als het paneel
            # zegt dat er een plaat op ligt én de versterker aanstaat.
            mag = ((self.panel_wants or time.monotonic() > self.panel_until)
                   and self.amplifier_on)
            begint = (mag
                      and self.loud_since is not None
                      and nu - self.loud_since > START_S
                      and not self.playing)

            # Mislukte opzoeking: het blijft spelen, dus een stuk verderop in de
            # plaat kan best lukken. Wachten tot het stil is zou betekenen dat je
            # een hele kant lang niets meer te zien krijgt.
            retry = (mag and self.retry_at is not None and nu >= self.retry_at
                       and self.loud_since is not None)
            if retry:
                self.retry_at = None

            if gevraagd or begint or retry:
                self.force.clear()
                self.listening = True
                if not gevraagd and not retry:
                    # De naald staat er net op; even laten zakken voor we happen.
                    await self.slik(proc, SETTLE_S)
                pcm = await self.hap(proc, CLIP_S)
                self.playing = True
                self.loud_since = None
                try:
                    await self.vraag(to_wav(pcm))
                finally:
                    self.listening = False

    async def slik(self, proc, seconden: float) -> None:
        n = int(seconden / BLOCK_S)
        for _ in range(n):
            await proc.stdout.readexactly(BYTES_PER_BLOCK)
            self.clock += BLOCK_S

    async def hap(self, proc, seconden: float) -> bytes:
        n = int(seconden / BLOCK_S)
        out = []
        for _ in range(n):
            out.append(await proc.stdout.readexactly(BYTES_PER_BLOCK))
            self.clock += BLOCK_S
        return b"".join(out)

    # -- het brein vragen --------------------------------------------------
    async def vraag(self, wav: bytes) -> None:
        print(f"[luister] {len(wav)//1024} kB naar het brein", flush=True)
        try:
            async with ClientSession(timeout=ClientTimeout(total=60)) as s:
                async with s.post(f"{BRAIN}/api/listen", data=wav,
                                  headers={"Content-Type": "audio/wav"}) as r:
                    body = await r.json()
        except Exception as e:                                  # noqa: BLE001
            self.last = f"brein onbereikbaar: {e!r}"
            print(f"[luister] {self.last}", flush=True)
            return

        rel = body.get("release")
        treffer = next((r for r in body.get("results", []) if r.get("matched")), {})

        # Alleen bijwerken als er werkelijk iets herkend is. Een mislukte
        # opzoeking betekent niet dat er een andere plaat op ligt — hij draait
        # gewoon door, en een stuk verderop lukte het even niet. Wél wissen zou
        # de hoes midden in een kant laten verdwijnen, en dat is precies wat er
        # gebeurde toen de herkansing na 60 seconden niets opleverde.
        if body.get("matched"):
            self.misses = 0
            self.open_play_id = None
            self.release_id = rel["id"] if rel else None
            self.cover_url = treffer.get("cover") or None
            self.artist = treffer.get("artist") or (rel["artist"] if rel else "")
            self.title = treffer.get("title") or ""
            self.album = (rel["title"] if rel else "") or treffer.get("album") or ""

        if body.get("matched") and rel:
            self.last = f"{rel['artist']} — {rel['title']}"
        elif body.get("matched"):
            self.last = (f"{treffer.get('artist','?')} — "
                            f"{treffer.get('title','?')} (niet in de kast)")
        else:
            self.open_play_id = body.get("playId")
            self.misses += 1
            if self.misses < MAX_RETRIES:
                self.last = "onbekend, in de wachtrij gezet"
                self.retry_at = self.clock + RETRY_S
            else:
                self.last = (f"{self.misses}x niets herkend — "
                                "wachten tot het stil wordt")
                self.retry_at = None
        print(f"[luister] {self.last}", flush=True)


ears = Ears()
atv = AppleTV()


async def api_listen_now(_request):
    """Nu meteen luisteren, ongeacht wat de drempel vindt."""
    ears.force.set()
    return web.json_response({"ok": True})


HERE = pathlib.Path(__file__).parent


async def index(_request):
    """De hele webinterface: één pagina met tabbladen.

    Hij staat als bestand naast deze code en niet als tekenreeks erin, want het
    is een pagina van honderden regels HTML en CSS — die hoort niet midden in de
    logica van de microfoon te staan.

    De pagina zelf haalt drie dingen op onder hetzelfde adres: /status en de
    Apple TV van deze dienst, /api/* van het brein en /paneel/* van het paneel.
    Waarom dat mag: zie de doorgeeflus hieronder.
    """
    return web.FileResponse(HERE / "static" / "index.html")


async def count_linkable() -> int:
    """Hoeveel platen wachten er op een koppeling.

    Met een cache van een halve minuut, want het paneel vraagt elke vier
    seconden en de wachtrij verandert hooguit een paar keer per avond.
    """
    if time.monotonic() < ears.linkable_until:
        return ears.linkable
    try:
        async with ClientSession(timeout=ClientTimeout(total=5)) as s:
            async with s.get(f"{BRAIN}/api/plays?status=unknown&limit=99") as r:
                body = await r.json()
        ears.linkable = len(body.get("plays", []))
    except Exception:                                       # noqa: BLE001
        pass                                                # oude telling houden
    ears.linkable_until = time.monotonic() + 30
    return ears.linkable


def _shrink_bytes(data: bytes, px: int | None = None) -> bytes:
    """Vierkant bijsnijden en terugbrengen tot px (standaard HOES_PX)."""
    from PIL import Image
    px = px or COVER_PX
    image = Image.open(io.BytesIO(data)).convert("RGB")
    kant = min(image.size)
    links = (image.width - kant) // 2
    above = (image.height - kant) // 2
    image = image.crop((links, above, links + kant, above + kant))
    image = image.resize((px, px), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


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
        ears.panel_polls += 1
        ears.last_panel_ip = request.remote or "?"
        ears.panel_wants = request.query["luister"] not in ("0", "false", "nee")
        ears.panel_until = time.monotonic() + 60

    # Staat de receiver niet op de platenspeler, dan is de Apple TV de bron —
    # als die gekoppeld is en iets afspeelt. Dat is beter dan meeluisteren:
    # het apparaat wéét wat het doet, inclusief de hoes.
    # Ook melden als er niets speelt maar er wel een app open staat: dat de
    # Apple TV op YouTube staat is op zichzelf al informatie, en anders val je
    # terug op de microfoon die daar niets te zoeken heeft.
    if not ears.panel_wants and atv.device is not None and (
            atv.artist or atv.title or atv.app_id):
        return web.json_response({
            "koppelen": await count_linkable(),
            "artiest": atv.artist,
            "titel": atv.title,
            "album": atv.album or atv.title,
            "hoes": bool(atv.artwork) or bool(await appicon.icon(atv.app_id)),
            # Een logo is geen hoes maar een plaatsvervanger: het paneel verbergt
            # tekst achter een echte hoes, maar bij een logo hoort de titel er
            # juist bij — anders zie je een merk en niet wat er draait.
            "logo": not atv.artwork and bool(await appicon.icon(atv.app_id)),
            "kast": False,
            "speelt": atv.playing_now,
            "luistert": False,
            "bron": "appletv",
            "app": atv.app,
            "heet": pi_heat()["heet"],
        })
    return web.json_response({
        "koppelen": await count_linkable(),
        "artiest": ears.artist,
        "titel": ears.title,
        "album": ears.album,
        "hoes": bool(ears.release_id or ears.cover_url),   # staat er iets op /hoes
        "kast": ears.release_id is not None,  # gevonden in de eigen collectie
        "speelt": ears.playing,
        "luistert": ears.listening,
        # Staat er een opzoeking open die niets opleverde? Dan kun je vanaf het
        # paneel een album aanwijzen en dat eraan hangen.
        "koppelbaar": ears.open_play_id is not None,
        "heet": pi_heat()["heet"],
    })


async def api_cover(_request):
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
    if not ears.panel_wants and atv.device is not None:
        if atv.artwork:
            small = await asyncio.to_thread(_shrink_bytes, atv.artwork)
            return web.Response(body=small, content_type="image/jpeg")
        # Geen afbeelding bij deze titel — YouTube geeft er geen door. Dan het
        # logo van de app, opgehaald bij Apple's eigen zoekingang.
        logo = await appicon.icon(atv.app_id)
        if logo:
            return web.Response(body=logo, content_type="image/jpeg")
        raise web.HTTPNotFound()

    if ears.release_id is not None:
        source = f"{BRAIN}/api/cover/{ears.release_id}"
    elif ears.cover_url:
        source = ears.cover_url
    else:
        raise web.HTTPNotFound()

    if ears.cover_cache_src == source and ears.cover_cache:
        return web.Response(body=ears.cover_cache, content_type="image/jpeg")

    async with ClientSession(timeout=ClientTimeout(total=15)) as s:
        async with s.get(source) as r:
            if r.status != 200:
                raise web.HTTPNotFound()
            raw = await r.read()

    # Vierkant bijsnijden en terugbrengen tot HOES_PX. Het paneel decodeert dan
    # één op één in een buffer die het van tevoren kan reserveren.
    small = await asyncio.to_thread(_shrink_bytes, raw)
    ears.cover_cache_src, ears.cover_cache = source, small
    return web.Response(body=small, content_type="image/jpeg")


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
SHELF_PX = int(os.environ.get("SHELF_PX", "138"))
SHELF_CACHE = HERE.parent / "brein" / "data" / "kasthoezen"


async def api_shelf(_request):
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            async with s.get(f"{BRAIN}/api/collection?q=&limit=5000") as r:
                body = await r.json()
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"brein niet bereikbaar: {e!r}")

    lines = []
    for rel in body.get("releases", []):
        # Tabs uit de veldwaarden halen, anders loopt het splitsen mis.
        artist = (rel.get("artist") or "").replace("\t", " ").strip()
        title = (rel.get("title") or "").replace("\t", " ").strip()
        lines.append(f"{rel['id']}\t{artist}\t{title}")
    return web.Response(text="\n".join(lines), content_type="text/plain")


async def api_link(request):
    """Het album dat je op het paneel aanwees koppelen aan wat er nu speelt.

    Dit is de wachtrij, maar dan op het juiste moment. Normaal koppel je 's
    avonds met je telefoon een fragment aan een plaat die je je half herinnert;
    zo doe je het terwijl de naald er nog in ligt en je de hoes in je hand hebt.

    Het brein doet het echte werk: koppelen én het bewaarde fragment als
    vingerafdruk bij die release vastleggen. Daardoor wordt dezelfde kant de
    volgende keer lokaal herkend, zonder dienst — precies de les die alleen jij
    kon geven.
    """
    if ears.open_play_id is None:
        return web.json_response({"ok": False, "fout": "niets om te koppelen"},
                                 status=409)
    try:
        rel_id = int(request.query.get("id", ""))
    except ValueError:
        return web.json_response({"ok": False, "fout": "geen id"}, status=400)

    play_id = ears.open_play_id
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            # Eerst opzoeken of dit album bestaat, dan pas koppelen. Andersom
            # zou een verkeerd nummer een luisterbeurt aan het niets hangen —
            # en, erger, het fragment als vingerafdruk bij een release zetten
            # die er niet is. Een koppeling is blijvend; die maak je niet op goed
            # vertrouwen.
            async with s.get(f"{BRAIN}/api/collection?q=&limit=5000") as r:
                lijst = (await r.json()).get("releases", [])
            rel = next((x for x in lijst if x["id"] == rel_id), None)
            if rel is None:
                return web.json_response(
                    {"ok": False, "fout": f"album {rel_id} bestaat niet"}, status=404)

            async with s.post(f"{BRAIN}/api/plays/{play_id}/link",
                              json={"releaseId": rel_id}) as r:
                out = await r.json()
    except Exception as e:                                  # noqa: BLE001
        return web.json_response({"ok": False, "fout": f"{e!r}"}, status=502)

    ears.release_id = rel_id
    ears.cover_url = None
    ears.artist = rel["artist"]
    ears.title = rel["title"]
    ears.album = rel["title"]
    ears.last = f"{rel['artist']} — {rel['title']} (zelf gekoppeld)"
    ears.cover_cache_src, ears.cover_cache = "", b""
    ears.open_play_id = None
    ears.linkable_until = 0.0                    # telling opnieuw ophalen

    print(f"[luister] {ears.last}, {out.get('hashes', 0)} vingerafdrukken",
          flush=True)
    return web.json_response({"ok": True, "hashes": out.get("hashes", 0),
                              "artiest": ears.artist, "titel": ears.title})


async def api_shelf_cover(request):
    """Eén hoes, klein genoeg om op het paneel te decoderen.

    Twee maten: de plaat in het midden staat groter dan die ernaast. Schalen op
    de ESP32 zou geheugen en tijd kosten die daar niet zijn, en hier is het een
    kwestie van milliseconden — dezelfde afweging als bij /hoes.
    """
    try:
        rel_id = int(request.query.get("id", ""))
        # Tot 480, want kies je een album in de kast dan komt diezelfde hoes
        # schermvullend terug op het volumescherm.
        px = min(int(request.query.get("px", SHELF_PX)), 480)
    except ValueError:
        raise web.HTTPBadRequest(text="id en px moeten getallen zijn")

    SHELF_CACHE.mkdir(parents=True, exist_ok=True)
    pad = SHELF_CACHE / f"{rel_id}-{px}.jpg"
    if pad.exists():
        return web.FileResponse(pad)

    try:
        async with ClientSession(timeout=ClientTimeout(total=20)) as s:
            async with s.get(f"{BRAIN}/api/cover/{rel_id}") as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                raw = await r.read()
    except web.HTTPException:
        raise
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"hoes ophalen mislukt: {e!r}")

    small = await asyncio.to_thread(_shrink_bytes, raw, px)
    pad.write_bytes(small)
    return web.Response(body=small, content_type="image/jpeg")


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
PANEL = os.environ.get("PANEL_HOST", os.environ.get("PANEEL_HOST", ""))


def panel_host() -> str:
    return PANEL or ears.last_panel_ip


async def _forward(request, target: str, what: str):
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
        target += "?" + request.query_string

    body = await request.read() if request.method != "GET" else None
    kop = {}
    if request.headers.get("Content-Type"):
        kop["Content-Type"] = request.headers["Content-Type"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=60)) as s:
            async with s.request(request.method, target, data=body, headers=kop) as r:
                raw = await r.read()
                return web.Response(body=raw, status=r.status,
                                    content_type=r.content_type)
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"{what} niet bereikbaar: {e!r}")


async def brain_proxy(request):
    """/api/* hoort bij het brein, een poort verderop op dezelfde Pi."""
    return await _forward(request, f"{BRAIN}/api/{request.match_info['staart']}",
                           "brein")


async def panel_proxy(request):
    """Het CrowPanel doorgeven.

    De pagina van het paneel gebruikt relatieve paden, dus hem onder /paneel/
    hangen werkt zonder er iets aan te herschrijven — zowel voor de eigen
    pagina van het paneel als voor de tabbladversie hier.
    """
    host = panel_host()
    if not host:
        raise web.HTTPServiceUnavailable(
            text="the panel has not been seen yet; it announces itself as soon "
                 "as it polls this Pi")
    return await _forward(request,
                           f"http://{host}/{request.match_info.get('staart', '')}",
                           "paneel")


async def panel_root(request):
    # Zonder afsluitende schuine streep kloppen de relatieve paden niet.
    if not request.path.endswith("/"):
        raise web.HTTPFound(request.path + "/")
    return await panel_proxy(request)


# -- Apple TV ---------------------------------------------------------------
async def atv_scan(_request):
    return web.json_response({"apparaten": await atv.scan()})


async def atv_pair(request):
    body = await request.json()
    return web.json_response(await atv.pair_start(body.get("id", "")))


async def atv_pin(request):
    body = await request.json()
    return web.json_response(await atv.pair_pin(str(body.get("pin", ""))))


async def atv_forget(_request):
    await atv.forget()
    return web.json_response({"ok": True})


async def atv_status(_request):
    g = atv.paired()
    return web.json_response({
        "gekoppeld": bool(g),
        "naam": (g or {}).get("naam", ""),
        "verbonden": atv.device is not None,
        "speelt": atv.playing_now,
        "artiest": atv.artist,
        "titel": atv.title,
        "album": atv.album,
        "hoes": bool(atv.artwork),
        "hoesBytes": len(atv.artwork),
        "app": atv.app,
        "appId": atv.app_id,
        "fout": atv.error,
        # Hoe oud deze gegevens zijn. Zonder dit ziet een bevroren verbinding
        # er precies hetzelfde uit als een Apple TV die al een uur dezelfde
        # video speelt, en dat verschil wil je juist kunnen zien.
        "seconden": (round(time.monotonic() - atv.last_update)
                     if atv.last_update else None),
    })


async def api_status(_request):
    return web.json_response({
        "niveauDb": round(ears.level_db, 1),
        "ruisvloerDb": round(ears.floor_db, 1),
        "drempelDb": round(ears.floor_db + TRIGGER_DB, 1),
        "speelt": ears.playing,
        "luistert": ears.listening,
        "laatste": ears.last,
        "releaseId": ears.release_id,
        "hoesUrl": ears.cover_url,
        "apparaat": MIC_DEVICE_NAME,
        "luisterenToegestaan": ((ears.panel_wants or time.monotonic() > ears.panel_until)
                                and ears.amplifier_on),
        "versterkerAan": ears.amplifier_on,
        "missers": ears.misses,
        "maxHerkansen": MAX_RETRIES,
        "pi": pi_heat(),
        "paneelVragen": ears.panel_polls,
        "paneelVan": ears.last_panel_ip,
    })


async def watch_amplifier() -> None:
    """Bijhouden of de versterker aanstaat, los van de audiolus.

    Apart en niet in lus(): daar wordt elke tiende seconde een blok gelezen, en
    daar hoort geen netwerkverzoek tussen. Tien seconden is ruim genoeg — je
    zet de versterker niet aan en uit tussen twee kanten door.
    """
    while True:
        host = panel_host()
        if host:
            try:
                async with ClientSession(timeout=ClientTimeout(total=4)) as s:
                    async with s.get(f"http://{host}/api/state") as r:
                        st = await r.json()
                # Alleen bij zekerheid dichtzetten: geen verbinding met de
                # receiver betekent dat het paneel het ook niet weet.
                ears.amplifier_on = not (st.get("connected") and
                                           not st.get("powered"))
            except Exception:                                   # noqa: BLE001
                ears.amplifier_on = True      # paneel weg: niet gaan raden
        await asyncio.sleep(10)


async def start(app):
    app["oren"] = asyncio.create_task(ears.draai())
    app["avr"] = asyncio.create_task(watch_amplifier())
    if atv.paired():
        app["atv"] = asyncio.create_task(atv.connect())
        app["atv_bewaking"] = asyncio.create_task(atv.watch())


async def stop(app):
    for name in ("oren", "avr", "atv_bewaking"):
        if name in app:
            app[name].cancel()


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/luister", api_listen_now)
    app.router.add_get("/status", api_status)
    app.router.add_get("/nu", api_nu)
    app.router.add_get("/hoes", api_cover)
    app.router.add_get("/kast", api_shelf)
    app.router.add_get("/kasthoes", api_shelf_cover)
    app.router.add_post("/koppel", api_link)
    app.router.add_get("/appletv/scan", atv_scan)
    app.router.add_get("/appletv/status", atv_status)
    app.router.add_post("/appletv/pair", atv_pair)
    app.router.add_post("/appletv/pin", atv_pin)
    app.router.add_post("/appletv/vergeet", atv_forget)

    # De twee doorgeefroutes. Ze staan achteraan omdat ze met een joker eindigen
    # en anders de vaste routes hierboven zouden opslokken.
    app.router.add_route("*", "/api/{staart:.*}", brain_proxy)
    app.router.add_route("*", "/paneel", panel_root)
    app.router.add_route("*", "/paneel/{staart:.*}", panel_proxy)

    app.on_startup.append(start)
    app.on_cleanup.append(stop)

    async def draaien():
        # Eén applicatie op twee poorten, en niet twee applicaties. Poort 80 was
        # eerst een apart portaaltje met drie links naar de andere pagina's; nu
        # er nog maar één pagina is, is dat tussenstation weg en luistert
        # dezelfde interface gewoon op allebei.
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        print(f"[luister] microfoon {MIC_DEVICE_NAME}, brein op {BRAIN}, "
              f"panel {PANEL or 'auto'}, port {PORT}", flush=True)

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
