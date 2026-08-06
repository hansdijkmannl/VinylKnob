# Version 2 — design notes

The idea: a round touchscreen (Pimoroni **HyperPixel 2.1" Round**, 480×480 IPS
with capacitive touch) with a **rotary ring** around it driving a detentless
encoder through gears. The screen shows the volume, what is playing, and your
whole record shelf to browse through. A microphone recognises which record is
on, so the unit can simply stay next to the sofa.

The parts are in [../v2/BOM.md](../v2/BOM.md), the build order in
[../v2/PLAN.md](../v2/PLAN.md).

This document is the analysis beforehand, not the build description, and it is
kept as it was written — including the parts that turned out differently. There
was a version 1 at the time it was written: a bare ESP32 with a rotary encoder
and no screen. It has since been removed from the repository, so the references
below are to something that no longer ships. They are left standing because the
reasoning only makes sense with them in it.

---

## The ring

The ring drives a **detentless rotary encoder** through printed gears. No
potentiometer, no motor.

### Why not a potentiometer

A potentiometer is absolute: its angle *is* the volume. Attractive, until
someone picks up the remote — then the ring's position no longer matches
reality. That is solvable with a motor that turns it back, but it costs an
H-bridge, a split supply, a dead zone in software against backlash, and a ban on
recording while the motor runs (it sits centimetres from the microphone).

There is a simpler argument, and it is decisive: **the SR7015's own volume knob
does not follow the remote either.** It is an infinite encoder. Our ring ought
to behave like the knob of the device it controls — otherwise you build a thing
that feels different from the rest of the system.

And the screen sits exactly in the middle of the ring. The volume arc runs along
the rim, precisely where your fingers are. *That* arc is your position
indicator; you need no absolute potentiometer for it.

Something else an encoder brings: **no end stops**. A potentiometer turns ~270°
and then stops. For a volume knob that is defensible, but turning on forever is
simply nicer.

### The gearing

Printed spur gears, module 0.5-0.8: internal teeth on the inside of the ring and
a pinion on the encoder's shaft.

The ratio follows from the geometry. A 15-25 mm pinion against internal teeth of
~70 mm gives 3 to 4.5:1. With a 24 pulse-per-revolution encoder that yields 290
to 430 quadrature steps per turn of the ring. Version 1's `encDivider` setting
then trims that to taste — that knob is already there.

**Backlash in the teeth is harmless here.** You only measure change, not
absolute position, so reversing direction costs you a fraction of a degree at
most. With a motorised potentiometer that *was* a problem; not any more.

Take a **detentless** encoder. With the gearing on top you would otherwise feel
100 to 150 clicks per turn of the ring, and that is exactly the rattly feel we
want to avoid.

### Optical would also have worked, but

Earlier I preferred optical sensing: a printed ring with black and white
segments and two reflective sensors. On a multi-colour printer that is one
print, and it is contactless.

There is a dimensional problem in it that I overlooked at the time. For
quadrature the two sensors have to sit **a quarter of a segment pitch** apart.
With 120 segments on a 70 mm ring the pitch is 1.8 mm, so a quarter is 0.45 mm —
and a TCRT5000 is ten millimetres wide. You can put them *n plus a quarter*
pitches apart, but then the placement accuracy is still a few tenths of a
millimetre. A gear train is a good deal more forgiving.

Optical remains the nicer solution if the gears start to annoy you. Start with
the gears.

### Mass and damping

The potentiometer brought its own damping; an encoder does not. So adjustable
friction comes back — and it is now the only thing that determines the feel:

- **Mass in the ring.** A printed ring of 25 g feels like a toy. A groove on the
  inside, a steel ring or M8 nuts in it, aim for 150-250 g.
- **Adjustable friction.** A felt or PTFE ring between the ring and the fixed
  part, with the preload set by three small screws. Expect a few iterations;
  this is the parameter you only find with the thing in your hand, and you want
  to be able to adjust it without destroying everything.
- **Grease in the bearing.** Thicker bearing grease gives a noticeably richer
  run. A small effect, but free.

### Bearing

A thin-section deep-groove bearing **6813** (65 mm inner, 85 mm outer, 10 mm
thick) fits comfortably around a 71 mm display. A cheaper alternative that works
surprisingly well: a printed race with loose 3 mm airsoft balls in it.

### What reads it

The **ESP32-C3**, with version 1's quadrature decoder unchanged. That same C3
also carries the microphone and talks to the Pi over a single USB connection.
That is not just a division of labour but a necessity: the HyperPixel leaves
hardly any GPIO on the Pi.

