# The Pi: ears and brain

Two services run here. The **brain** ([../brain/](../brain/)) does recognition,
Discogs and the database. The **ears** (`listen.py`) listen on the receiver's
line feed, talk to the Apple TV, and serve the web interface.

## Setting it up

### 1. Write the card

Raspberry Pi Imager, **Raspberry Pi OS Lite (64-bit)**. No desktop — it costs
memory and this machine never gets a screen.

Set these in the gear menu before writing:

| | |
|---|---|
| hostname | `marantzknob` |
| SSH | on, with your public key |
| Wi-Fi | your network (or just use ethernet) |
| user | your own name, not `pi` |

That hostname matters: everything below is then reachable at
`marantzknob.local` even when the router hands out a different address.

### 2. Copy it over and install

```bash
rsync -av --exclude '.venv' --exclude '._*' ./ marantzknob.local:marantzknob/
ssh marantzknob.local
cd marantzknob/v2/pi && ./install.sh
```

The script is idempotent — running it again is always safe. It installs
packages, builds a virtualenv, registers both services, and reduces writes to
the SD card (logs to RAM, swap off; see
[../BOM.md](../BOM.md) for why that matters more than a faster card).

`numpy` and `scipy` come from `apt` rather than `pip` on purpose: building scipy
on a Pi 5 with 1 GB takes over an hour and barely fits in memory.

### 3. Check the line feed

Put a record on and run:

```bash
./line.sh
```

There is no microphone. The receiver digitises its own analog inputs and serves
each one over HTTP — see [../BOM.md](../BOM.md) — and this asks yours which it
offers, then measures three seconds of each so the turntable one stands out:

```
  phono           3.1s  peak 0.0740   -36.6 dBFS  <- signal
  cd              3.1s  peak 0.0001   -92.5 dBFS
```

Put that name in `LINE_INPUT` in `marantzknob-listen.service`; `phono` is the
default and right on most receivers.

The script pauses the ears while it runs. The receiver serves one client at a
time and the ears normally hold that connection, so without stepping aside every
reading is a scrap of somebody else's stream.

### 4. See whether it runs

```bash
journalctl -u marantzknob-brain -u marantzknob-listen -f
```

| | |
|---|---|
| web interface | <http://marantzknob.local> |
| raw levels as JSON | <http://marantzknob.local/status> |
| listen right now | `curl -X POST http://marantzknob.local/listen` |

`/status` gives you `niveauDb`, `ruisvloerDb` and `drempelDb` — level, noise
floor and threshold. That is how you tune without guessing: put a record on,
watch where the level goes, compare it with the threshold.

### 5. Your Discogs token and collection

The database does not travel with `rsync`; it lives in `brain/data/`. On the Pi,
open the web interface, enter your Discogs token again and sync. If you want to
bring fingerprints you built up elsewhere, copy `brain/data/brain.db` across
before starting the service.

## The web interface

One page, five tabs, served on port 80 and 8791. What sits underneath is still
split up — the queue and the collection come from the brain on 8790 (passed
through under `/api/`), the panel's settings from the panel itself (under
`/panel/`) — but the browser sees one address, and that saves remembering three
port numbers.

**Now** carries a copy of the panel's screen, at full size and on the same data:
the same sleeve from `/artwork`, the same accent colour from the same calculation
as `findAccent()` in `crowpanel/src/artwork.cpp`, and the same choice between the
dB reading, the title, or nothing but the sleeve as in `uiRender()`. Change the
layout there and it should change here too.

**Collection** has the shelf as a round browser: sleeves in a row, the jump
index as a ring of letters along the inner rim with the gap at the bottom.
Scroll, drag, or tap a letter. The search box below filters the browser too, so
searching and browsing work on the same list.

**Panel** is the panel's own settings page, rebuilt. Among them: the screen
follows the amplifier, so when the main zone goes off — by remote, or by your
Apple TV over HDMI — the display goes with it, and comes back when it returns.

## How the listening works

Lookups happen **on an event, not a timer**: sound after silence. That is the
moment you put the needle down.

Why it has to be that way is in [../PLAN.md](../PLAN.md): shazamio is an
unofficial client, and a handful of lookups an evening does not look like
hundreds. It is also pointless — a side lasts twenty minutes and does not change
its name in the meantime.

And it works without this service knowing anything about the amplifier. That is
not a coincidence but a requirement: the receiver allows exactly one telnet
session, and the panel owns it.

