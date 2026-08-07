#!/usr/bin/env python3
"""
The device's ears: listens along on the receiver's own line feed and asks the
brain for a lookup as soon as something starts playing.

There is no microphone. Denon and Marantz receivers digitise their analog
inputs and offer each one as a plain HTTP stream — the mechanism behind sharing
an input with HEOS speakers — and the turntable is one of them:

    http://<receiver>:8015/analoginput/analog/analog/0/phono

Raw 16-bit stereo PCM at 44.1 kHz, realtime, one client at a time. Measured on
an SR7015: the music sits 43 dB above that input's noise floor, where a
microphone in the same room managed 13 dB. The fingerprinter is only validated
down to 20 dB, so this is the difference between working by design and working
by luck — and it hears no conversation, no doors and no traffic.

Why not on a timer — see ../PLAN.md. shazamio is an unofficial client with no
key: a handful of lookups an evening does not stand out, one a minute does. It
is also simply pointless, because a side lasts twenty minutes and does not
change its name in the meantime.

So listening happens on an event: **sound after silence**. That is exactly the
moment you put the needle down.

The threshold still follows the signal rather than being fixed: the noise floor
tracks the quiet and we trigger on a jump above it. On a line feed that floor
barely moves, but the same code covers both and costs nothing.

This service also serves the web interface: one page with tabs, in
static/index.html. It lives here rather than with the brain because the line
feed, the Apple TV and the proxy to the panel are all here; the brain supplies
only its API, passed through under /api/.

Runs as a systemd service — see vinylknob-listen.service.
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

# Artwork is resized here and not on the panel: an ESP32 scaling a 600-pixel
# JPEG costs memory and time it does not have, while the Pi does it in tens of
# milliseconds.
COVER_PX = int(os.environ.get("COVER_PX", "480"))

# -- settings, every one overridable through the environment ----------------
BRAIN        = os.environ.get("BRAIN_URL", "http://127.0.0.1:8790")
PORT        = int(os.environ.get("LISTEN_PORT", "8791"))

# Where the sound comes from. AVR_HOST is normally left empty: the panel is
# already configured with the receiver's address and hands it over, the same
# way the panel's own address is discovered rather than typed in.
#
# LINE_INPUT is the last part of the stream path, which is the protocol name in
# lower case — phono, cd, tuner, dvd, game, mediaplayer, bluray, tvaudio. Run
# ./line.sh to see what your receiver offers and which ones carry signal.
AVR_HOST    = os.environ.get("AVR_HOST", "")
LINE_INPUT  = os.environ.get("LINE_INPUT", "phono")
LINE_PORT   = int(os.environ.get("LINE_PORT", "8015"))
RATE        = int(os.environ.get("LINE_RATE", "44100"))

BLOCK_S       = 0.1                     # how often we measure the level
CLIP_S   = float(os.environ.get("CLIP_SECONDS", "8"))
SETTLE_S    = float(os.environ.get("SETTLE_SECONDS", "4"))    # let the needle settle
START_S      = float(os.environ.get("START_SECONDS", "2.5"))   # sound this long = playing
QUIET_S     = float(os.environ.get("QUIET_SECONDS", "15"))    # silence this long = side over
RETRY_S    = float(os.environ.get("RETRY_SECONDS", "60"))    # after a failed lookup

# How many times in a row we retry when nothing is recognised.
#
# Without a limit this runs for as long as there is any sound, and that is
# exactly what happened: a talking video on the Apple TV produced forty-five
# lookups in a single morning, one every seventy-five seconds, all empty.
# Retrying does help for a record — the first sample can be a quiet intro — but
# if three fail there is no record playing, and attempts four through
# twenty-five will not change that. Waiting for real silence is the right move:
# that is the signal something new can begin.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# How long the sleeve stays after it goes quiet. Deliberately much longer than
# QUIET_SECONDS: that number decides when listening may resume, and you want it
# short. Clearing the picture is a different question — with a marginal signal a
# soft passage already drops below the threshold, and then the sleeve vanishes
# while the record plays on. Five minutes of silence is genuinely over.
COVER_HOLD_S = float(os.environ.get("COVER_HOLD_SECONDS", "300"))
# How far above the noise floor counts as sound. On the line feed there is 43 dB
# of room between the floor and the music, so this can sit high enough to ignore
# hum and a needle in the run-out groove, and still fire the moment music starts.
# With a microphone it had to be 6, and that was uncomfortably close to the
# noise.
TRIGGER_DB    = float(os.environ.get("TRIGGER_DB", "15"))       # above the noise floor
# The noise floor falls quickly and rises very slowly. That is not the same as
# the tenth percentile over the last minute, and the difference matters: play a
# minute of continuous music and that music *becomes* the tenth percentile, so
# the measured margin drops to zero. Exactly why a perfectly audible record kept
# staying under the threshold.
FLOOR_RISE_DB = 0.02          # per 0.1 s block, so ~0.2 dB per second
FLOOR_QUIET_DB  = 6.0           # this close to the floor counts as "the room"

# A ceiling on the noise floor, and the whole reason it exists: the floor is
# seeded from the first block read, and a line feed gives no clue whether that
# block is silence or the middle of a chorus. Restart the service during a side
# and the floor seeds on music — after which the threshold sits above the music
# and that side never triggers a lookup. With a microphone the room noise hid
# this, because there was always something quieter than the record.
#
# The fix is to say what a line's noise floor can physically be. It is a
# property of the input, not of the room: measured between -80 and -92 dBFS on
# the receivers this has run on, while music sits around -37. A floor claiming
# to be up near the music is not a floor, it is a bad seed. Capping it costs
# nothing in the normal case, where the floor is thirty decibels below this.
FLOOR_MAX_DB = float(os.environ.get("FLOOR_MAX_DB", "-55"))

# And a floor under the whole thing: never ask about sound too quiet to
# recognise anyway.
#
# The threshold above is a *relative* one — so many decibels over whatever the
# quiet is — which is right for deciding that something started, and says
# nothing about whether there is enough there to identify. With the line idle at
# -80 or lower, that relative threshold lands around -65, and hum, a needle in
# the run-out groove or a little bleed from a neighbouring input all clear it
# comfortably. Each one is a lookup that cannot succeed: it spends a request on
# a service that owes us nothing, burns one of the three attempts, and drops
# another unknown in the queue for you to throw away by hand.
#
# Measured on this line over an evening: music runs between -33 and -48 dBFS,
# the idle input between -80 and -92. -60 sits in that gap with twelve decibels
# of room on the music side.
#
# Only the automatic path is gated. Asking by hand — the note on the panel, the
# button on the page — goes through regardless: you have decided there is
# something to hear, and the device should not argue.
MIN_LEVEL_DB = float(os.environ.get("MIN_LEVEL_DB", "-60"))

BYTES_PER_BLOCK = int(RATE * BLOCK_S) * 2       # 16-bit mono


class MonoReader:
    """The stereo stream, handed on as mono.

    Shaped like the pipe of the arecord process this replaces: the loop below
    calls readexactly() for a block of 16-bit mono and does not care where it
    comes from. The receiver sends stereo, so a block is twice as many bytes on
    the wire; the downmix happens here and nowhere else.
    """

    def __init__(self, content) -> None:
        self._content = content

    async def readexactly(self, n: int) -> bytes:
        stereo = await self._content.readexactly(n * 2)
        pairs = np.frombuffer(stereo, dtype="<i2").reshape(-1, 2).astype(np.int32)
        return ((pairs[:, 0] + pairs[:, 1]) // 2).astype("<i2").tobytes()


class LineStream:
    """One open HTTP stream from the receiver, for as long as it lasts.

    No timeout on the read: this connection is meant to stay open for hours.
    The receiver serves one client at a time, so if this service is restarted
    the old connection has to be gone before the new one is accepted — which is
    why the caller closes it in a finally.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._session: ClientSession | None = None
        self._response = None
        self.stdout: MonoReader | None = None

    async def open(self) -> "LineStream":
        self._session = ClientSession(timeout=ClientTimeout(total=None,
                                                            sock_connect=6))
        self._response = await self._session.get(self.url)
        if self._response.status != 200:
            raise RuntimeError(f"{self.url} answered {self._response.status}")
        self.stdout = MonoReader(self._response.content)
        return self

    async def close(self) -> None:
        if self._response is not None:
            self._response.close()
        if self._session is not None:
            await self._session.close()