---

## Architecture: three routes

Since the CrowPanel came into view there are three ways to build this. The last
one is new and probably the best.

### A. Pi + HyperPixel, all in one

What was here originally. A Pi Zero 2 W with a HyperPixel 2.1" Round, an
ESP32-C3 for the encoder and the microphone, and a self-built ring with gears
and a bearing. ~€140 and most of the mechanical work.

### B. A CrowPanel on its own

**Elecrow CrowPanel 2.1" ESP32 Rotary Display**: ESP32-S3R8 with 8 MB PSRAM and
16 MB flash, a round 480×480 IPS screen with capacitive touch, a built-in rotary
encoder, in an aluminium and acrylic housing (79×79×30 mm, 80 g). Around €35-40.

That replaces display, computer, encoder, bearing, gears and enclosure in one
go. But it costs two things: there is no documented free GPIO for an I2S
microphone (only UART, I2C and a 12-pin FPC), and **shazamio does not run on an
ESP32** — it is Python with a Rust core. You would then be tied to the AudD API,
with a key and costs beyond the free tier.

### C. CrowPanel + a bare Pi next to it — **chosen**

The combination, and most of the problems disappear with it:

| Does | What |
|---|---|
| **CrowPanel** | screen, knob, touch, telnet to the AVR, all of the controls |
| **Pi (headless)** | USB microphone, shazamio, local fingerprint database, Discogs, the web interface with the linking queue |

They talk over the network, or over the CrowPanel's UART connector.

The reason this works out better than route A: **the Pi no longer has to drive a
screen.** That removes the HyperPixel's GPIO problem, the need for a second
microcontroller for the encoder, and the fact that you sit watching Linux boot
for thirty seconds — the CrowPanel is on instantly, and the Pi starts up in the
background.

And the microphone: because there is no display on the Pi any more, the whole
40-pin header is free. So no USB dongle but an **INMP441 on I2S** — raw PCM
without the hidden gain control and noise suppression that cheap USB microphones
have in hardware. Exactly the processing we explicitly switch off in the web
test because it harms recognition.

Cost: CrowPanel €40 + Pi Zero €22 + SD card €8 + USB microphone €5 ≈ **€75**,
against €140 for route A. And the mechanical work is nil.

What you give up is the feel of the knob: that built-in encoder is small, light
and almost certainly detented. That is exactly what this project set out to get
right, so it is not a detail — but it is something a printed ring around it can
partly correct, and otherwise you still build your own ring against a display
you will know by then.

### The choice

**Route C.** More possibilities, shazamio stays within reach, no API key needed,
and the local fingerprint database stays possible as a cache.

What still has to be found out is not the architecture but the feel: **buy the
CrowPanel first, on its own** and feel how that built-in knob turns. Forty euros
against half a design is not a gamble, and you can build phase 2 with it
straight away without taking a single decision about the Pi.

---

## Platform choice: Pi or ESP32

The HyperPixel forces a Raspberry Pi — it is a DPI display that sits on the
40-pin header. That is not a small choice.

### Note: the HyperPixel eats your GPIO

DPI displays use nearly all of the Pi's GPIO pins. What is left over for two
encoder sensors is minimal to nothing. **Check the pinout of the 2.1" Round
before you order anything.**

The robust solution is not to work around it but to design around it: let the
**ESP32-C3 you already have** read the ring and send the counts to the Pi over
USB serial. That costs a couple of euros of nothing, gives you guaranteed tight
interrupt timing, and leaves the Pi only having to draw and talk to the
receiver.

### Which Pi: the Zero 2 W comes back into view

The memory calculation that earlier led to a Pi 4 with 4 GB came entirely from
the local fingerprint index. Now that it is a cache rather than the main
mechanism, that claim falls away and the whole thing fits in **512 MB**:

| | |
|---|---|
| Raspberry Pi OS Lite, 64-bit, no desktop | 80-120 MB |
| Python with pygame and Pillow | 60-80 MB |
| Sleeve images on screen (the rest on disk) | 20-40 MB |
| An 8 s audio buffer | negligible |
| Possibly a cache of ~50 often-played sides | ~37 MB |
| **together** | **~250-300 MB** |

And in size the Zero is clearly the better one: 65×30 mm, so it disappears
entirely behind a 71 mm display. With the ring around it the whole becomes a
puck of about 90-95 mm. A Pi 4 also fits behind it, but is thicker because of
its connectors and needs cooling.

