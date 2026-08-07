# Version 2 — the order it was built in

A round touchscreen with a knob, for a Marantz SR7015. The design analysis is in
[../docs/version-2.md](../docs/version-2.md), the parts in [BOM.md](BOM.md).

## The architecture

**Route C**: an off-the-shelf CrowPanel for the controls, with a bare Raspberry
Pi next to it as the brain.

| Does | What |
|---|---|
| **Elecrow CrowPanel 2.1"** | screen, knob, touch, telnet to the AVR, all of the controls. ESP32-S3, LVGL, on instantly |
| **Raspberry Pi, headless** | microphone, shazamio, local fingerprint database, Discogs, the web interface with the linking queue |

They talk over the network, or over the CrowPanel's UART connector.

Why this works out better than a Pi with a HyperPixel: **the Pi does not have to
drive a screen.** That removes the GPIO problem of a DPI display, the second
microcontroller for the encoder, and the wait for Linux to boot — the CrowPanel
is on instantly and the Pi starts up in the background. And because the 40-pin
header is free, the microphone can be a raw I2S MEMS part instead of a USB
dongle with hidden noise suppression.

About €100, and there is no mechanical precision part left in it.

---

## Phase 0 — Prove recognition ✅

**Done.** [recognizer/](recognizer/): own fingerprinting in Python, faultless
down to 20 dB SNR with a speed deviation, limits around 100 sides.

Left here: the index in memory (a factor of 20-50 in search time), and testing
on real needle recordings instead of synthetic ones.

## Phase 0b — Recognition with a microphone ✅

**Done and successful.** [webtest/](webtest/) recognised nearly everything in 8
seconds on 31 July 2026, from an iPhone speaker through a MacBook's microphone,
sleeve included.

Consequence: the own fingerprint database from phase 0 drops from main mechanism
to **cache**, growing only where Shazam falls short.

The condition that comes with it: **do not ask on a timer but on an event** (the
input goes to phono, or sound starts after silence). shazamio is an unofficial
client without a key; a handful of lookups an evening is unobtrusive, hundreds
are not.

## Phase 1 — Order the CrowPanel and feel it ✅

Arrived and in use. The knob has detents; with acceleration on top (0.5 dB
gently, 4.0 dB turning through) that has turned out not to matter in practice,
so the custom ring is not needed.

## Phase 1b — Interface mockup ✅

**Done.** [mockup/](mockup/) is a working sketch of the four screens and the
control model, openable in your browser. It serves as the reference while
writing the LVGL firmware.

The heart of the model: with rotation, press *and* touch, nothing has to be
modal. **Turning is always volume**, on every screen. Everything you want to do
without looking is on the knob (mute, favourite, on/off); everything you look at
the screen for anyway is on the screen (input, record shelf).

## Phase 2 — The CrowPanel as the controls ✅

**Finished and tested on hardware, 1 August 2026.** Working: screen, touch,
volume on the knob, mute, on/off, the input list and telnet to the SR7015.
17.5% flash, 29.9% RAM. See [crowpanel/](crowpanel/).

Four things only became apparent with the panel on the table:

- **A boot loop** caused by `board_build.flash_size`, which does nothing — the
  bootloader reads `board_upload.flash_size`. See the appendix in
  [BUILD.md](BUILD.md).
- **`lv_label_set_text_fmt` cannot do `%f`.** LVGL's own printf leaves floating
  point out by default, so the screen literally read `f`.
- **The encoder counts the other way round** from version 1's (`ENC_INVERT`),
  and one detent is exactly one step. 0.5 dB gently, 4.0 dB fast.
- **The 250 ms delay on an input choice had to go, in fact.** In version 1
  turning *was* the choice; here there is a list and a confirmation, and sending
  while browsing dragged you through every input on the way.

And one thing that was not the firmware's fault: a Marantz ignores `SI` commands
for sources set to `DEL`. `SSSOD ?` asks which those are.

The driver stood here for a long time as the one thing that could only be
written with the hardware on the table. That turned out to be half true. From
Elecrow's own repository:

- the ST7701 initialisation sequence is **not** panel-specific but simply
  `st7701_type5_init_operations` from Arduino_GFX, and their bundled copy is
  byte for byte upstream **v1.3.1** (newer versions have a rewritten API *and* a
  different BGR bit, so that tag is pinned);
