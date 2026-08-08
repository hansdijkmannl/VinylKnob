# Building it, step by step

The order to bring the parts up in, with what you should see at each step and
what to do when you do not.

Wiring is in [wiring.svg](wiring.svg). The reasoning behind the choices is
in [PLAN.md](PLAN.md) and [BOM.md](BOM.md).

---

## Step −1 — Find out whether your receiver can do it, before you order

Half of this is a volume knob and works on any Denon or Marantz that speaks telnet
on port 23, which is most of them from the last decade. The other half — knowing
which record is on — needs the receiver to hand its **analog inputs over HTTP**,
and that is a narrower feature. There is no published list of which models have
it, so ask yours. It costs nothing and you do not own anything yet.

**Switch the receiver on** — in standby it does not serve these streams at all;
Network Control keeps telnet alive, not the audio server — and put a record on.
Then, from any machine on the same network:

```bash
curl -s --max-time 3 -o /tmp/probe "http://192.168.1.60:8015/analoginput/analog/analog/0/phono"; wc -c < /tmp/probe
```

With your receiver's own address in place of `192.168.1.60`. Nothing is changed by
this; it reads three seconds of audio and throws it away.

| What comes back | What it means |
|---|---|
| a few hundred thousand bytes | it works. Order the parts |
| `0` | either the receiver is in standby, or it does not do this. Try again with it switched on before concluding anything |
| a connection error | nothing is listening on 8015 — this model does not serve its inputs |

If your turntable is not on `PHONO`, the path is the stream's own name and not the
front panel's: `mediaplayer` for MPLAY, `cable_sat` for SAT/CBL, `aux_single` for
AUX1, `tvaudio` for TV. Try `phono` first anyway; it is right on most.

**A receiver that fails this is still worth building for.** You get the knob, the
volume, the input list, the shelf to browse, the sleeves for anything an Apple TV
plays, and hand-linking records from the queue. What you do not get is a record
naming itself, which is admittedly the best trick.

---

## Step 0 — What else you need, and what to check when the boxes arrive

Nothing on the [parts list](BOM.md) is unusual, but four things around it are
easy to be caught without:

| | |
|---|---|
| a computer with **PlatformIO** | for flashing the panel once. `pip install platformio` in a virtualenv is enough; you never need the IDE |
| a **microSD reader** and **Raspberry Pi Imager** | for the Pi's card |
| an **SSH key** | the Imager will put your public key on the card, which is much better than a password |
| a **Discogs account** | free, and the shelf comes from it. Settings › Developers for a personal access token |

**The parcels rarely arrive together, and that is fine.** With only the panel you
can do steps 1 to 3 and end up with a working volume knob and input selector on
the shelf, which is worth having on its own. The Pi adds everything about records
later, and the panel does not change when it appears.

**When you unpack the panel**, check the cable is in the box: plain USB-A at one
end, a small white **4-pin JST MX1.25** at the other, which goes into the connector
marked `USB-5V-IN` on the board. The CrowPanel has no USB socket of its own and that
plug is awkward to source separately, so if it is missing, take it up with the
seller rather than going shopping.

That one cable is the whole connection. Power and data both: the Pi sees the panel
as `303a:1001 Espressif USB JTAG/serial debug unit` drawing 500 mA, which is the
S3's own native USB with no bridge chip in between — and is why the panel can be
flashed from the Pi later without touching it.

---

## Step 1 — Nothing else may hold the amplifier

The receiver accepts **one telnet session at a time**, and the panel needs it. If
something else has it, the panel reports "No receiver" — which is the most
confusing way this can fail, because everything else looks fine.

The usual culprits are Home Assistant with a Denon integration, a Denon or Marantz
app left open on a phone, or a second controller of any kind. Turn those off before
you start; you can decide later whether to give one of them a Zone 2 session
instead.

And in the receiver's own menu, **Network → Network Control → Always On**. Without
it the receiver drops its network when it goes into standby, and the panel can
never wake it — which looks exactly like a broken cable.

## Step 2 — Flash the panel