Three things you do have to arrange then:

**Raspberry Pi OS Lite, 64-bit.** Not the desktop version: an X11 or Wayland
session on top drains the Zero. And 64-bit because shazamio has a Rust extension
— check in advance that aarch64 wheels exist for it, because compiling it
yourself on a Zero is no fun.

**The UI straight on KMS/DRM.** Pygame on the framebuffer, no browser and no
desktop. 480×480 is only 230,000 pixels; a Zero 2 W handles that fine, provided
you scale sleeves to size in advance and cache them on disk instead of shrinking
them every frame.

**One USB device, because the microphone goes on the C3.** It has an I2S
peripheral and enough GPIO, so an INMP441 on it, and it sends audio *and* the
encoder position to the Pi over the same USB connection. 16 kHz mono is 32 kB/s,
well within what USB CDC on a C3 can manage.

That saves a USB hub in the enclosure — the Zero has only one data port — and
the board is in there for the encoder anyway. The microphone is then inside the
box, so there has to be an acoustic opening in the wall.

Only decide this once you know which records Shazam does *not* recognise. If a
serious local database turns out to be needed for them, the memory question
comes back and you are at 2 or 4 GB after all.

### The comparison

| | Pi + HyperPixel | ESP32-S3 with a round touchscreen onboard |
|---|---|---|
| What it is | a separate display on a little Linux computer | a ready-made board, e.g. the Waveshare *ESP32-S3-Touch-LCD-2.1* (480×480 round) — verify the specs |
| Cost | ~€100 (display €60-70, Pi Zero 2 W €20, SD €8) | ~€35-45 |
| On after power | 25-40 s to boot on a Zero | immediately |
| Maintenance | OS updates, SD card corruption (set root read-only!) | none |
| GPIO for the ring | practically nothing left, an extra MCU needed | plenty |
| Building the UI | Python + pygame, or LVGL — quick and familiar | LVGL in C, nicer result but more work |
| Extras | music recognition can run locally on the same board | recognition has to go to a service elsewhere in the house |

**If the knob only does input and volume: the ESP32-S3 board.** A volume knob
that takes 25 seconds to boot and has an SD card in it that can corrupt is a
computer, not a device.

**If you want the music recognition with it: the Pi.** Then the fingerprint
database runs on the same board as the screen, no audio has to cross the
network, and you have Python for both the UI and the matching. That is the only
real argument for the Pi, but it is a good one.

---

## Listening with a microphone

The unit sits by the sofa and has to be able to stay there: no cables to the
turntable, no Y-splitter, no separate phono preamp. It simply listens to the
room, like a phone app does.

I have argued against that before, on the grounds that a microphone is in the
wrong place and hears everything. On reflection the first objection largely
falls away, and the second is solvable — with something we already have.

### Why this works out better than I thought

**The measurements are already there.** The recogniser in
[../v2/recognizer/](../v2/recognizer/) managed faultlessly down to 20 dB
signal-to-noise, and at 10 dB still gave the right record *with* the exact time
position. A phone three metres from a pair of speakers sits around 15-25 dB.
That is exactly the range that has been measured. Shazam works in a pub; this is
a living room.

**Room acoustics cancel against themselves.** The argument that vinyl-against-
vinyl matches better than vinyl-against-master becomes stronger here: the
reference is recorded with the same microphone, in the same room, in the same
place, through the same speakers. All the distortion of that path is in both
recordings and cancels out — just like the platter's speed deviation.

There is a consequence: **move the unit and the acoustics change.** Enrolling
again is cheap, but this is not a device you move every week.

**The "it hears everything" problem is solved by the AVR itself.** We are
already connected over telnet and so know exactly whether the input is on phono,
whether the zone is on, whether it is unmuted, and how loud it is. Only when all
of that holds does the microphone come on. Talking while it listens is still
noise, but that is precisely the case that is called 10-20 dB and has been
measured.

### What you need

A **USB microphone**. That is not a preference but a consequence: anything going
over the 40-pin header or over I2S clashes with the HyperPixel.

**So a ReSpeaker 2-Mics Pi HAT is out.** It is a HAT: it goes on the same header
the HyperPixel needs, and it also uses I2S plus I2C for its codec — exactly the
pins the DPI display claims. Ruled out mechanically and electrically. The same
goes for a separate I2S MEMS microphone like the INMP441.

