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


def _rounded(raw: bytes, px: int):
    """The bare logo at `px`, square, on the dark field, with rounded corners.

    Shared by the full-screen version and the thumbnail, because the awkward
    parts are the same for both: a transparent background belongs on the dark
    field rather than on white, a non-square logo (the tv app is wide) must be
    padded and not stretched, and app icons without their rounding read as a
    screenshot instead of a logo.
    """
    from PIL import Image, ImageDraw

    source = Image.open(io.BytesIO(raw))
    if source.mode in ("RGBA", "LA", "P"):
        source = source.convert("RGBA")
        backdrop = Image.new("RGBA", source.size, (16, 16, 20, 255))
        source = Image.alpha_composite(backdrop, source)
    source = source.convert("RGB")

    if source.width != source.height:
        side = max(source.size)
        square = Image.new("RGB", (side, side), (16, 16, 20))
        square.paste(source, ((side - source.width) // 2, (side - source.height) // 2))
        source = square

    icon = source.resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, px - 1, px - 1), radius=int(px * 0.22), fill=255)
    return icon, mask


def _thumb(raw: bytes, px: int) -> bytes:
    """A logo at thumbnail size, for the launcher carousel."""
    from PIL import Image

    icon, mask = _rounded(raw, px)
    field = Image.new("RGB", (px, px), (16, 16, 20))
    field.paste(icon, (0, 0), mask)
    out = io.BytesIO()
    field.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def _compose(raw: bytes) -> bytes:
    """The logo full-screen, with room under it for the title and artist."""
    from PIL import Image

    icon, mask = _rounded(raw, ICON)
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
    # The upload itself is kept as well, because the composed version is a
    # full screen with the logo small in the middle of it — make a thumbnail of
    # *that* and you get a speck of logo in a field of dark. The thumbnail has
    # to start from the same picture this one did.
    (OWN / f"{bundle}.src").write_bytes(raw)
    (CACHE / f"{bundle}.jpg").unlink(missing_ok=True)       # the old find lapses
    for stale in CACHE.glob(f"{bundle}-*.jpg"):
        stale.unlink(missing_ok=True)
    return done


def own_list() -> list[str]:
    return sorted(p.stem for p in OWN.glob("*.jpg")) if OWN.exists() else []


async def thumb(bundle: str, px: int) -> bytes:
    """A small square logo for the launcher, or empty if there is none.

    Cached per size, because the panel asks for one size and the web interface
    may ask for another, and fetching from the store twice for the same logo is
    a request nobody needs to make.
    """
    if not bundle or px < 16 or px > 480:
        return b""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{bundle}-{px}.jpg"
    if path.exists():
        return path.read_bytes()

    own = OWN / f"{bundle}.src"
    raw = own.read_bytes() if own.exists() else await _fetch(bundle)
    if not raw:
        path.write_bytes(b"")            # remember that there is nothing, too
        return b""

    import asyncio
    done = await asyncio.to_thread(_thumb, raw, px)
    path.write_bytes(done)
    return done


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