**1a. Find the cable.** The panel has no USB-C. Power and data share the
`USB-5V-IN` connector: a **4-pin JST MX1.25** (`GND · D+ · D− · VCC`). Elecrow
normally supplies a USB-A cable for it — you need that one.

**1b. Put it in flash mode.** There is no auto-reset: `RESET` and `GPIO0` are on
the 12-pin FPC, not on that 4-pin connector.

1. Hold the **BOOT** button down
2. Plug the cable into your computer
3. Release BOOT

Check that it announces itself:

```bash
ls /dev/cu.usbmodem*        # macOS
ls /dev/ttyACM*             # Linux
```

Nothing there is almost always the cable or the BOOT timing. Try again and hold
BOOT a little longer.

**1c. Flash.**

```bash
cd v2/crowpanel && pio run -t upload
```

**1d. Press RESET.** After uploading, the chip is still in the ROM bootloader;
your firmware only runs after a reset. The port name may change when it does.

**1e. Watch it come up.**

```bash
cd v2/crowpanel && pio device monitor
```

You should see:

```
VinylKnob — CrowPanel
[board] touch chip found
Setup access point "VinylKnob-setup" at 192.168.4.1
```

If it says there is no touch chip at 0x15, the PCF8574 was not found or the
reset sequence went wrong — the display is separate from that. A black screen
with everything else healthy is covered in
[crowpanel/README.md](crowpanel/README.md).

---

## Step 3 — Feel the knob

One minute, and it answers the question the whole design rests on: **does that
built-in encoder have detents?**

Almost certainly yes, which is exactly what you did not want — a real amplifier's
volume knob does not. If it bothers you, `encDivider` in the settings is the way
to tame it: it decides how many quadrature transitions make one step.

Do this before you start on the Pi. It is the only thing that could still change
the whole approach.

---

## Step 4 — Configure the panel

The panel has no keyboard, so this goes through a web page.

1. Connect your phone or laptop to the Wi-Fi network **VinylKnob-setup**
2. Open <http://192.168.4.1>
3. Fill in your own Wi-Fi, your receiver's IP address, and the list of inputs
   (with PHONO as the favourite)
4. Save — it restarts onto your network

After that the same page lives at <http://vinylpanel.local>, or at whatever
address the monitor shows. **Not** `vinylknob` — that is the Pi.

**If it ends up crooked in its mount**, there is a *Fine angle* next to
Orientation, in tenths of a degree. It turns the finished picture, text and all,
which LVGL cannot do on its own — and it is not free: a redraw goes from about
113 ms to 186 ms at six degrees, measured on the panel. A shim under the mount
costs nothing per frame and gives a sharper picture, so use the angle when the
mount cannot be moved rather than instead of moving it. Zero is the fast path;
leaving zero needs a restart.

**Now test it against the amplifier.** Turn the knob: the volume should follow.
Short press is mute, long press is on/off, tapping the input name opens the
input list.

If it does nothing, go back through step 1. Nine times out of ten something else
is still holding that telnet session.

---

## Step 5 — The SD card

Raspberry Pi Imager, **Raspberry Pi OS Lite (64-bit)** — no desktop; it only
costs memory and this machine never gets a screen.

In the gear menu:

| | |
|---|---|
| hostname | `vinylknob` (the panel is `vinylpanel`) |
| SSH | on, with your public key |
| Wi-Fi | your own network |
| user | your own name, not `pi` |

That hostname makes everything below reachable at `vinylknob.local`, even when
the router hands out a different address.

Card in, heatsink on, 27 W adapter into the Pi's USB-C. Wait a minute, then:

```bash
ssh vinylknob.local
```

---

## Step 6 — Set up the Pi

From your computer:

```bash
rsync -a --exclude '.venv' --exclude '._*' --exclude 'data' --exclude '*.stl' \
  ./ vinylknob.local:vinylknob/
```

Then on the Pi. Note the `-t`: the script uses `sudo` and needs to be able to
ask for your password.

```bash
ssh -t vinylknob.local 'cd ~/vinylknob/v2/pi && ./install.sh'
```