**Two thresholds, and they do different jobs.** `TRIGGER_DB` is relative — so
far above the quiet — and decides that *something started*. `MIN_LEVEL_DB` is
absolute and decides whether there is *enough to identify*. Without the second,
hum and a needle in the run-out groove clear the first easily and spend a lookup
that cannot succeed; every one of those burns an attempt and leaves an unknown
in the queue. `/status` reports the higher of the two as `thresholdDb`, so the
meter on the page shows what the loop really uses.

Both are on the automatic path only. Tapping the note on the panel or the button
on the page goes past all of it — you have decided there is something to hear.

**The floor follows the signal.** The noise floor tracks the quiet and
triggers a set number of decibels above it. The floor falls quickly and rises
very slowly, and only while the level is close to it — otherwise a minute of
continuous music *becomes* the floor and the margin you need disappears.

**The clock counts audio, not wall time.** Every block is exactly 0.1 s of
sound, and all the thresholds run on that. It looks like a detail and is not:
with `time.time()`, a stall in the stream could skip a side or ask again in the
middle of one.

Tuning lives in `marantzknob-listen.service`:

| | Default | For |
|---|---|---|
| `TRIGGER_DB` | 15 | how far above the noise floor counts as music |
| `MIN_LEVEL_DB` | -60 | quieter than this is not worth asking about at all |
| `FLOOR_MAX_DB` | -55 | the noise floor can never be claimed to be higher |
| `START_SECONDS` | 2.5 | how long sound must last before it "is playing" |
| `SETTLE_SECONDS` | 4 | letting the needle settle before sampling |
| `CLIP_SECONDS` | 15 | length of the recording sent for lookup |
| `QUIET_SECONDS` | 15 | how much silence means the side has ended |
| `RETRY_SECONDS` | 60 | wait before trying an unrecognised side again |
| `MAX_RETRIES` | 3 | give up after this many failures in a row |
| `COVER_HOLD_SECONDS` | 300 | how long the sleeve stays after the last sound |

Then `systemctl daemon-reload && systemctl restart marantzknob-listen`.

`MAX_RETRIES` is worth understanding. Without a limit the retry loop runs for as
long as there is any sound at all, and a talking video on the television once
produced forty-five empty lookups in a single morning, one every seventy-five
seconds. Three attempts is plenty for a record — the first sample can be a quiet
intro — and if three fail, there is no record playing.

## Why `web.py` exists

`../brain/server.py` binds to `127.0.0.1`. On a laptop that is right; on a
headless Pi it means you cannot reach it. `web.py` intercepts only that choice
and leaves everything else alone. If you ever want it tidier: make the host a
setting in `server.py` and delete this file.

Note that this leaves the web interface **open on your whole network with no
password**. For this device that is a deliberate trade-off — there is nothing in
it more sensitive than your record collection — but do not forward it through
your router.

## Troubleshooting

### Wi-Fi does not survive the first reboot

Pi OS images from 2026 configure Wi-Fi through **cloud-init**, with a
`network-config` on the boot partition. That works on first boot, but cloud-init
does not record it anywhere NetworkManager will find it:
`/etc/NetworkManager/system-connections/` stays empty and the netplan file NM
generates is zero bytes. After the first reboot the Wi-Fi is gone.

What makes this confusing is how it presents: the Pi does nothing on the network
while the panel comes up perfectly — it hangs off the USB port and gets power
before Linux does anything. It looks like a dead SD card when nothing is wrong.

To confirm: **plug in an ethernet cable.** If it appears, Linux is fine and this
is purely Wi-Fi. To fix it, using the PSK already in `network-config` on the
boot partition (those 64 characters are the key itself, not a password you need
to know):

```bash
sudo nmcli connection add type wifi con-name <SSID> ifname wlan0 ssid <SSID> \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk <64-chars-from-network-config> \
  connection.autoconnect yes
```

That profile lands in `/etc/NetworkManager/system-connections/` and does survive
a reboot.

### Everything ends up unrecognised, with no error

Check that `ffmpeg` is installed. shazamio has pydub convert the recording, and
without ffmpeg that fails **silently** — no error, just a queue filling up. The
installer now verifies that `import shazamio` actually works, for this reason.

Related: Pi OS Lite 64-bit is Debian 13 with Python 3.13, which removed
`audioop` from the standard library. pydub imports it in three places, so
`audioop-lts` is installed alongside.

### The serial connection to the panel

Measured with the panel on the Pi's USB:

```
/dev/ttyACM0    crw-rw---- root dialout
Bus 001 Device 002: ID 303a:1001 Espressif USB JTAG/serial debug unit
```

That one cable really does carry power **and** a serial connection, which is
what `flash-via-pi.sh` uses. No separate wire to the UART header is needed.

If you want the GPIO UART anyway: `cmdline.txt` contains
`console=serial0,115200`, so a login console is sitting on it. That has to go
first.
