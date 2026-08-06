# Building it, step by step

The order to bring the parts up in, with what you should see at each step and
what to do when you do not.

Wiring is in [wiring.svg](wiring.svg). The reasoning behind the choices is
in [PLAN.md](PLAN.md) and [BOM.md](BOM.md).

---

## Step 0 — Let go of the amplifier

The receiver accepts **one telnet session at a time**. If anything else is
connected, the panel cannot get in — and it will simply report "No receiver",
which is the most confusing way this can fail.

If you have been running the brain on a laptop, check:

```bash
curl -s http://127.0.0.1:8790/api/avr/state
```

If that says `"connected": true`, disconnect first:

```bash
curl -X POST http://127.0.0.1:8790/api/avr/disconnect
```

From here on the **panel** owns that connection. The web interface keeps working
for recognition and Discogs; just do not press "connect" there again.

---

## Step 1 — Flash the panel

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
MarantzKnob — CrowPanel
[board] touch chip found
Setup access point "MarantzKnob-setup" at 192.168.4.1
```

If it says there is no touch chip at 0x15, the PCF8574 was not found or the
reset sequence went wrong — the display is separate from that. A black screen
with everything else healthy is covered in
[crowpanel/README.md](crowpanel/README.md).

---

## Step 2 — Feel the knob

One minute, and it answers the question the whole design rests on: **does that
built-in encoder have detents?**

Almost certainly yes, which is exactly what you did not want — a real amplifier's
volume knob does not. If it bothers you, `encDivider` in the settings is the way
to tame it: it decides how many quadrature transitions make one step.

Do this before you start on the Pi. It is the only thing that could still change
the whole approach.

---

## Step 3 — Configure the panel

The panel has no keyboard, so this goes through a web page.

1. Connect your phone or laptop to the Wi-Fi network **MarantzKnob-setup**
2. Open <http://192.168.4.1>
3. Fill in your own Wi-Fi, your receiver's IP address, and the list of inputs
   (with PHONO as the favourite)
4. Save — it restarts onto your network

After that the same page lives at <http://marantzpanel.local>, or at whatever
address the monitor shows. **Not** `marantzknob` — that is the Pi.

**Now test it against the amplifier.** Turn the knob: the volume should follow.
Short press is mute, long press is on/off, tapping the input name opens the
input list.

If it does nothing, go back through step 0. Nine times out of ten something else
is still holding that telnet session.

---

## Step 4 — The SD card

Raspberry Pi Imager, **Raspberry Pi OS Lite (64-bit)** — no desktop; it only
costs memory and this machine never gets a screen.

In the gear menu:

| | |
|---|---|
| hostname | `marantzknob` (the panel is `marantzpanel`) |
| SSH | on, with your public key |
| Wi-Fi | your own network |
| user | your own name, not `pi` |

That hostname makes everything below reachable at `marantzknob.local`, even when
the router hands out a different address.

Card in, heatsink on, 27 W adapter into the Pi's USB-C. Wait a minute, then:

```bash
ssh marantzknob.local
```

---

## Step 5 — Set up the Pi

From your computer:

```bash
rsync -a --exclude '.venv' --exclude '._*' --exclude 'data' --exclude '*.stl' \
  ./ marantzknob.local:marantzknob/
```

Then on the Pi. Note the `-t`: the script uses `sudo` and needs to be able to
ask for your password.

```bash
ssh -t marantzknob.local 'cd ~/marantzknob/v2/pi && ./install.sh'
```

It lives in your home directory rather than `/opt` so that copying does not need
root. The script derives every path from its own location, so it works from
anywhere.

That takes a few minutes: packages, a virtualenv, two systemd services, and
reducing writes to the SD card (logs to RAM, swap off). Run it as often as you
like; it is idempotent.

---

## Step 6 — Check the line feed

There is no microphone to plug in. The receiver digitises its own analog inputs
and serves each one over HTTP; the Pi listens to the turntable input. Put a
record on and run:

```bash
ssh marantzknob.local marantzknob/v2/pi/line.sh
```

It asks the receiver which inputs it offers and measures three seconds of each,
so the one with your turntable on it stands out from the rest:

```
  phono           3.1s  peak 0.0740   -36.6 dBFS  <- signal
  cd              3.1s  peak 0.0001   -92.5 dBFS
  tuner           3.1s  peak 0.0001   -92.5 dBFS
```

Put the name of that one in `LINE_INPUT` in `marantzknob-listen.service`. The
default is `phono`, which is right on most receivers.

The script pauses the ears while it runs, because the receiver serves **one**
client at a time and the ears normally hold that connection — without stepping
aside every reading is a scrap of somebody else's stream and everything looks
dead.

Nothing above -60 dBFS with a record playing means either the receiver is not on
the turntable, or that input arrives over HDMI. Only the analog inputs get
digitised.

---

## Step 7 — See whether the Pi runs

```bash
ssh marantzknob.local 'journalctl -u marantzknob-brain -u marantzknob-listen -f'
```

| | |
|---|---|
| web interface | <http://marantzknob.local> |
| raw levels | <http://marantzknob.local/status> |
| listen right now | `curl -X POST http://marantzknob.local/listen` |

In the web interface, enter your Discogs token and sync the collection — the
database does not travel with `rsync`. To keep fingerprints you built up
elsewhere, copy `v2/brain/data/brain.db` across separately and restart the
service.

**Tuning without guessing:** put a record on and watch `/status` to see where
`niveauDb` goes relative to `drempelDb`. The adjustments live in
`marantzknob-listen.service`.

---

## Step 8 — Move the panel onto the Pi

Until now the panel hung off your computer. Move the USB cable to a USB-A port
on the Pi. Everything keeps working: the panel talks to the receiver over Wi-Fi,
the Pi talks to Shazam and Discogs over Wi-Fi.

Now they find each other. The panel polls the Pi every four seconds for what is
playing, and the Pi learns the panel's address from those same requests — there
is nothing to configure. Set `brainHost` in the panel's settings to the Pi's
address and the sleeve appears.

---

## When something does not work

| Symptom | Usually |
|---|---|
| panel says "No receiver" | something else still holds the telnet session (step 0) |
| no serial port appears | BOOT not held long enough, or the wrong cable |
| nothing happens after uploading | press RESET; the chip is still in the bootloader |
| black screen, monitor spews `ESP-ROM` | boot loop — see the appendix |
| black screen, monitor otherwise fine | see [crowpanel/README.md](crowpanel/README.md) |
| wrong colours on the screen | Arduino_GFX is not on v1.3.1 — check `pio pkg list` |
| `marantzknob.local` not found | avahi not up yet; try the IP from your router |
| one input does nothing, others work | that source is set to `DEL` in the receiver |

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