It lives in your home directory rather than `/opt` so that copying does not need
root. The script derives every path from its own location, so it works from
anywhere.

That takes a few minutes: packages, a virtualenv, two systemd services, and
reducing writes to the SD card (logs to RAM, swap off). Run it as often as you
like; it is idempotent.

---

## Step 7 — See whether the Pi runs

```bash
ssh vinylknob.local 'journalctl -u vinylknob-brain -u vinylknob-listen -f'
```

| | |
|---|---|
| web interface | <http://vinylknob.local> |
| raw levels | <http://vinylknob.local/status> |
| listen right now | `curl -X POST http://vinylknob.local/listen` |

In the web interface, **Shelf** tab, enter your Discogs token and sync the
collection — the database does not travel with `rsync`. Then press **Fetch
tracklists** and leave it: that is a request per release, so several hundred
records take a few passes at Discogs' rate limit. Everything that knows a record
has sides comes from it — being asked which of three pressings is on, the
`A4 · Angels` on the panel, the next track named before this one ends — so a shelf
without it works but says less. After the first time the nightly task keeps it
topped up on its own.

To keep fingerprints you built up elsewhere, copy `v2/brain/data/brain.db` across
separately and restart the service.

**Optional, and off unless you ask:** a
[ListenBrainz](https://listenbrainz.org/settings/) token under System → *For the
record* logs every recognised side to your listening history, which is the hole
vinyl leaves in everyone's. AudD, the paid second opinion, is next to it; most
people will not want it and Shazam plus your own database do not need it.

**Tuning without guessing:** put a record on and watch `/status` to see where
`levelDb` goes relative to `thresholdDb`. The adjustments live in
`vinylknob-listen.service`.

---

## Step 8 — Tell it which input the turntable is on

There is no microphone to plug in. A Denon or Marantz receiver digitises its
analog inputs and serves each one over HTTP — the machinery behind sharing an
input with HEOS speakers — and this listens to the turntable one.

This is done on the page, not in a file. Put a record on, open the web interface
, and go to **System → Where it listens**.

The list comes from your receiver rather than from a table in here, because the
names are the stream's and not the front panel's: `PHONO` is `phono`, but `MPLAY`
is `mediaplayer`, `SAT/CBL` is `cable_sat` and `AUX1` is `aux_single`. So
**Find it for me** is usually the quicker route — it reads every input for two
seconds and shows what it heard:

```
  phono         -36.6 dB
  cd            -92.5 dB
  tuner         -92.5 dB
```

It only names a winner if something is above -55 dB, which is what a record
sounds like on this line; music runs -33 to -48 and an idle input -80 to -92. With
nothing playing it says so rather than confidently naming the least quiet input,
which is what an earlier version did.

Under the list it says which front-panel input that is and whether the knob agrees
— the two settings live in different places and this is where a mismatch becomes
visible instead of becoming a fortnight of nothing being recognised.

**If the list is empty**, this receiver does not hand its inputs over. Recognition
by listening cannot work on it, and everything else — the volume, the sources, the
shelf, the sleeves for anything the Apple TV plays — works as it does anywhere.
HEOS speakers and receivers from before the HEOS generation are not built for it,
and there is no published list of which models are, so this is how you find out.

`v2/pi/line.sh` does the same thing over SSH and prints more detail; it is the
place to go when the page says something you do not believe.

## Step 8b — Pair the Apple TV

Only if you have one. Records come off the line feed and get recognised;
anything over HDMI does not need recognising, because the Apple TV knows what it
is playing and will say so.

Open the web interface, **Apple TV** tab, and press Scan. Pick your device and
press Pair: a PIN appears on the television, type it on your phone. It asks
twice, once for each protocol it needs. The credentials land in
`v2/brain/data/appletv.json` and survive a restart.

After that the panel switches by itself — the turntable input shows what the
line feed produced, any other input shows what the Apple TV reports. A track
with no artwork gets the app's own logo instead.

Netflix withholds its metadata and there is nothing to be done about that from
here. Apple TV+, Music and most others do not.

---

## Step 9 — Move the panel onto the Pi

Until now the panel hung off your computer. Move the USB cable to a USB-A port
on the Pi. Everything keeps working: the panel talks to the receiver over Wi-Fi,
the Pi talks to Shazam and Discogs over Wi-Fi.

Now they find each other, in one direction. Set `brainHost` in the panel's
settings — System → The brain — to the Pi's address; that is the one thing to
type. The other direction is automatic: the panel polls the Pi every four seconds
for what is playing, and the Pi learns the panel's address from those same
requests, which is also how it finds the receiver without being told twice.

Then put a record on. The sleeve should appear within fifteen seconds or so: four
to let the needle settle, eight of recording, and a moment to ask.

---

## When something does not work

| Symptom | Usually |
|---|---|
| panel says "No receiver" | something else still holds the telnet session (step 1) |
| no serial port appears | BOOT not held long enough, or the wrong cable |
| nothing happens after uploading | press RESET; the chip is still in the bootloader |
| black screen, monitor spews `ESP-ROM` | boot loop — see the appendix |
| black screen, monitor otherwise fine | see [crowpanel/README.md](crowpanel/README.md) |
| wrong colours on the screen | Arduino_GFX is not on v1.3.1 — check `pio pkg list` |
| `vinylknob.local` not found | avahi not up yet; try the IP from your router |
| one input does nothing, others work | that source is set to `DEL` in the receiver |
| the QR scans but the phone refuses to open it | Safari's **HTTPS-Only** blocks any `http://` address. Settings -> Apps -> Safari -> Advanced, or add an exception for this one |
| the volume works but no record is ever recognised | System &rsaquo; *Where it listens*: is the right input chosen, and does the knob's favourite agree? |
| the list of inputs there is empty | this receiver does not serve its analog inputs, so recognition by listening cannot work on it |
| a record is recognised as the previous one | one record has far more fingerprints than the rest. Capped now, but a database from before that may need the offender trimmed |
| no `A4`, and no next track either | no tracklists yet — Shelf &rsaquo; *Fetch tracklists*. The next-track line also needs printed durations, which Discogs has for a bit over half a shelf |
| AudD says the limit was reached | the free trial is a few hundred lookups. It is left alone for a day at a time after that; Shazam and your own database carry on |

---

## Appendix — the boot loop

The first time this was flashed the screen stayed black, and the monitor printed
this forty times a second:

```
ESP-ROM:esp32s3-20210327
rst:0x3 (RTC_SW_SYS_RST),boot:0xa (SPI_FAST_FLASH_BOOT)
Saved PC:0x403cdb0a
entry 0x403c98d0
```

Not one line of the firmware itself. So it was not a display problem: the board
was restarting before any of my code ran.

How it was found, each step ruling something out:

1. **The bare serial firmware** (no display, no LVGL, no backlight) looped the
   same way → not the screen, and not a power shortfall either.
2. **A build without PSRAM** looped too → not `memory_type`.
3. **Erasing the flash completely** did not help → no leftover of Elecrow's
   factory image.
4. **Flashing Elecrow's own factory image** worked immediately → the board, the
   power and the flash are all fine, so it was in my build configuration.
5. Comparing the flash headers of both images showed it: mine said **8 MB**
   while a partition table for **16 MB** sat underneath.

The cause: `board_build.flash_size` does nothing. The bootloader reads its flash
size from **`board_upload.flash_size`**, which was still on the board default of
8 MB. It then found partitions past the end of what it believed it had, and
restarted.

```ini
board_upload.flash_size = 16MB
board_upload.maximum_size = 16777216
board_build.partitions = default_16MB.csv
```

The actual flash was verified with esptool: manufacturer `ba`, device `4018`,
16 MB, quad according to the eFuse. And the chip really is an S3R8 — `Embedded
PSRAM 8MB (AP_3v3)` — so `memory_type = qio_opi` was already right.

Worth remembering: **the bootloader logs to UART0 (GPIO43/44), not to USB.** So
over the USB cable you only ever see the ROM lines and never the reason. To see
the reason, hang a USB-serial adapter on the UART connector.
