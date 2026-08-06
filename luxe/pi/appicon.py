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
OWN = CACHE / "eigen"
SEARCH_URL = "https://itunes.apple.com/lookup"

FIELD = 480          # zelfde maat als een hoes, zodat het paneel niets hoeft te weten
ICON_URL = 130         # het logo zelf; de rest is lucht en ruimte voor tekst

# Het logo staat bovenin en niet in het midden: daaronder komen de titel en de
# artiest, en die willen die ruimte hebben. Op een rond scherm is er op deze
# hoogte nog ruim 300 pixels breed, dus het logo valt er niet af.
TOP = 66


async def _fetch(bundle: str) -> bytes:
    async with ClientSession(timeout=ClientTimeout(total=12)) as s:
        async with s.get(SEARCH_URL, params={"bundleId": bundle, "country": "NL"}) as r:
            body = await r.json(content_type=None)
        treffers = body.get("results") or []
        if not treffers:
            return b""
        url = treffers[0].get("artworkUrl512") or treffers[0].get("artworkUrl100")
        if not url:
            return b""
        async with s.get(url) as r:
            return await r.read() if r.status == 200 else b""


def _compose(raw: bytes) -> bytes:
    from PIL import Image, ImageDraw

    source = Image.open(io.BytesIO(raw))
    # Een logo met doorzichtige achtergrond hoort op het donkere vlak te komen,
    # niet op wit. Vandaar samenvoegen in plaats van botweg omzetten.
    if source.mode in ("RGBA", "LA", "P"):
        source = source.convert("RGBA")
        onder = Image.new("RGBA", source.size, (16, 16, 20, 255))
        source = Image.alpha_composite(onder, source)
    source = source.convert("RGB")

    # Niet-vierkante logo's (de tv-app is breed) passend maken zonder uitrekken.
    if source.width != source.height:
        kant = max(source.size)
        vierkant = Image.new("RGB", (kant, kant), (16, 16, 20))
        vierkant.paste(source, ((kant - source.width) // 2, (kant - source.height) // 2))
        source = vierkant

    icon = source.resize((ICON_URL, ICON_URL), Image.LANCZOS)

    # App-iconen zijn vierkant met ronde hoeken; zonder die afronding ziet het
    # eruit als een screenshot in plaats van als een logo.
    masker = Image.new("L", (ICON_URL, ICON_URL), 0)
    ImageDraw.Draw(masker).rounded_rectangle(
        (0, 0, ICON_URL - 1, ICON_URL - 1), radius=int(ICON_URL * 0.22), fill=255)

    field = Image.new("RGB", (FIELD, FIELD), (16, 16, 20))
    field.paste(icon, ((FIELD - ICON_URL) // 2, TOP), masker)

    out = io.BytesIO()
    field.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def store_own(bundle: str, raw: bytes) -> bytes:
    """Een zelf aangeleverd logo. Gaat voor op wat de App Store levert.

    Nodig omdat Apple's eigen apps — de tv-app, Music — niet in de winkel staan
    en daar dus geen icoon te halen valt. En handig als je een logo mooier vindt
    dan het officiele.
    """
    OWN.mkdir(parents=True, exist_ok=True)
    done = _compose(raw)
    (OWN / f"{bundle}.jpg").write_bytes(done)
    (CACHE / f"{bundle}.jpg").unlink(missing_ok=True)      # oude vondst vervalt
    return done


def own_list() -> list[str]:
    return sorted(p.stem for p in OWN.glob("*.jpg")) if OWN.exists() else []


async def icon(bundle: str) -> bytes:
    """Geeft een schermvullende JPEG met het logo, of leeg als die er niet is."""
    if not bundle:
        return b""
    own = OWN / f"{bundle}.jpg"
    if own.exists():
        return own.read_bytes()

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{bundle}.jpg"
    if path.exists():
        return path.read_bytes()

    raw = await _fetch(bundle)
    if not raw:
        path.write_bytes(b"")        # ook onthouden dát er niets is
        return b""

    import asyncio
    done = await asyncio.to_thread(_compose, raw)
    path.write_bytes(done)
    return done
