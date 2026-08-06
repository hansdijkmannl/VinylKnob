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