A simple USB dongle with an electret capsule will do, and that is less of a
compromise than it looks: **the quality of the microphone barely matters for
recognition.** The reference and the query go through the same microphone, so
any colouration of that path cancels against itself — just like the room
acoustics and the platter's speed. And we work at 11 kHz mono anyway. What does
matter is that it is always the same microphone in the same place.

Two practical things for the enclosure:

- **An acoustic opening.** The microphone must not sit in a closed printed box.
  A hole at the front, the capsule right behind it, and not glued rigidly to the
  wall.
- **No motor noise to allow for.** That was a worry when the ring still drove a
  motorised potentiometer; with an encoder nothing moves on its own.

For "something is playing" no separate circuit is needed any more — the energy
level of the microphone recording is enough, as long as you combine it with the
state the AVR already reports. If that level stays low for twenty to thirty
seconds while phono is selected and the zone is on, the side is over.

---

## Recognition — only to show something nice with

The goal is not a track list but **a sleeve or an artist on the screen**. A good
picture that belongs with what is playing. That saves an enormous amount: you
only have to recognise the **album**, not which track is running. One match per
side, no timeline, no track boundaries — precisely the difficult part falls
away.

### The database is the problem, not the algorithm

Shazam's approach is well documented and there is open source that does it
(**Dejavu**, Python). What you do not have is their database of tens of millions
of tracks, and an official Shazam API does not exist.

But you do not need that database either: you only have to recognise **your own
record shelf**. A few hundred albums. On a search space like that, matching is
trivial, fast and entirely offline.

### Discogs closes the circle

If you have your collection on **Discogs**, you already have the catalogue.
Discogs is the only source that knows your *pressing* — including the right
sleeve image, which is exactly what makes the difference with reissues and
special editions. MusicBrainz with the Cover Art Archive is the open
alternative.

Practically: Discogs works with a **personal access token** (no OAuth dance
needed), allows 60 requests per minute, and **insists on a User-Agent header** —
without that header the API flatly refuses you. Fetch the collection through
`/users/{user}/collection/folders/0/releases`, paginated. Cache the sleeve
images locally instead of fetching them on every display.

### Tested: it works

**Measured on 31 July 2026** with [../v2/webtest/](../v2/webtest/README.md):
music from an iPhone speaker, picked up by a MacBook's microphone, recognised
**nearly everything in 8 seconds** — with sleeve, artist, album.

That matters more than it looks, because it clears up two worries that steered
the whole design:

- **A room microphone is enough.** No tap on the phono line, no separate
  preamp, no cables to the turntable.
- **Pressing differences are less bad than expected.** I had reasoned that vinyl
  would match poorly against a digital master. In practice it goes fine. That
  weakens the argument for an own local database.

And the real setup is *easier* than the test: a Marantz with decent speakers
gives the microphone more to work with than a phone speaker.

### What this means for the local database

The own fingerprint database in `../v2/recognizer/` was meant as the main
mechanism. It now drops to a **cache**: nice not to have to go on the network
every time and to keep working offline, but no longer necessary to recognise
anything at all.

That has a concrete consequence for the hardware. The whole memory calculation
that led to a Pi 4 with 4 GB came from that local index. Without it — or with
only a cache of records you play often — a smaller Pi comes back into view.
**Only decide that once you know which records Shazam does not recognise**,
because that is exactly where an own database earns its place.

### An important limitation: only ask on a change

shazamio is an unofficial client on Shazam's own endpoints, without a key. For a
few lookups a day that is unobtrusive; ask every fifteen seconds and you are at
hundreds of requests a day and you risk being throttled. On top of that it is a
reverse-engineered client that can break at any change on their side.

So: **do not ask on a timer, but on an event.** The AVR says over telnet when
the input goes to phono, and the microphone level says when sound starts again
after silence. Those are the two moments you ask once — a handful of lookups an
evening instead of hundreds.

### Cold start: ask once, then know it yourself

The weak point of a self-learning database is that you have to tag every record
by hand once. The existing recognition services solve that:

1. An unknown side starts playing → **one** call to a recognition service.
2. The answer (artist + album) → look it up in your Discogs collection → sleeve.
3. Store a fingerprint of that side locally, linked to that release.
4. Every time after that: a direct local match, no more calls.

That is **one API call per new record, ever**. A few hundred for a whole
collection, which fits comfortably in a free or cheap tier. After a month you
practically stop using the service, and the thing works entirely offline.