- the touch chip is a **CST826** at `0x15`;
- what really could not be guessed is the **start-up order** — the LCD and the
  touch chip both hang off the PCF8574 and each want their own reset pulse
  before `gfx->begin()`. That now lives in `board.cpp`.

`ui_serial.cpp` stays as a second environment: the same firmware with the serial
monitor as the screen, to follow the controls without the panel in the way.

## Phase 3 — The plinth

A printed plinth for the CrowPanel to stand on, with the Pi and the microphone
inside. No gears, no bearing, no precision work left — but it does need
**weight**: the CrowPanel weighs 80 grams and otherwise slides across your table
when you turn the knob. A cavity for ~300 g of ballast, four anti-slip feet
underneath, and an acoustic opening for the microphone.

## Phase 4 — The Pi as the brain ✅

**Running, 1 August 2026.** Raspberry Pi 5 (Debian 13 trixie), both services
active and enabled. The full chain tested: microphone → threshold → Shazam →
link to the collection, without the Mac.

Three things that only surfaced on the real Pi:

- **Pi OS is Debian 13 now, with Python 3.13**, and there `audioop` has been
  removed from the standard library while pydub — which shazamio leans on —
  imports it in three files. `audioop-lts` fixes that; the installer now adds it
  and then checks that `import shazamio` really works.
- **ffmpeg was missing**, and that fails silently: shazamio has pydub convert
  the recording, and without ffmpeg everything landed unrecognised in the queue
  without anything looking like an error. It is in the package list now.
- **The USB lavalier microphone has no AGC**, and that is now measured rather
  than hoped: the noise floor stayed firmly at −53 dB while the signal moved
  between −32 and −53. With automatic gain that floor would have crept along.

What stands apart from that: the signal only comes 10 to 20 dB above the noise
floor — the bottom end of what the fingerprinter has been tested at. Enough for
now, but `Mic Capture Volume` (80% at the moment) is the knob if it disappoints.

**Original design, unchanged:** see [pi/](pi/): an install script for a fresh
Raspberry Pi OS Lite 64-bit, two systemd services, and a listener on the USB
lavalier microphone.

Nothing was changed in [brain/](brain/) — that stays the test bed on the Mac.
`pi/web.py` only intercepts the bind choice so that the web interface is
reachable from your phone.

Listening happens **on an event, not on a timer**: sound after silence, with a
threshold that follows the room (the quietest ten per cent of the past minute is
the noise floor, trigger at 12 dB above it). That works without the Pi having to
know anything about the amplifier, and that is a necessity: the SR7015 allows
only one telnet session and it belongs to the CrowPanel.

One thing that came up while trying it and would have been easy to get wrong:
the thresholds run on a **clock that counts audio, not wall time**. With
`time.time()` a hiccup in `arecord` can skip a side, or ask again in the middle
of a record.

The reference recordings then automatically run through the same microphone in
the same place, so room acoustics and speaker colouration cancel out.

## Phase 5 — Panel and Pi joined up ✅

**Working since 2 August 2026.** The panel fetches what is playing from the Pi
every four seconds, shows artist and album, and the sleeve with it.

The choice that decided the most: **HTTP over Wi-Fi, not serial.** The USB cable
does carry a serial connection (`/dev/ttyACM0`, verified), but using it would
need a protocol of its own with framing, a serial client on the Pi, and giving
up the monitor this panel is followed with. The panel is on Wi-Fi already — it
has to be, for telnet — and the Pi already serves HTTP. One GET is enough.

| | |
|---|---|
| `GET /now` | artist, album, whether a sleeve is waiting, how much there is to link |
| `GET /artwork` | the sleeve, brought down to 240×240 by the Pi (~9 kB) |
| `POST /listen` | the panel asks for a lookup |

Three things that stood out:

- **The Pi scales the sleeve, not the panel.** An ESP32 that has to shrink a
  600-pixel JPEG costs memory and time it does not have; the Pi does it in tens
  of milliseconds with Pillow, and the panel decodes one to one into a buffer it
  can reserve in advance.
- **The QR code does not impose itself.** There is a dot on the volume screen
  when there is something to link; tapping the sleeve takes you to the code. A
  screen that pushes itself forward while you are turning the volume knob is
  exactly what you do not want.