# From here the Pi puts its fan on the highest step; throttling only starts at
# 80. Below this, warm is just warm and the screen need say nothing about it — a
# permanent temperature readout on a screen meant for album art is clutter, a
# warning when it matters is not.
HOT_C = float(os.environ.get("WARN_TEMP_C", "75"))


def pi_heat() -> dict:
    """Temperature, fan speed, and whether it is being throttled."""
    out = {"tempC": None, "fanRpm": None, "throttled": False, "hot": False}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["tempC"] = round(int(f.read()) / 1000, 1)
    except Exception:                                       # noqa: BLE001
        pass
    for file in ("/sys/class/hwmon/hwmon0/fan1_input",
                "/sys/class/hwmon/hwmon1/fan1_input",
                "/sys/class/hwmon/hwmon2/fan1_input"):
        try:
            with open(file) as f:
                out["fanRpm"] = int(f.read())
                break
        except Exception:                                   # noqa: BLE001
            continue
    try:
        with open("/sys/devices/platform/soc/soc:firmware/get_throttled") as f:
            out["throttled"] = int(f.read().strip(), 16) != 0
    except Exception:                                       # noqa: BLE001
        pass
    out["hot"] = bool(out["throttled"] or (out["tempC"] or 0) >= HOT_C)
    return out


def db(rms: float) -> float:
    return 20.0 * np.log10(max(rms, 1e-9))


