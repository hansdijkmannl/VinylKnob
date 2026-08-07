# VinylKnob

A physical volume knob for a Denon or Marantz receiver that also tells you which
record is playing.

Turn it and the volume follows. Put a record on and the sleeve appears on the
screen — heard on the receiver's own line feed, matched against your own Discogs
collection. Wasn't recognised? Browse your shelf on the knob itself and point at
the album. It links the two and remembers, so next time it knows without asking
anyone.

## What it does

| Gesture | Effect |
|---|---|
| Wake it | the input list: record or Apple TV is the question at that moment, not how loud |
| Turn | volume; turning faster takes bigger steps |
| Hold + turn | step through inputs |
| Short press | mute; on the Apple TV, pause |
| Double press | jump to your favourite input |
| Hold 1 s | back, one level — the same gesture on every screen. From the volume that is the input list |
| Tap the sleeve | browse your record shelf; **BACK** at the bottom leaves without choosing. On the Apple TV input, the same tap gives you its apps |
| Tap the note | listen now |
| Tap the input name, turn to **Settings** | where to reach it, what it is talking to, the brightness |

While a record plays the sleeve fills the screen, with the volume as an arc
around the rim in the sleeve's own dominant colour. The screen goes dark when
the amplifier does and comes back when it returns.

## The Apple TV

The Pi is already paired with it — that is where the artist and title come from
when something plays over HDMI — and the same connection carries commands. So
the knob can drive it, within limits chosen on purpose.

What it does is the part the remote on your sofa is bad at: **starting things**.
Tap the screen while the receiver is on the Apple TV input and you get its apps,
three at a time, the same carousel as the record shelf. Turn, press, and you are
in the app — no walking a grid with a direction pad. Choosing that input also
wakes the Apple TV, and switching everything off puts it back to sleep.

After that the panel goes blind on purpose. Nothing reports back what is focused
over there, so it stops pretending: turning sends left and right, a press
selects, a long press goes back, and you look at the television, which does
know. The moment something starts playing the knob is a volume knob again and
the screen is the ordinary now-playing — a press pauses instead of muting,
because you are watching rather than listening.

What it deliberately is not is a second remote. There is no keyboard on a
480-pixel round screen, no attempt to beat Netflix's own menu, and no Siri
button. Set which input the Apple TV is on in the web interface, under the panel
tab.

