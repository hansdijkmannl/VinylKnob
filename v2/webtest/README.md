# Web test — trying recognition out

A small web interface for seeing whether music recognition with a microphone
works, and what it looks like with the sleeve and all. No hardware needed,
nothing to learn or enrol: press a button, let music play, see what comes out.

The browser handles the microphone (so macOS asks permission with an ordinary
pop-up) and a little server does the recognition. The same recording goes to
**two engines at once**, so you can compare them directly:

| | |
|---|---|
| **shazamio** | open-source client for Shazam, no key needed, but Python-with-Rust and so only on a computer |
| **AudD** | commercial API that swallows a raw audio upload — and so can be called straight from an ESP32 |

That comparison is why this exists. If AudD does just as well on your records,
the final device can manage without a computer and an ESP32 board is enough. If
AudD disappoints, that is an argument for putting a Raspberry Pi next to it that
can run shazamio.

## Running it

```bash
cd v2/webtest
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Then open <http://localhost:8770>.

**For AudD you need a key.** Get one yourself at audd.io — there is a free tier
— and put it in a file `audd_token.txt` next to `server.py`, or in the
environment variable `AUDD_TOKEN`. Without a key only Shazam takes part, and the
page says so.

**Note the `/usr/bin/python3`**, so Apple's Python 3.9, not your newer one.
shazamio leans on a Rust extension that segfaults on Python 3.14, and on pydub,
which needs the `audioop` module that was taken out of the standard library in
Python 3.13. On 3.9 everything works without contortions.

## What it does

The browser records 8 seconds, turns that into a plain 16-bit WAV in JavaScript
and sends it to the little server. That saves every dependency on ffmpeg at the
server end. Back come two results side by side, each with artist, title, album,
the elapsed time and the sleeve — shown round with a spindle hole in the middle,
the way it would look on the final round screen.

Noise suppression, echo cancellation and automatic gain are deliberately off.
That "clever" processing cuts away exactly the detail recognition leans on.

## How this relates to `../recognizer/`

Two different things, and they do not clash:

- **This** answers "does recognition work with a microphone, and does it look
  right?" It recognises anything, including records you do not own, but it needs
  an internet connection and an external service per lookup.
- **`../recognizer/`** is the own, local fingerprint database that needs no
  service after the first time. That is what ends up running on the Pi.

In the final design they both take part: a service like this one for the cold
start, the local database after that. See [../PLAN.md](../PLAN.md).