def to_wav(pcm: bytes) -> bytes:
    """The brain wants a plain 16-bit WAV; arecord delivers bare PCM."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


class Ears:
    def __init__(self) -> None:
        self.floor_db = -99.0                 # tracks the quiet, not the music
        self.loud_since: float | None = None
        self.quiet_since: float | None = 0.0
        self.playing = False                    # something is on; do not ask again
        self.listening = False                 # recording or looking up right now

        # The panel says on every poll whether listening makes sense: with the
        # receiver on anything but the turntable there is nothing to recognise.
        # If that word goes stale (panel off, cable out) we listen on our own
        # again — otherwise a broken panel would take recognition down with it.
        self.panel_wants = True
        self.panel_until = 0.0

        # Is the amplifier on? A record you cannot hear is not playing, so any
        # sound in the room is by definition something else. Only block when we
        # are certain: if the panel cannot reach the receiver, "off" is a guess
        # and we keep listening.
        self.amplifier_on = True
        self.retry_at: float | None = None  # try again after a miss
        self.misses = 0                      # in a row, with no silence between

        # The last lookup that came up empty. While it stands you can point at
        # an album on the panel and link the two — right while the record is
        # still spinning, instead of working through a queue on your phone in
        # the evening. It is also the moment when the clip still belongs to the
        # sound you are hearing.
        self.open_play_id: int | None = None
        # Release ids the last lookup could not choose between. Empty in the
        # ordinary case, so nothing downstream has to think about it.
        self.choices: list[int] = []
        self.force = asyncio.Event()
        self.last = "nothing heard yet"
        self.release_id: int | None = None     # artwork from your own shelf
        self.cover_url: str | None = None       # artwork from the service, second choice
        self.artist = ""                      # separate fields, for the panel
        self.title = ""
        self.album = ""
        self.level_db = -99.0

        # How often the panel asked for /now. Purely diagnostic: it lets /status
        # show whether the panel really reaches you, without writing a log line
        # every four seconds.
        self.panel_polls = 0
        self.last_panel_ip = ""

        self.cover_cache_src = ""               # scaled sleeve, one record deep
        self.cover_cache: bytes = b""
        self.linkable = 0                       # records waiting to be linked
        self.linkable_until = 0.0                 # how long that count is valid

        # Which stream we are actually on, for /status. Filled in once the
        # connection stands, so an empty string means "not listening yet".
        self.source_url = ""

        # The clock counts audio, not wall time: every block is exactly BLOCK_S
        # of sound. That is not the same thing. If the stream stalls, or the
        # system clock jumps, the thresholds below still hold — with time.time()
        # a hiccup could skip a side or ask again in the middle of one.
        self.clock = 0.0

    # -- listening ---------------------------------------------------------
    async def open_source(self) -> LineStream | None:
        """The stream, or None while we do not yet know where to get it.

        At boot the panel has usually not polled yet, so there is no address to
        ask for. That is not a fault and should not read like one: it resolves
        itself within seconds, and saying so once beats filing an error every
        five seconds until it does.
        """
        host = await avr_host()
        if not host:
            return None
        return await LineStream(
            f"http://{host}:{LINE_PORT}/analoginput/analog/analog/0/{LINE_INPUT}"
        ).open()

    async def run(self) -> None:
        waiting = False
        while True:
            source = None
            try:
                source = await self.open_source()
                if source is None:
                    if not waiting:
                        print("[listen] waiting for the panel to say where the "
                              "receiver is", flush=True)
                        waiting = True
                    await asyncio.sleep(5)
                    continue
                waiting = False
                self.source_url = source.url
                print(f"[listen] on {source.url}", flush=True)
                await self.audio_loop(source)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                print("[listen] line feed dropped out, retrying in 5 s", flush=True)
            except Exception as e:                              # noqa: BLE001
                print(f"[listen] error: {e!r}", flush=True)
            finally:
                if source is not None:
                    await source.close()
                    self.source_url = ""
            await asyncio.sleep(5)

    def amplifier_is(self, on: bool) -> None:
        """The amplifier went on or off; act on the change, not the state.

        Switching off ends the evening, so it ends the record with it: the
        screen goes back to being a volume knob. Waiting out COVER_HOLD_S
        instead would mean switching on again half an hour later and being shown
        whatever you finished with, which reads as "this is playing" when
        nothing is.

        Only on the edge. Called every ten seconds with the same answer, and
        clearing on the state rather than the change would wipe the screen over
        and over while the amplifier is simply off.
        """
        was_on, self.amplifier_on = self.amplifier_on, on
        if was_on and not on and self.artist:
            self.forget()
            self.playing = False
            self.misses = 0
            self.retry_at = None
            print("[listen] amplifier off, cleared the screen", flush=True)

    def forget(self) -> None:
        """Nothing is playing any more: empty the screen.

        Everything that describes a record goes at once — the name, the sleeve,
        the link you could still have made, the question about which pressing it
        was. Clearing them one at a time is how they get out of step, and a
        sleeve without an artist under it looks like a bug rather than an empty
        screen.
        """
        self.release_id = None
        self.cover_url = None
        self.artist = self.title = self.album = ""
        # The open link goes with it: what you would point at now no longer
        # belongs to the sound it was recorded from.
        self.open_play_id = None
        self.choices = []

    def threshold_db(self) -> float:
        """The level sound has to clear before we ask on our own.

        Two conditions in one number: far enough above the quiet to count as
        something starting, and loud enough to be worth identifying at all. The
        page draws its marker from this, so what you see on the meter is what
        the loop actually uses.
        """
        return max(self.floor_db + TRIGGER_DB, MIN_LEVEL_DB)

    async def audio_loop(self, source) -> None:
        while True:
            block = await source.stdout.readexactly(BYTES_PER_BLOCK)
            self.clock += BLOCK_S
            mon = np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768.0
            level = db(float(np.sqrt(np.mean(mon * mon))))
            self.level_db = level

            # The floor follows the quiet, not the music. Straight down with
            # it; but up only while the level sits close to the floor, because
            # then it is the room that got louder. With music over the top the
            # floor stands still — otherwise it creeps up during a long side and
            # the margin disappears exactly where you need it.
            if self.floor_db <= -98.0:
                self.floor_db = level               # first block: start here
            elif level < self.floor_db:
                self.floor_db = level
            elif level < self.floor_db + FLOOR_QUIET_DB:
                self.floor_db += FLOOR_RISE_DB
            self.floor_db = min(self.floor_db, FLOOR_MAX_DB)

            now = self.clock
            loud = level > self.threshold_db()

            if loud:
                self.quiet_since = None
                if self.loud_since is None:
                    self.loud_since = now
            else:
                self.loud_since = None
                if self.quiet_since is None:
                    self.quiet_since = now
                # Quiet long enough: the side is over, we may ask again.
                if self.playing and now - self.quiet_since > QUIET_S:
                    self.playing = False
                    self.retry_at = None
                    # Silence draws a line under what was. What comes next is a
                    # new event and deserves a full set of attempts again.
                    self.misses = 0

                # Clear the picture much later. That keeps the sleeve up
                # through a soft passage, and drops it when the record has
                # genuinely finished.
                if self.artist and now - self.quiet_since > COVER_HOLD_S:
                    self.forget()
                    print("[listen] quiet for a long time, cleared the screen", flush=True)
                    print("[ears] quiet, ready for the next side", flush=True)

            # Asking by hand goes past every gate above: the level, the
            # threshold, the panel's opinion and the amplifier. You pressed the
            # note on the knob or the button on the page, so you have already
            # decided there is something to hear.
            asked = self.force.is_set()

            # Starting on its own is the guarded path: loud enough to be worth
            # identifying, the panel says a record is on, and the amplifier is
            # running.
            allowed = ((self.panel_wants or time.monotonic() > self.panel_until)
                   and self.amplifier_on)
            starts = (allowed
                      and self.loud_since is not None
                      and now - self.loud_since > START_S
                      and not self.playing)

            # A failed lookup: it is still playing, so somewhere further into
            # the record may well work. Waiting for silence would mean seeing
            # nothing for a whole side.
            retry = (allowed and self.retry_at is not None and now >= self.retry_at
                       and self.loud_since is not None)
            if retry:
                self.retry_at = None

            if asked or starts or retry:
                self.force.clear()
                self.listening = True
                if not asked and not retry:
                    # The needle just landed; let it settle before we sample.
                    await self.skip(source, SETTLE_S)
                pcm = await self.grab(source, CLIP_S)
                self.playing = True
                self.loud_since = None
                try:
                    await self.ask(to_wav(pcm))
                finally:
                    self.listening = False

    async def skip(self, source, seconds: float) -> None:
        n = int(seconds / BLOCK_S)
        for _ in range(n):
            await source.stdout.readexactly(BYTES_PER_BLOCK)
            self.clock += BLOCK_S

    async def grab(self, source, seconds: float) -> bytes:
        n = int(seconds / BLOCK_S)
        out = []
        for _ in range(n):
            out.append(await source.stdout.readexactly(BYTES_PER_BLOCK))
            self.clock += BLOCK_S
        return b"".join(out)

    # -- asking the brain --------------------------------------------------
    async def ask(self, wav: bytes) -> None:
        print(f"[ears] {len(wav)//1024} kB to the brain", flush=True)
        try:
            async with ClientSession(timeout=ClientTimeout(total=60)) as s:
                async with s.post(f"{BRAIN}/api/listen", data=wav,
                                  headers={"Content-Type": "audio/wav"}) as r:
                    body = await r.json()
        except Exception as e:                                  # noqa: BLE001
            self.last = f"brain unreachable: {e!r}"
            print(f"[listen] {self.last}", flush=True)
            return

        rel = body.get("release")
        hit = next((r for r in body.get("results", []) if r.get("matched")), {})

        # Only update when something was genuinely recognised. A failed lookup
        # does not mean a different record is on — it is still playing, and one
        # stretch of it happened not to match. Clearing would make the sleeve
        # vanish in the middle of a side, which is exactly what happened when
        # the retry after 60 seconds came back with nothing.
        # Records of yours this track is on, when it is on more than one. The
        # brain will not guess between them and neither will this: it is offered
        # on the panel, filtered down to just these, and you point at the one
        # that is spinning.
        self.choices = [c["id"] for c in (body.get("choices") or [])]

        if body.get("matched"):
            self.misses = 0
            # The link stays open as long as this listen has not landed on one
            # of your records. With several candidates you still have to point.
            # With none at all — the track was recognised but the album it names
            # is not on the shelf — pointing is the only way this side will ever
            # be learnt, and until now that was quietly impossible.
            self.open_play_id = None if rel else body.get("playId")
            self.release_id = rel["id"] if rel else None
            self.artist = hit.get("artist") or (rel["artist"] if rel else "")
            self.title = hit.get("title") or ""
            # With a choice open, the album and the sleeve the service handed
            # over are the very thing we decided not to trust — it named one
            # record and the song is on two of yours. Putting that sleeve on the
            # screen answers the question with the guess we just rejected, and
            # it looks settled, so nobody ever goes and picks. Name the track
            # instead and let the panel say it is asking.
            if self.choices:
                self.cover_url = None
                self.album = ""
            else:
                self.cover_url = hit.get("cover") or None
                self.album = (rel["title"] if rel else "") or hit.get("album") or ""

        if body.get("matched") and rel:
            self.last = f"{rel['artist']} — {rel['title']}"
        elif body.get("matched") and self.choices:
            self.last = (f"{hit.get('artist','?')} — {hit.get('title','?')} "
                            f"(on {len(self.choices)} of your records — pick one)")
        elif body.get("matched"):
            self.last = (f"{hit.get('artist','?')} — "
                            f"{hit.get('title','?')} (not on the shelf)")
        else:
            self.open_play_id = body.get("playId")
            self.misses += 1
            if self.misses < MAX_RETRIES:
                self.last = "unknown, put in the queue"
                self.retry_at = self.clock + RETRY_S
            else:
                self.last = (f"{self.misses}x nothing recognised — "
                                "waiting for silence")
                self.retry_at = None
        print(f"[listen] {self.last}", flush=True)


ears = Ears()
atv = AppleTV()


async def api_listen_now(_request):
    """Listen right now, whatever the threshold thinks."""
    ears.force.set()
    return web.json_response({"ok": True})


HERE = pathlib.Path(__file__).parent


async def index(_request):
    """The whole web interface: one page with tabs.

    It sits as a file next to this code rather than as a string inside it,
    because it is hundreds of lines of HTML and CSS and that does not belong in
    the middle of the listening logic.

    The page itself fetches three things from the same address: /status and the
    Apple TV from this service, /api/* from the brain, and /panel/* from the
    panel. How that works is in the forwarding helper below.
    """
    return web.FileResponse(HERE / "static" / "index.html")


async def count_linkable() -> int:
    """How many records are waiting for you.

    Both kinds: nothing recognised it, or the track is on more than one of your
    records and only you can say which.

    Cached for half a minute, because the panel asks every four seconds and the
    queue changes a couple of times an evening at most.
    """
    if time.monotonic() < ears.linkable_until:
        return ears.linkable
    try:
        async with ClientSession(timeout=ClientTimeout(total=5)) as s:
            async with s.get(f"{BRAIN}/api/plays?status=unknown,choose&limit=99") as r:
                body = await r.json()
        ears.linkable = len(body.get("plays", []))
    except Exception:                                       # noqa: BLE001
        pass                                                # keep the old count
    ears.linkable_until = time.monotonic() + 30
    return ears.linkable


def _shrink_bytes(data: bytes, px: int | None = None) -> bytes:
    """Crop to a square and bring it down to px (COVER_PX by default)."""
    from PIL import Image
    px = px or COVER_PX
    image = Image.open(io.BytesIO(data)).convert("RGB")
    side = min(image.size)
    left = (image.width - side) // 2
    above = (image.height - side) // 2
    image = image.crop((left, above, left + side, above + side))
    image = image.resize((px, px), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


async def api_now(request):
    """What is playing, in the shortest possible form — for the panel.

    Deliberately separate from /status: that one is for people and full of dB
    values, this is what a microcontroller with 480x480 pixels needs and nothing
    more. Short keys and flat text, so the ESP32 can read it with a small JSON
    buffer.
    """
    # Only count what comes from the panel, which you can tell by `listen`:
    # only the panel sends that parameter (see brain.cpp). Since the web
    # interface started using this endpoint too — to show exactly what is on the
    # screen — counting those would muddy the diagnostic: "panel polls" would
    # then say as much about your phone as about the panel.
    if "listen" in request.query:
        ears.panel_polls += 1
        ears.last_panel_ip = request.remote or "?"
        ears.panel_wants = request.query["listen"] not in ("0", "false", "nee")
        ears.panel_until = time.monotonic() + 60

    # With the receiver on anything but the turntable, the Apple TV is the
    # source — if it is paired and playing something. That beats listening in:
    # the device *knows* what it is doing, artwork included.
    # Report it even when nothing is playing but an app is open: that the Apple
    # TV is sitting on YouTube is information in itself, and the alternative is
    # falling back to the turntable's line, which has no business there.
    if not ears.panel_wants and atv.device is not None and (
            atv.artist or atv.title or atv.app_id):
        return web.json_response({
            "linkable": await count_linkable(),
            "artist": atv.artist,
            "title": atv.title,
            "album": atv.album or atv.title,
            "artwork": bool(atv.artwork) or bool(await appicon.icon(atv.app_id)),
            # A logo is not artwork but a stand-in: the panel hides text behind
            # real artwork, but with a logo the title belongs on screen —
            # otherwise you see a brand and not what is playing.
            "logo": not atv.artwork and bool(await appicon.icon(atv.app_id)),
            "onShelf": False,
            "playing": atv.playing_now,
            "listening": False,
            "source": "appletv",
            "app": atv.app,
            "hot": pi_heat()["hot"],
        })
    return web.json_response({
        "linkable": await count_linkable(),
        "artist": ears.artist,
        "title": ears.title,
        "album": ears.album,
        "artwork": bool(ears.release_id or ears.cover_url),   # is there anything on /artwork
        "onShelf": ears.release_id is not None,  # found in your own collection
        "playing": ears.playing,
        "listening": ears.listening,
        # Is there an open lookup that came up empty? Then you can point at an
        # album on the panel and hang it on that.
        "canLink": ears.open_play_id is not None,
        # When the track is on more than one of your records: which ones. The
        # panel narrows the shelf to these instead of offering all of them.
        "choices": ears.choices,
        "hot": pi_heat()["hot"],
    })


async def api_cover(_request):
    """Artwork, passed through from the brain.

    This way the panel only has to know one address. It fetches here rather than
    from the brain directly, which saves a second port in its settings and a
    second place where something can break.
    """
    # Your own shelf first, then whatever the service supplied. That second one
    # is not an afterthought: anything you do *not* own on vinyl — radio,
    # streaming, someone else's record — only gets artwork that way.
    # The Apple TV takes priority while the turntable is not the source, and
    # then exclusively. Falling through to the record path served the previous
    # LP's sleeve for a YouTube video with no image, which is worse than none.
    if not ears.panel_wants and atv.device is not None:
        if atv.artwork:
            small = await asyncio.to_thread(_shrink_bytes, atv.artwork)
            return web.Response(body=small, content_type="image/jpeg")
        # No image for this title — YouTube does not supply one. Fall back to
        # the app's logo, fetched from Apple's own search endpoint.
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

    # Crop square and scale to COVER_PX. The panel then decodes one-to-one into
    # a buffer it can reserve in advance.
    small = await asyncio.to_thread(_shrink_bytes, raw)
    ears.cover_cache_src, ears.cover_cache = source, small
    return web.Response(body=small, content_type="image/jpeg")


# -- the record shelf, for the panel ----------------------------------------
#
# The panel has eight megabytes of PSRAM and a collection can run to hundreds of
# albums. The artwork does not fit — one 480-pixel sleeve is already 460 kB —
# but the names do. So the panel gets the list in one go and the pictures one at
# a time, and only for the three actually on screen.
#
# The list goes as flat text rather than JSON: an ESP32 parsing 40 kB of JSON
# spends seconds on it, while splitting lines on a tab costs almost nothing. One
# line per album, sorted by artist the way the brain already
# sorteert.
SHELF_PX = int(os.environ.get("SHELF_PX", "138"))
SHELF_CACHE = HERE.parent / "brain" / "data" / "shelfcovers"


async def api_shelf(_request):
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            async with s.get(f"{BRAIN}/api/collection?q=&limit=5000") as r:
                body = await r.json()
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"brain not reachable: {e!r}")

    lines = []
    for rel in body.get("releases", []):
        # Strip tabs out of the values, or the splitting goes wrong.
        artist = (rel.get("artist") or "").replace("\t", " ").strip()
        title = (rel.get("title") or "").replace("\t", " ").strip()
        lines.append(f"{rel['id']}\t{artist}\t{title}")
    return web.Response(text="\n".join(lines), content_type="text/plain")


async def api_link(request):
    """Link the album you pointed at on the panel to whatever is playing.

    This is the queue, but at the right moment. Normally you link a clip to a
    half-remembered record with your phone in the evening; this way you do it
    with the needle still down and the sleeve in your hand.

    The brain does the real work: linking, and recording the saved clip as
    fingerprints against that release. That makes the same side recognisable
    locally next time, with no service involved — precisely the lesson only you
    could teach it.
    """
    if ears.open_play_id is None:
        return web.json_response({"ok": False, "error": "nothing to link"},
                                 status=409)
    try:
        rel_id = int(request.query.get("id", ""))
    except ValueError:
        return web.json_response({"ok": False, "error": "no id"}, status=400)

    play_id = ears.open_play_id
    try:
        async with ClientSession(timeout=ClientTimeout(total=30)) as s:
            # Check the album exists before linking, not after. The other way
            # round, a wrong number would hang a listen on nothing — and worse,
            # store the clip as fingerprints against a release that does not
            # exist. A link is permanent; you do not make one on good
            # faith.
            async with s.get(f"{BRAIN}/api/collection?q=&limit=5000") as r:
                releases = (await r.json()).get("releases", [])
            rel = next((x for x in releases if x["id"] == rel_id), None)
            if rel is None:
                return web.json_response(
                    {"ok": False, "error": f"album {rel_id} does not exist"}, status=404)

            async with s.post(f"{BRAIN}/api/plays/{play_id}/link",
                              json={"releaseId": rel_id}) as r:
                out = await r.json()
    except Exception as e:                                  # noqa: BLE001
        return web.json_response({"ok": False, "error": f"{e!r}"}, status=502)

    ears.release_id = rel_id
    ears.cover_url = None
    ears.artist = rel["artist"]
    ears.title = rel["title"]
    ears.album = rel["title"]
    ears.last = f"{rel['artist']} — {rel['title']} (linked by hand)"
    ears.cover_cache_src, ears.cover_cache = "", b""
    ears.open_play_id = None
    ears.choices = []            # the question is answered
    ears.linkable_until = 0.0                    # fetch the count again

    print(f"[listen] {ears.last}, {out.get('hashes', 0)} fingerprints",
          flush=True)
    return web.json_response({"ok": True, "hashes": out.get("hashes", 0),
                              "artist": ears.artist, "title": ears.title})


async def api_shelf_cover(request):
    """One sleeve, small enough for the panel to decode.

    Scaling on the ESP32 would cost memory and time it does not have, and here
    it is a matter of milliseconds — the same trade-off as /artwork.
    """
    try:
        rel_id = int(request.query.get("id", ""))
        # Up to 480, because picking an album in the shelf brings that same
        # sleeve back full-screen on the volume view.
        px = min(int(request.query.get("px", SHELF_PX)), 480)
    except ValueError:
        raise web.HTTPBadRequest(text="id and px must be numbers")

    SHELF_CACHE.mkdir(parents=True, exist_ok=True)
    file = SHELF_CACHE / f"{rel_id}-{px}.jpg"
    if file.exists():
        return web.FileResponse(file)

    try:
        async with ClientSession(timeout=ClientTimeout(total=20)) as s:
            async with s.get(f"{BRAIN}/api/cover/{rel_id}") as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                raw = await r.read()
    except web.HTTPException:
        raise
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"fetching the sleeve failed: {e!r}")

    small = await asyncio.to_thread(_shrink_bytes, raw, px)
    file.write_bytes(small)
    return web.Response(body=small, content_type="image/jpeg")


# Where the panel lives.
#
# You should not have to configure this. The panel polls /now every four seconds
# and every one of those requests carries its address, so the Pi simply
# remembers who called. Setting PANEL_HOST overrides that — useful if you have
# two panels, or if you want to reach one that is not polling yet.
#
# The alternative was asking for an IP during setup, which is a poor question:
# at that moment the panel usually has no network yet, so you would be typing
# an address that does not exist.
PANEL = os.environ.get("PANEL_HOST", "")


def panel_host() -> str:
    return PANEL or ears.last_panel_ip


_avr_host_seen = ""


async def avr_host() -> str:
    """The receiver's address, asked of the panel rather than configured.

    The panel already has it — it needs it for telnet — so making you type it a
    second time here is a way of letting the two drift apart. AVR_HOST
    overrides, for the case where this service runs somewhere the panel cannot
    be reached.

    Cached once found: the address of a receiver does not change while the
    music is playing, and the audio loop reopens this on every reconnect.
    """
    global _avr_host_seen
    if AVR_HOST:
        return AVR_HOST
    if _avr_host_seen:
        return _avr_host_seen
    host = panel_host()
    if not host:
        return ""
    try:
        async with ClientSession(timeout=ClientTimeout(total=4)) as s:
            async with s.get(f"http://{host}/api/settings") as r:
                _avr_host_seen = (await r.json()).get("avrHost", "") or ""
    except Exception:                                       # noqa: BLE001
        return ""
    return _avr_host_seen


async def _forward(request, target: str, what: str):
    """Pass a request through unchanged and hand back the answer.

    This is what puts the whole web interface on one address while the three
    parts stay where they belong: the queue and the collection in the brain, the
    settings on the panel itself, the listening here. The browser sees none of
    it, and that is the point — otherwise you would be carrying three port
    numbers around in your head.

    Note: Content-Type goes along exactly as it arrived. When adding a record by
    hand that is multipart *with* its boundary, and dropping it makes the form
    unreadable at the other end.
    """
    if request.query_string:
        target += "?" + request.query_string

    body = await request.read() if request.method != "GET" else None
    headers = {}
    if request.headers.get("Content-Type"):
        headers["Content-Type"] = request.headers["Content-Type"]

    try:
        async with ClientSession(timeout=ClientTimeout(total=60)) as s:
            async with s.request(request.method, target, data=body, headers=headers) as r:
                raw = await r.read()
                return web.Response(body=raw, status=r.status,
                                    content_type=r.content_type)
    except Exception as e:                                  # noqa: BLE001
        raise web.HTTPBadGateway(text=f"{what} not reachable: {e!r}")


async def brain_proxy(request):
    """/api/* belongs to the brain, one port along on the same Pi."""
    return await _forward(request, f"{BRAIN}/api/{request.match_info['tail']}",
                           "brain")


async def panel_proxy(request):
    """Pass the panel through.

    The panel's own page uses relative paths, so hanging it under /panel/ works
    without rewriting anything — both for the panel's own page and for the
    rebuilt version in the tabs here.
    """
    host = panel_host()
    if not host:
        raise web.HTTPServiceUnavailable(
            text="the panel has not been seen yet; it announces itself as soon "
                 "as it polls this Pi")
    return await _forward(request,
                           f"http://{host}/{request.match_info.get('tail', '')}",
                           "panel")


async def panel_root(request):
    # Without the trailing slash the relative paths do not resolve.
    if not request.path.endswith("/"):
        raise web.HTTPFound(request.path + "/")
    return await panel_proxy(request)


# -- Apple TV ---------------------------------------------------------------
async def atv_scan(_request):
    return web.json_response({"devices": await atv.scan()})


async def atv_pair(request):
    body = await request.json()
    return web.json_response(await atv.pair_start(body.get("id", "")))


async def atv_pin(request):
    body = await request.json()
    return web.json_response(await atv.pair_pin(str(body.get("pin", ""))))


async def atv_forget(_request):
    await atv.forget()
    return web.json_response({"ok": True})


async def atv_power(request):
    on = request.query.get("on", "1") not in ("0", "false", "no")
    return web.json_response(await atv.set_power(on))


async def atv_status(_request):
    g = atv.paired()
    return web.json_response({
        "paired": bool(g),
        "name": (g or {}).get("name", ""),
        "connected": atv.device is not None,
        "playing": atv.playing_now,
        "artist": atv.artist,
        "title": atv.title,
        "album": atv.album,
        "artwork": bool(atv.artwork),
        "artworkBytes": len(atv.artwork),
        "app": atv.app,
        "appId": atv.app_id,
        "error": atv.error,
        # How old this information is. Without it, a frozen connection looks
        # exactly like an Apple TV that has been playing the same video for an
        # hour — and that is the difference you want to be able to see.
        "ageSeconds": (round(time.monotonic() - atv.last_update)
                     if atv.last_update else None),
    })


async def api_status(_request):
    return web.json_response({
        "levelDb": round(ears.level_db, 1),
        "floorDb": round(ears.floor_db, 1),
        "thresholdDb": round(ears.threshold_db(), 1),
        "minLevelDb": MIN_LEVEL_DB,
        "playing": ears.playing,
        "listening": ears.listening,
        "last": ears.last,
        "releaseId": ears.release_id,
        "coverUrl": ears.cover_url,
        "source": ears.source_url,
        "sourceInput": LINE_INPUT,
        "listeningAllowed": ((ears.panel_wants or time.monotonic() > ears.panel_until)
                                and ears.amplifier_on),
        "amplifierOn": ears.amplifier_on,
        "misses": ears.misses,
        "maxRetries": MAX_RETRIES,
        "pi": pi_heat(),
        "panelPolls": ears.panel_polls,
        "panelFrom": ears.last_panel_ip,
    })


async def watch_amplifier() -> None:
    """Track whether the amplifier is on, away from the audio loop.

    Separate, and not inside audio_loop(): that reads a block every tenth of a
    second and no network request belongs in between. Ten seconds is ample —
    nobody
    switches the amplifier on and off between two sides.
    """
    while True:
        host = panel_host()
        if host:
            try:
                async with ClientSession(timeout=ClientTimeout(total=4)) as s:
                    async with s.get(f"http://{host}/api/state") as r:
                        st = await r.json()
                # Only shut the gate when we are sure: no connection to the
                # receiver means the panel does not know either.
                ears.amplifier_is(not (st.get("connected") and
                                       not st.get("powered")))
            except Exception:                                   # noqa: BLE001
                ears.amplifier_on = True      # panel gone: do not guess
        await asyncio.sleep(10)


async def start(app):
    app["ears"] = asyncio.create_task(ears.run())
    app["avr"] = asyncio.create_task(watch_amplifier())
    if atv.paired():
        app["atv"] = asyncio.create_task(atv.connect())
        app["atv_watch"] = asyncio.create_task(atv.watch())


async def stop(app):
    for name in ("ears", "avr", "atv_watch"):
        if name in app:
            app[name].cancel()


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/listen", api_listen_now)
    app.router.add_get("/status", api_status)
    app.router.add_get("/now", api_now)
    app.router.add_get("/artwork", api_cover)
    app.router.add_get("/shelf", api_shelf)
    app.router.add_get("/shelfcover", api_shelf_cover)
    app.router.add_post("/link", api_link)
    app.router.add_get("/appletv/scan", atv_scan)
    app.router.add_get("/appletv/status", atv_status)
    app.router.add_post("/appletv/pair", atv_pair)
    app.router.add_post("/appletv/pin", atv_pin)
    app.router.add_post("/appletv/forget", atv_forget)
    app.router.add_post("/appletv/power", atv_power)

    # The two forwarding routes. They come last because they end in a wildcard
    # that would otherwise swallow the fixed routes above.
    app.router.add_route("*", "/api/{tail:.*}", brain_proxy)
    app.router.add_route("*", "/panel", panel_root)
    app.router.add_route("*", "/panel/{tail:.*}", panel_proxy)

    app.on_startup.append(start)
    app.on_cleanup.append(stop)

    async def serve():
        # One application on two ports, not two applications. Port 80 used to
        # be a little portal with three links to the other pages; now that there
        # is only one page, that middle step is gone and the same interface
        # simply listens on both.
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        where = AVR_HOST or "the receiver the panel knows"
        print(f"[ears] line input {LINE_INPUT} on {where}, brain at {BRAIN}, "
              f"panel {PANEL or 'auto'}, port {PORT}", flush=True)

        # Port 80 is a bonus: if it fails (no permission) the rest keeps
        # running rather than the service falling over.
        try:
            await web.TCPSite(runner, "0.0.0.0", 80).start()
            print("[ears] also on port 80", flush=True)
        except Exception as e:                              # noqa: BLE001
            print(f"[ears] no port 80: {e!r}", flush=True)

        await asyncio.Event().wait()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