There is a web interface at the Pi's address — one page, five tabs: what's
playing (a live copy of the panel's screen), the queue of unrecognised records,
your collection, the panel's settings, and the system.

Getting to it is the awkward part on a device with no keyboard, so the panel
tells you itself: at the bottom of the input list is **Settings**, and its first
page is a QR code with the address written underneath. Turn for the Wi-Fi it is
on, the Pi, the receiver, the brightness, and a way back; press to close. On the
brightness page one press hands the knob over, and it says so — the level fills
the same ring the volume uses, so you set it by feel rather than by reading a
number.

That page appears by itself the moment Wi-Fi comes up, which is when you need it
and cannot look it up anywhere else. It is also the one screen that stays
reachable when there is no receiver or no network — a press of the knob gets you
there — because those are exactly the moments you want an address.

## What you need

Around €150. The full list with the reasoning behind each part is in
[v2/BOM.md](v2/BOM.md).

| Part | What to look for |
|---|---|
| **Elecrow CrowPanel 2.1" ESP32 Rotary Display** | ESP32-S3, 8 MB PSRAM, round 480×480 IPS, capacitive touch, built-in encoder |
| **Raspberry Pi 5** | 1 GB is enough; it listens, recognises and holds your collection |
| microSD card | 32 GB, A1, high-endurance |
| Power supply | the official 27 W USB-C one for a Pi 5, not a generic charger |

The cable from the Pi to the panel comes with the panel. Plain USB-A at the Pi
end, and it carries power and data both — see [How it listens](#how-it-listens)
for the other end of that.

No microphone. See [How it listens](#how-it-listens).

And a **Denon or Marantz receiver with network control**. Any model speaking the
telnet protocol on port 23 should do; in the receiver's menu set *Network →
Network Control* to **Always On**, or the port disappears in standby.

## Two sources

**Records** come off the line feed and are recognised. **Everything over HDMI**
does not need recognising: an Apple TV knows exactly what it is playing, and
[pyatv](https://github.com/postlund/pyatv) asks it. No noise floor, no Shazam,
no waiting — artist, title, album and artwork arrive the moment the track
changes.

Pairing is on the Apple TV tab of the web interface: scan, pick the device,
type the PIN that appears on the television. It wants one for each of two
protocols. The credentials land in `v2/brain/data/appletv.json` and survive a
restart.

The panel switches on its own. With the receiver on the turntable it shows what
the line feed produced; on any other input, whatever the Apple TV reports. When
a track has no artwork — YouTube, a podcast — it shows the app's own logo
instead, fetched once and cached, with the title over it rather than behind it.

One thing nothing can fix from this side: an app may withhold its metadata.
Netflix does. Apple TV+, Music and most others do not.

## How it listens

Denon and Marantz receivers digitise their analog inputs and serve each one as a
plain HTTP stream — the machinery behind sharing an input with HEOS speakers.
The turntable is one of them, so the Pi listens to the record straight off the
phono stage:

```
http://<receiver>:8015/analoginput/analog/analog/0/phono
```

Raw 16-bit stereo PCM at 44.1 kHz, realtime, one client at a time. On an SR7015
the music sits **43 dB** above that input's noise floor; a microphone in the same
room, in the same minute, managed **13 dB**. The fingerprinter is only validated
down to 20 dB, so that is the difference between working by design and working
by luck — and it hears no conversation, no doors and no traffic.

`v2/pi/line.sh` lists what your receiver offers and which input carries signal.
If yours has no such stream, the knob and the screen work as they always did;
only recognition needs it.

## Getting it running

2. **Flash the panel** — see [v2/crowpanel/README.md](v2/crowpanel/README.md).
   Needs PlatformIO. It boots into its own access point called
   `VinylKnob-setup`; connect to it, fill in your network and your receiver's
   address, save.
3. **Set up the Pi** — `v2/pi/install.sh` does the lot: packages, virtualenv,
   both services. It prints the address to open when it is done.
4. **Add your collection** — open the web interface, Collection tab, enter your
   Discogs username and a personal access token (Discogs → Settings →
   Developers), press Sync. After that it re-syncs itself daily.

Step by step, with photos: [v2/BUILD.md](v2/BUILD.md).

## How it fits together

Three parts, each doing what it is good at:

```
   ┌─────────────┐   telnet :23   ┌──────────────┐
   │  CrowPanel  │───────────────▶│   receiver   │
   │  ESP32-S3   │                └──────────────┘
   └──────┬──────┘
          │ HTTP :8791    ┌───────────────┐
          ├──────────────▶│ ears          │  line feed, Apple TV,
          │               │ listen.py    │  web interface
   USB    │               └───────┬───────┘
   power  │                       │ HTTP :8790
          │               ┌───────▼───────┐
   ┌──────┴──────┐        │ brain         │  recognition, Discogs,
   │ Raspberry Pi│        │ server.py     │  fingerprints, database
   └─────────────┘        └───────────────┘
```

The receiver accepts exactly **one** telnet session, and the panel owns it. So
the Pi never talks to the amplifier directly — it asks the panel. The panel in
turn never does recognition — it asks the Pi. Neither guesses about the other's
job.

Your browser only ever sees one address: `/api/*` is passed through to the brain
and `/panel/*` to the panel, so three services look like one page.

The design decisions, and why they went the way they did, are in
[v2/PLAN.md](v2/PLAN.md).

## Recognition, honestly

Records are identified three ways, cheapest first:

1. **Your own fingerprint database.** Costs nothing, needs no network, and grows
   every time you play something. This is the one that matters.
2. **Shazam**, via [shazamio](https://github.com/shazamio/ShazamIO).
3. **AudD**, if you supply a key. Optional and paid.

> **Read this before you run it.** `shazamio` is an unofficial client. A handful
> of lookups an evening is one thing; a hundred installations doing it
> constantly is another, and nobody agreed to provide that service. The listener
> is deliberately frugal — it only listens when sound follows silence on the
> turntable input, gives up after three failed attempts, and stays quiet while
> the amplifier is off — but if you intend to run this at any scale, use AudD
> with your own key, or lean on the local database and link the rest by hand.

Linking by hand is not a chore here. It happens on the knob, while the record is
still spinning, and every link teaches the local database one more side.

A service names the track it heard and then names an album to go with it, and
that second part is its opinion, not yours: for anything with a hit on it the
metadata reaches for a compilation. So the Pi asks your own tracklists first —
which of *your* copies actually carries this song. Usually that is one record
and nothing is asked. When it is more than one, nothing here can tell which
platter is turning, so it asks: the shelf narrows to those two or three sleeves
and you point at the one that is on. If you were not standing there, the same
question is waiting in the queue the next morning, with the candidates already
laid out and one press each.

## Known rough edges

- **There is no enclosure here yet.** It went through nine revisions and is
  still changing too fast to be worth publishing, so nothing is printed from
  this repository. What the shape has to do is in [v2/BOM.md](v2/BOM.md):
  weight in the base and feet under it, or the whole thing walks across the
  table when you turn the knob.
- **The web interface has no password** and listens on your whole network. That
  is a deliberate trade-off for a device on your own LAN — there is nothing in
  it more sensitive than your record collection — but do not forward it through
  your router.
- **It speaks plain HTTP**, and a phone can refuse that. Safari's HTTPS-Only
  will not open the address the panel's QR code gives you; the setting lives
  under Settings → Apps → Safari → Advanced, and takes a per-site exception. A
  self-signed certificate would satisfy the scheme and then fail on the
  certificate instead, which is not an improvement, so it stays as it is.
- **Tested against one receiver**, an SR7015. The protocol is shared across the
  Denon and Marantz range, and the code reads the volume ceiling from the device
  instead of hardcoding it, but nobody has confirmed another model yet. If you
  try one, please say so.
- **Browsing the shelf shows albums; it cannot play them.** This is a knob for a
  turntable. Picking an album puts its sleeve on the screen, and then you get up.

## Repository layout

| | |
|---|---|
| `v2/crowpanel/` | ESP32 firmware — display, encoder, telnet to the receiver |
| `v2/pi/` | the ears: line feed, Apple TV, web interface, installer |
| `v2/brain/` | the brain: recognition, Discogs, fingerprints, database |
| `v2/recognizer/` | standalone fingerprinting prototype, with its own notes |
| `v2/mockup/` | the interface sketch the design came from |
| `logos/` | source logos for the app icons |
| `v2/avr.sh` | poke the receiver's telnet port by hand, before anything else owns it |

Two things run without a receiver or a turntable and are worth running after a
change. The two Python ones need the virtualenv the installer makes (they build
a throwaway database); the page test needs nothing but node.

```bash
.venv/bin/python v2/brain/test_match.py   # a service's answer against your shelf
.venv/bin/python v2/pi/test_ears.py       # what the ears do with no sound
node v2/pi/static/test_page.mjs           # does the web interface hold together
```

## Licence

MIT — see [LICENSE](LICENSE). Do what you like with it; if you build one, I'd
enjoy hearing about it.