- **The panel provokes a lookup** as soon as the input goes to your favourite.
  That is the moment you put the needle down, and it saves the Pi waiting until
  it hears it itself.

A by-product: [crowpanel/flash-via-pi.sh](crowpanel/flash-via-pi.sh) flashes the
panel over the network through the Pi. The cable no longer has to travel back
and forth, because esptool puts the S3 into the bootloader itself over its
native USB.

## Phase 5b — The queue and the web interface ✅

**Running on the Pi.** See [brain/](brain/): listening with the own database
first and only then a service, both engines side by side, syncing and searching
the Discogs collection, the linking queue with audio clips, entering something
by hand with your own sleeve, and a "that is wrong" button. The same code later
runs on the Pi; the recording then comes from the USB microphone instead of the
browser.

What still has to happen: the QR code on the CrowPanel's screen, and the
endpoint the panel asks for a lookup with.

Unrecognised sides land in a queue with their audio clip. In the web interface
you link those to a Discogs release, or upload a sleeve yourself; after that the
device recognises them on its own, without a service. That way the local
database grows precisely where Shazam falls short.

When a lookup fails, the Pi keeps listening for another 60-90 seconds. Eight
seconds is enough to *ask* with, but too little as a reference of your own: that
covers eight seconds of a twenty-minute side.

Getting to that web interface: a **QR code on the screen** with the address
below it in plain digits. It appears the moment there is something to link — and
that is exactly the moment you reach for your phone.

## Phase 6 — The collection browser ✅

Three sleeves in a row, the knob as the position, the jump index as a ring of
letters along the inner rim. Tap the sleeve to get in; turning browses, turning
while held jumps by letter, and a press picks the album you are on.

There is a **BACK** button in the gap of the letter ring, because pressing the
knob in here is the *choose* gesture and with an unrecognised record playing
that press writes a fingerprint you cannot unwrite. Leaving without choosing
should not depend on knowing that the screen falls back on its own after
eighteen seconds.

**Choosing does two things, depending on what is playing.**

If a record is playing that was not recognised, choosing is a **link**. The
brain hangs your choice on that listen *and* enrols the stored clip as a
fingerprint, after which the same side is recognised locally from then on
without a service. That is exactly the lesson only you can teach, and this is
the moment you can teach it: with the needle still down and the sleeve in your
hand, instead of working through a queue on your phone in the evening. The head
of the screen then reads **LINK TO WHAT IS PLAYING**, because you ought to know
you are recording something.

If nothing particular is playing, choosing is only "show me": the sleeve comes
back filling the screen. Putting it on is not something this device can do. That
choice stands until the brain reports something else — put a record on shortly
after and recognition wins. What sounds is truth, what you pointed at was a
choice.

For that the Pi keeps track of which lookup is still open (`open_play_id`). It
expires on a successful recognition and after five minutes of silence, because
by then what you point at no longer belongs to what you heard. Linking only
happens to an album that really is on the shelf: a link is permanent and fixes a
fingerprint, so you do not make one on trust.

While jumping by letter that letter comes up large on screen, in Montserrat at
130 pixels. A font was generated for it (`font_shelf_letter.c`, only A-Z and
`#`, 52 kB of flash): LVGL supplies Montserrat up to 48 px and on a 480-pixel
screen that is too small to read while turning. The ring stays small — that
shows *where* you are, the large letter where you are going.

The division is the same as everywhere: the Pi knows, the panel shows. The names
arrive in one go through `/shelf` — 25 kB of flat text, because parsing 40 kB of
JSON costs an ESP32 seconds and splitting lines on a tab almost nothing. The
sleeves come one at a time through `/shelfcover`, made to size by the Pi, and
only for the three on screen; nine fit in memory so that turning back and forth
over the same spot costs nothing.

Fetching never happens while you are turning: the text moves with you at once,
the sleeves follow when you hold still for two hundred milliseconds. A knob that
waits on the network every step feels broken, even when nothing is wrong.

All three sleeves are the same size. That saves work: were the middle one
larger, one step would need three new pictures instead of one. Which is the
current one you can see from the border around it and the title underneath.

Since the sleeve leads to the shelf, the QR code for linking has been given a
touch area of its own around the dot — you do not hit ten pixels with a finger.

