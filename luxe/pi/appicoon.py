"""
Het icoon van de app die op de Apple TV draait.

Bij een YouTube-video komt er geen afbeelding mee — die app geeft er geen door.
Een leeg scherm is dan zonde, en de appnaam in letters is maar half zo duidelijk
als het logo dat je kent. Apple heeft daar een openbare zoekingang voor: geef de
bundelnaam en je krijgt het icoon uit de App Store, zonder sleutel.

Wat er terugkomt is een vierkant icoon, geen schermvullende hoes. Daarom wordt
het hier op een donkere ondergrond gezet met ruimte eromheen: dan valt het op
zijn plek naast de echte hoezen in plaats van als opgeblazen postzegel.

Apple's eigen apps staan niet in de winkel en leveren dus niets. Daar blijft de
naam op het scherm staan, en dat is precies goed.
"""

from __future__ import annotations

import io
import pathlib

from aiohttp import ClientSession, ClientTimeout

CACHE = pathlib.Path(__file__).parent.parent / "brein" / "data" / "appicons"
EIGEN = CACHE / "eigen"
ZOEK = "https://itunes.apple.com/lookup"

VLAK = 480          # zelfde maat als een hoes, zodat het paneel niets hoeft te weten
ICOON = 130         # het logo zelf; de rest is lucht en ruimte voor tekst

# Het logo staat bovenin en niet in het midden: daaronder komen de titel en de
# artiest, en die willen die ruimte hebben. Op een rond scherm is er op deze
# hoogte nog ruim 300 pixels breed, dus het logo valt er niet af.
BOVEN = 66


async def _haal(bundel: str) -> bytes:
    async with ClientSession(timeout=ClientTimeout(total=12)) as s:
        async with s.get(ZOEK, params={"bundleId": bundel, "country": "NL"}) as r:
            body = await r.json(content_type=None)
        treffers = body.get("results") or []
        if not treffers:
            return b""
        url = treffers[0].get("artworkUrl512") or treffers[0].get("artworkUrl100")
        if not url:
            return b""
        async with s.get(url) as r:
            return await r.read() if r.status == 200 else b""


def _stel_samen(rauw: bytes) -> bytes:
    from PIL import Image, ImageDraw

    bron = Image.open(io.BytesIO(rauw))
    # Een logo met doorzichtige achtergrond hoort op het donkere vlak te komen,
    # niet op wit. Vandaar samenvoegen in plaats van botweg omzetten.
    if bron.mode in ("RGBA", "LA", "P"):
        bron = bron.convert("RGBA")
        onder = Image.new("RGBA", bron.size, (16, 16, 20, 255))
        bron = Image.alpha_composite(onder, bron)
    bron = bron.convert("RGB")

    # Niet-vierkante logo's (de tv-app is breed) passend maken zonder uitrekken.
    if bron.width != bron.height:
        kant = max(bron.size)
        vierkant = Image.new("RGB", (kant, kant), (16, 16, 20))
        vierkant.paste(bron, ((kant - bron.width) // 2, (kant - bron.height) // 2))
        bron = vierkant

    icoon = bron.resize((ICOON, ICOON), Image.LANCZOS)

    # App-iconen zijn vierkant met ronde hoeken; zonder die afronding ziet het
    # eruit als een screenshot in plaats van als een logo.
    masker = Image.new("L", (ICOON, ICOON), 0)
    ImageDraw.Draw(masker).rounded_rectangle(
        (0, 0, ICOON - 1, ICOON - 1), radius=int(ICOON * 0.22), fill=255)

    vlak = Image.new("RGB", (VLAK, VLAK), (16, 16, 20))
    vlak.paste(icoon, ((VLAK - ICOON) // 2, BOVEN), masker)

    uit = io.BytesIO()
    vlak.save(uit, "JPEG", quality=88, optimize=True)
    return uit.getvalue()


def bewaar_eigen(bundel: str, rauw: bytes) -> bytes:
    """Een zelf aangeleverd logo. Gaat voor op wat de App Store levert.

    Nodig omdat Apple's eigen apps — de tv-app, Music — niet in de winkel staan
    en daar dus geen icoon te halen valt. En handig als je een logo mooier vindt
    dan het officiele.
    """
    EIGEN.mkdir(parents=True, exist_ok=True)
    klaar = _stel_samen(rauw)
    (EIGEN / f"{bundel}.jpg").write_bytes(klaar)
    (CACHE / f"{bundel}.jpg").unlink(missing_ok=True)      # oude vondst vervalt
    return klaar


def eigen_lijst() -> list[str]:
    return sorted(p.stem for p in EIGEN.glob("*.jpg")) if EIGEN.exists() else []


async def icoon(bundel: str) -> bytes:
    """Geeft een schermvullende JPEG met het logo, of leeg als die er niet is."""
    if not bundel:
        return b""
    eigen = EIGEN / f"{bundel}.jpg"
    if eigen.exists():
        return eigen.read_bytes()

    CACHE.mkdir(parents=True, exist_ok=True)
    bestand = CACHE / f"{bundel}.jpg"
    if bestand.exists():
        return bestand.read_bytes()

    rauw = await _haal(bundel)
    if not rauw:
        bestand.write_bytes(b"")        # ook onthouden dát er niets is
        return b""

    import asyncio
    klaar = await asyncio.to_thread(_stel_samen, rauw)
    bestand.write_bytes(klaar)
    return klaar
