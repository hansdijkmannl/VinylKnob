"""
The icon of whichever app is running on the Apple TV.

A YouTube video comes with no image — that app supplies none. An empty screen is
a waste, and the app name in letters is half as recognisable as the logo you
know. Apple has a public search endpoint for exactly this: give it the bundle
identifier and you get the App Store icon back, no key required.

What comes back is a square icon, not a full-bleed sleeve. So it is placed on a
dark field with room around it: that way it sits alongside the real artwork
rather than looking like a blown-up postage stamp.

Apple's own apps are not in the store and return nothing. There the name stays
on screen, which is exactly right.
"""

from __future__ import annotations

import io
import pathlib

from aiohttp import ClientSession, ClientTimeout

CACHE = pathlib.Path(__file__).parent.parent / "brain" / "data" / "appicons"
OWN = CACHE / "own"
SEARCH_URL = "https://itunes.apple.com/lookup"

FIELD = 480          # same size as a sleeve, so the panel need know nothing
ICON = 130         # the logo itself; the rest is air and room for text

# The logo sits near the top rather than centred: the title and artist go below
# it and want that room. On a round screen there is still over 300 pixels of
# width at this height, so the logo does not fall off the edge.
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
    # A logo with a transparent background belongs on the dark field, not on
    # white. Hence compositing rather than a blunt convert.
    if source.mode in ("RGBA", "LA", "P"):
        source = source.convert("RGBA")
        backdrop = Image.new("RGBA", source.size, (16, 16, 20, 255))
        source = Image.alpha_composite(backdrop, source)
    source = source.convert("RGB")

    # Fit non-square logos (the tv app is wide) without stretching them.
    if source.width != source.height:
        side = max(source.size)
        square = Image.new("RGB", (side, side), (16, 16, 20))
        square.paste(source, ((side - source.width) // 2, (side - source.height) // 2))
        source = square

    icon = source.resize((ICON, ICON), Image.LANCZOS)

    # App icons are square with rounded corners; without that rounding it looks
    # like a screenshot rather than a logo.
    mask = Image.new("L", (ICON, ICON), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, ICON - 1, ICON - 1), radius=int(ICON * 0.22), fill=255)

    field = Image.new("RGB", (FIELD, FIELD), (16, 16, 20))
    field.paste(icon, ((FIELD - ICON) // 2, TOP), mask)

    out = io.BytesIO()
    field.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def store_own(bundle: str, raw: bytes) -> bytes:
    """A logo you supplied yourself. Takes priority over the App Store.

    Needed because Apple's own apps — the tv app, Music — are not in the store,
    so there is no icon to fetch. Also handy when you prefer a logo to the
    official one.
    """
    OWN.mkdir(parents=True, exist_ok=True)
    done = _compose(raw)
    (OWN / f"{bundle}.jpg").write_bytes(done)
    (CACHE / f"{bundle}.jpg").unlink(missing_ok=True)       # the old find lapses
    return done


def own_list() -> list[str]:
    return sorted(p.stem for p in OWN.glob("*.jpg")) if OWN.exists() else []


async def icon(bundle: str) -> bytes:
    """Returns a full-screen JPEG with the logo, or empty if there is none."""
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
        path.write_bytes(b"")        # remember that there is nothing, too
        return b""

    import asyncio
    done = await asyncio.to_thread(_compose, raw)
    path.write_bytes(done)
    return done