## Phase 7 — The microphone out ✅

**6 August 2026.** There is no microphone any more. Denon and Marantz receivers
digitise their analog inputs and serve each one as a plain HTTP stream — the
machinery behind sharing an input with HEOS speakers — so the ears read the
turntable straight off the phono stage:

```
http://<receiver>:8015/analoginput/analog/analog/0/phono
```

Raw 16-bit stereo PCM at 44.1 kHz, realtime, one client at a time. Measured on
the SR7015 with one record, both paths within the same minute:

| | line feed | microphone |
|---|---|---|
| signal | −36.7 dBFS | −42.0 dBFS |
| its own noise floor | −80 dBFS | −54.7 dBFS |
| **room above the floor** | **43 dB** | **13 dB** |

Phase 0 established that the fingerprinter is faultless down to 20 dB. The
microphone was working *below* that the whole time.

Two things had to be checked before this was worth doing, and both came out
well:

- **The existing fingerprints survive.** Twenty-five seconds of line and
  twenty-five of microphone, recorded simultaneously and matched against each
  other in a scratch database: line-enrolled against a microphone query scored
  278 at a margin of 5.1x, the other way round 3.1x, with the time offset dead
  on zero in both directions. So the 132,000 fingerprints built up through the
  microphone did not have to be thrown away.
- **It is genuinely realtime.** 176,616 B/s measured over a minute against
  176,400 expected, steady in every ten-second window.

What it costs: one client at a time, only the analog inputs (anything over HDMI
stays silent), and an undocumented manufacturer endpoint that a firmware update
could take away. The knob, the screen and the shelf do not depend on it.

`pi/line.sh` replaces `microphone.sh`: it asks the receiver which inputs it has
and measures each one, pausing the ears first because they hold the one
connection allowed.

**Known rough edge.** The noise floor is seeded from the first block the ears
read. Start the service in the middle of a side and the floor seeds on music,
so that side will not trigger a lookup; it settles at the first real silence.
With a microphone the room noise hid this. Not fixed here, because the
threshold logic is tuned and this change was about the source.

## Phase 8 — A fine rotation ✅

**6 August 2026.** The panel came out of its mount a few degrees off, and LVGL
turns a display by whole quarters and cannot turn a label at all. So this turns
the finished frame on its way to the glass, in `flushRotated()`, with the touch
point turned back by the same angle.

Nearest-neighbour sampling looked exactly like what it is — a staircase through
every line of text — so it interpolates between all four neighbours. Plain that
cost 241 ms a frame, which on this device is not a trade worth making. Three
things brought it to 101 ms of flush and 186 ms all in, against 113 ms with no
rotation:

- `-O3` on that one function, and running it from IRAM where it is not fighting
  the flash cache for the bus PSRAM sits on;
- skipping the corners. The panel is round and the buffer is square, so a fifth
  of every frame was never visible. The spans are worked out once at startup.

Two things worth writing down. The first attempt interpolated only between rows,
argued from three degrees where a row slips two thirds of a pixel; at six it
slips two and a half and the argument fails — a number from one operating point
does not settle a choice at another. And the counters behind all these numbers
had to be made cumulative before any of it could be measured at all: they reset
on read, and the Pi asks the panel for its state every ten seconds, so every
measurement came back zero because the poll had drained it.

Six degrees is a lot to be out by, and a shim costs nothing per frame. The angle
is for when the mount cannot be moved.

## Phase 9 — Which record is it, then ✅

**6 August 2026.** Robbie Williams gave this away. A track came up and the
sleeve that appeared was *Greatest Hits*, when what was turning was *Swing When
You're Winning*. Nothing was broken: Shazam recognised the song correctly and
then named the release its own metadata prefers, which for anything with a hit
on it is a compilation. The brain matched that title against the shelf, found a
record by that name, and was wrong for entirely reasonable reasons.

So the question changed. Not "what album is this song from" — a service's answer
to that is an opinion — but "which of *your* records carries this song". That is
a different question and your own shelf can answer it. Discogs has the
tracklists; 549 releases and 8,259 tracks later, `releases_with_track()` answers
it in a query.