The reason for storing locally still stands: matching vinyl against vinyl is
more reliable than a service comparing against the digital master. Pressing
differences and your platter's speed deviation fall away as soon as the
reference comes from your own turntable. The service only gives the record a
name; it does not have to recognise it every time.

| Candidate | What it is | Useful as |
|---|---|---|
| **AudD** | commercial API, upload a clip and get artist/album back; free tier, then ~$5/month | the cold start — the most used choice and the simplest to integrate |
| **ACRCloud** | commercial with a free developer tier; can also host your *own* audio bucket | cold start, or if you would rather put the whole database in the cloud after all |
| **AHA Music** | a service with an API, originally a browser extension | an alternative for the cold start; less common for this purpose |
| **Audile / Audire** | open-source Android clients (F-Droid) | **reference implementations**, not engines — they call an API themselves (AudD as far as I know). Read their code for sample length, format and error handling; check in the repository which backend they use |
| **Dejavu** | open-source Python fingerprinting, self-hosted | the local database that does the work after the cold start |

Note that "open source" for Audile and Audire refers to the app, not to the
algorithm or the database. You cannot put them on a Pi and be done.

### Where it runs

Not on the microcontroller. Record through an I2S ADC (**PCM1808** breakout,
~€8; the ESP32's internal ADC is too poor for this), ~15 s over Wi-Fi to a small
Python service, sleeve back. That service can sit on your Mac or a Pi — and if
you choose the Pi variant, it simply runs on the same board as the screen.

---

## Unrecognised records: the queue

If Shazam does not recognise a record, that is not a dead end but the starting
point. The recording that exists anyway is kept, and you link it to the right
record later. From that moment the device recognises it **itself**, without a
service.

That way the local database grows precisely where Shazam falls short, and only
there. You do not have to read your collection in beforehand — the gaps fill
themselves, in the order you come across them.

### Keep listening when it goes wrong

Eight seconds is enough to *ask* Shazam with, but **not enough to serve as your
own reference**. From the measurements in
[../v2/recognizer/](../v2/recognizer/README.md): an eight-second reference
covers eight seconds of the side. If the needle is somewhere else next time,
there is nothing to match against.

So: when the lookup fails, the device simply keeps listening for another **60 to
90 seconds**. The record is playing anyway. That longer recording is both things
at once: the audio clip you listen back to later, and the fingerprint reference
for afterwards.

### What you see in the web interface

A list of unrecognised sides, each with a time and a play button — because after
two days you no longer know what was on on Tuesday evening. Per row:

- **search Discogs**, first in your own collection and only then the whole
  database, because you own the record after all
- or **upload a sleeve yourself**, for bootlegs, private pressings and
  everything Discogs does not know
- or **throw it away**, if it was the radio after all

Confirming does three things at once: the sleeve is fetched and cached, the
fingerprint is linked to that release, and the row disappears from the queue.
Next time the sleeve appears within a few seconds, without a network.

Next to it a second list of what *was* matched, with "that is wrong" on each
row. Without that button a wrong match becomes permanent, and that is exactly
the sort of thing that makes a nice device annoying.

### Cleaning up

The audio clips are recordings from your living room. Keep them short, only
record when the AVR reports phono is playing, and **throw the audio away as soon
as the side is linked** — the fingerprint is then all you still need, and that
is not audio any more. Clean unlinked clips up automatically after a month.

## Getting to the web interface: a QR code on the screen

The device knows its own address; you do not. So the screen shows a **QR code**
you scan with your phone, with the address below it in plain digits for anyone
who wants to type it on a laptop.

Two choices in that:

**Encode the IP address, show the hostname as text.** `vinylknob.local` is
nicer and does not change, but not every phone resolves mDNS reliably. The
address always works. Give it a DHCP reservation in your router and it is stable
too.

**Let it appear the moment there is something to do.** Not permanently on screen
— that is ugly and usually unnecessary. But the moment a record is not
recognised is exactly the moment you reach for your phone. The QR then comes to
you instead of you having to find a settings screen. Reachable with a tap on the
screen as well.

On a round 480×480 screen a square of about 340×340 pixels fits inside the
circle. Plenty. Generating it can be done with the `qrcode` library for Python:
small, no heavy dependencies, and fast enough on a Zero.

## The picture

480×480 round is a gift for this subject: it is the shape of a record.

**Show the sleeve as a label.** A square sleeve cropped round, with a subtle
spindle opening in the middle and fine grooves towards the rim. That is
format-native in a way a square screen can never be, and losing the corners of
the sleeve then reads as intent rather than as a crop.

**Volume as an arc along the rim.** Precisely where your fingers rest on the
ring, so the arc reads as the ring's position. While turning it lights up and
the dB value briefly comes over it; after that it fades and the sleeve is left.

**Take the colour from the sleeve.** Pull the two or three dominant colours out
of the image and use them for the arc and the glow. It costs little computation
and the device looks different for every record — that is the kind of detail
that makes it feel "made" rather than "built".

**Do not make it spin.** Tempting, but 33⅓ rpm is 1.8 seconds per revolution and
that is restless; and turning it more slowly is a trick that palls after a week.
More important: the picture ought to stand still because the **ring** is the
thing that moves. Two things turning at once fight each other.

**When there is no sleeve:** typography. The artist's name large, the album
below it, in the colour of nothing. That can look better than a mediocre image.
And on an input other than phono: simply the volume and the input name, large,
not an empty circle.

## The collection on the screen

Besides "what is playing now", also: **browsing your record shelf with the
ring**. The sleeves slide past, you tap to choose.

### How it switches

Tap the screen to get into browse mode; the ring then scrolls through the list
instead of setting the volume. Tap to choose, or do nothing and after a few
seconds it goes back on its own.

With an encoder that switching is free. With an absolute potentiometer the ring
would sit, after browsing, at a position that no longer matched the volume, and
that was previously the whole argument for a motor. Now the ring only counts
change, so there is nothing to put back.

You point with the screen. The ring has no press function, and you are looking
at the screen anyway.

### What "choosing" gets you

You cannot make a record play — somebody has to get up. Two things it *is* good
for, and both are worth it:

- **"What shall we put on?"** Scrolling through the shelf with the sleeves on
  screen is a nicer way to choose than squinting along the spines of your
  records. If you have filled in a storage location in Discogs, show that with
  it.
- **Linking by hand.** If it does not recognise the record, you turn to the
  right album and tap. That moves linking from the web interface to the device
  itself for the ordinary case.

That last one makes the web interface a good deal less important: it is left for
settings, tokens, and correcting earlier mistakes in bulk.

### Design

On a round screen an arc works better than a list. Three or five sleeves on a
segment of a circle, the middle one large and sharp, its neighbours smaller and
softer. Artist and album underneath.

You scroll with your finger over the screen, or with the ring. The latter works
better now than in the earlier arrangement: an encoder only counts change and
turns on forever, so you scroll for as long as you like instead of getting your
whole shelf spread over 270 degrees. For a few hundred albums that is the
difference between usable and frustrating.

Do add an alphabetical jump index along the rim, so you do not have to turn
through three hundred sleeves to get to the W.

### Keep it out of the control path

Recognition feeds **the screen only**. It switches nothing and sets nothing. If
a match is wrong, there is a wrong sleeve on screen — not an amplifier doing
something unexpected. Input and volume stay purely the ring's.

---

## What carries over from version 1

Directly reusable, whatever the platform:

- **The protocol knowledge.** `MV`/`SI`/`MU`/`ZM`, the volume model
  (`dB = value - 80`, half steps), `MVMAX`, and that the receiver pushes
  unasked. It lives on in
  [`v2/crowpanel/src/marantz.cpp`](../v2/crowpanel/src/marantz.cpp).
- **The quadrature decoder** (the 16-value table in `src/main.cpp`).
- **The 250 ms delay on an input choice**, so the receiver does not touch every
  input on the way.
- **The settings model** and the web interface arrangement.
- The two hard conditions: Network Control on "Always On", and one telnet
  session at a time.

What does **not** carry over: the gestures. A ring has no push button. Mute,
on/off, choosing an input and the favourite all move to the touchscreen. That is
no loss — it is better, because a radial menu with your inputs on it is
self-explanatory where "press twice" never becomes that.

---

## Order of work

Finish version 1 first. Not out of caution, but because you then know three
things you do not know yet: whether the telnet protocol behaves as expected on
your unit, how many dB per step feels right, and how much friction a knob may
have before it becomes annoying. That last one is precisely the parameter that
decides how version 2 feels, and you can only find it with a knob in your hand.

The signal detection, incidentally, is not tied to version 2. An envelope
detector on a free ADC pin and then sending `ZMON` + `SIPHONO` is two parts and
twenty lines, which fit version 1 just as well. A good first extension once the
board runs. The music recognition is a project in itself and belongs with
version 2, with its screen to show it on.