Usually there is exactly one and nothing is asked. Sometimes there are three,
and then nothing here can tell which platter is on. It would be worse to guess:
a wrong link is permanent and teaches the local fingerprint database a lie. So
it asks, and the asking is the shelf you already know — same three sleeves, same
knob, same press — narrowed to the records it could be. The letter ring goes
away with them, because jumping by initial through four sleeves is turning with
extra steps, and a ring of letters would suggest the rest of the shelf is still
out there to walk to.

Three things this turned up along the way:

- **Two copies of a record is not a choice.** Life Thru A Lens is on the shelf
  three times. Offering all three is a question with one answer written down
  three times, so duplicate pressings collapse by artist and title, oldest kept.
- **A match is not the same as an answer.** A recognised track whose album you
  do not own — Cocky, off *Escapology* — was marked recognised and the open link
  was dropped, so pointing at the right sleeve was quietly impossible. The link
  now stays open whenever the listen has not landed on one of your records,
  whether that is because there are several or none.
- **The question has to survive you not being there.** A choice made only on the
  panel is a choice lost if the record played while you were in another room, so
  those listens get their own status and wait in the queue with the candidates
  laid out, one press each.

Sixteen cases in `v2/brain/test_match.py`, each one a mistake that actually
happened or a rule that must keep working — including Hans Zimmer's *Live*,
which the first fix for the compilation problem broke and which is why replaying
all 113 historical lookups was worth the trouble.

## Phase 10 — A screen that can tell you where it is ✅

**7 August 2026.** Half an hour off the mains and it came back asking to have
Wi-Fi set up, on a network it already knew. Nothing was lost — the credentials
were still in NVS — but falling back to the access point was a one-way door.
Twenty-five seconds at boot, and if the router was not answering yet the panel
put up its own network and stayed there for good; `maintainWifi()` returned
immediately in that mode and never tried again. A router coming back from a
power cut takes minutes, and this thing is up in three seconds, so it lost that
race every time.

With credentials stored it now runs AP and station at once. The access point is
how you fix a wrong password; the station is how it gets itself back without
you. Proved rather than argued: a build with the boot timeout set to 1 ms, so it
is *guaranteed* to fall into setup mode, recovered to the LAN in under four
seconds and logged "Wi-Fi is back". Flashing goes over USB from the Pi, so that
experiment could not strand anything.

That fix needed somewhere to say "here is the address", and the address turns
out to be the thing you can never look up at the moment you need it: standing at
the shelf, just after setup, with no idea what the router handed out. So there
is a settings screen — a QR with the address written under it, then the Wi-Fi,
the Pi, the receiver, the brightness, and a way back. Turn to page, press to
close.

Three corrections came straight from standing in front of it. It showed two
addresses, this panel's and the Pi's, which is a screen answering a different
question than the one you asked — the panel's own page is reachable through the
web interface anyway, so one address it is. Everything was set in the sizes used
for asides, fourteen point and grey, where this is read from a metre away while
you stand there; it went up a size and into full white, and the only grey left
is the one line that says what the knob does. And the brightness needed a press
before turning would do anything, which nothing on screen said: it says it now,
and the level fills the same ring the volume uses, because a quantity you set by
feel should not be a number you read.

Three things about where it lives:

- **At the bottom of the input list**, next to Turn Off. That list is already
  the place for things that are not inputs, and it is where you go when the
  record is over.
- **It shows itself** the moment Wi-Fi comes up — after setup, or after an
  outage — but not on an ordinary boot, where it would be noise, and not when
  the screen is off, where it would be a light in a dark room.
- **It is exempt from the screen overrides.** No Wi-Fi and no receiver both
  force their own full-screen message, and those are precisely the two moments
  you go looking for an address. A press of the knob on either of them opens it,
  because on those screens there is nothing to mute and no list to confirm.

---

## What carries over from version 1

Version 1 keeps working on its own and is not throwaway work. Directly reusable:

- the protocol (`MV`/`SI`/`MU`/`ZM`, `dB = value - 80`, half steps, `MVMAX`)
- that the receiver pushes unasked, so no polling is needed
- the quadrature decoder and the `encDivider` idea, to tune the step size per
  click
- the 250 ms delay on an input choice
- the division of labour: the device shows, the web interface configures

And the two conditions: Network Control on "Always On", and one telnet session
at a time.
