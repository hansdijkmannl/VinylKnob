# Recognizer — working prototype

Fingerprinting record sides, like Shazam but for one record shelf. Runs without
any hardware; this was deliberately the first thing built, because it was the
only part of the project where it was not certain it *could* be done.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python test_roundtrip.py      # synthetic check
.venv/bin/python listen.py selftest     # the pipeline without a microphone
```

| File | |
|---|---|
| `fingerprint.py` | spectrogram → peaks → landmark hashes |
| `store.py` | SQLite storage and the matching |
| `test_roundtrip.py` | makes its own "records" and measures where it gives up |
| `experiment_window.py` | how much of a side you need to enrol |
| `listen.py` | testing with your Mac's microphone, on real music |

## Does it work?

Yes. From `test_roundtrip.py`, with five sides in the database and a 15-second
clip taken from 30.0 s into record 3:

```
     SNR      speed  verdict   score   margin   position
   clean     normal  ok         2082    11.6x     30.0s
   45 dB     normal  ok         1130     7.7x     30.0s
   45 dB     +0.3 %  ok          415     5.5x     30.0s
   25 dB     normal  ok          801     6.7x     30.0s
   25 dB     +0.3 %  ok          357     4.4x     30.0s
   10 dB     normal  ok          653     5.4x     30.0s
```

Faultless down to 20 dB SNR, with and without a speed deviation. For scale:
normal vinyl sits at 45-55 dB, a record you would no longer put on at 25-35.
The recovered time position is exactly 30.0 s throughout — so it knows not only
*which* record it is but also where the needle is.

## Testing on real music

Everything above was measured on synthetic material. `listen.py` uses your Mac's
microphone, so you can test it on real music without ordering anything.

```bash
.venv/bin/python listen.py trial            # guided trial session - start here
.venv/bin/python listen.py devices          # which microphones does it see
.venv/bin/python listen.py learn "Name"     # record 60 s and enrol it
.venv/bin/python listen.py id               # record 15 s: what is this?
.venv/bin/python listen.py watch            # keep listening
.venv/bin/python listen.py list             # show the database
.venv/bin/python listen.py forget 3         # throw a link away
```

While recording there is a level meter, so you can see straight away whether
anything is coming in. If nothing does: **System Settings → Privacy & Security →
Microphone**, and switch your terminal on.

`trial` walks you through the three steps that matter, with a database of its
own that is emptied each time:

1. Put a track on and let it enrol
2. Let it run on — it should recognise it again, with the right time position
3. **Put something completely different on** — it should say "Nothing
   recognised"

That third step is the important one. Recognising something is easy; recognising
*nothing* when there is nothing there is where weak fingerprinting comes apart.
That is why `listen.py` gives three outcomes (certain / doubtful / unknown)
rather than always a best guess, and shows numbers two and three as well.

`learn` enrols everything by default here (`--density 1`). If that works, try
`--density 4` — that is the setting at which a whole collection fits in a Pi's
memory.

## What it cost along the way

Measured and adjusted four times. The outcomes are worth keeping, because they
are exactly the things you do not get from a tutorial.

**Logarithmic frequency bands solve the speed problem.** A platter running 0.3 %
fast shifts every frequency by 0.3 %; in linear FFT bins that is three bins over
at 1 kHz and it breaks every hash. In bands an eighth of a tone wide (1.45 %),
such a shift stays inside the same band. This alone took the margin from 1.3× to
10.9×.

**But not *too* coarse.** Quarter-tone bands (24 per octave) gave only ~130
bands, so the hash space saturated and every record looked like every other one
— high scores, margin 1.0×. 48 bands per octave is the workable middle.

**The peak window in time was the biggest mistake.** At 20 frames (~0.9 s) a
peak has to dominate a whole second. So few survived that each one was marginal:
across two plays, 8 % of the peaks survived. At 3 frames that became 23 %.

**And the decider: the instability is in time, not in frequency.** Measuring
with tolerance showed that ±1 band barely improves the overlap (16 → 17 %), but
±1 frame doubles it (17 → 44 %). A peak inside a sustained note moves one frame
under noise. Because a hash needs *two* peaks, that is the difference between
3 % and 19 % usable hashes — which is to say, between not working and working.
The fix is `DT_TOLERANCE`: on lookup every hash is also emitted with a time
difference of ±1, and the alignment adds three neighbouring buckets together.
Enrolling stays exact, so the database does not grow from it.

## How much of a side do you enrol?

Shazam needs only ~10 seconds — but that is the length of the **recording you
make**, not of what is in the database. Shazam has the whole track enrolled, and
that is precisely why you can start it in the middle of a song.

Enrol only the beginning of a side and you only recognise it while the needle is
there. From `experiment_window.py`, five-minute sides, listening at three
positions:

```
variant                 h/s  RAM 400 alb        @10s        @60s       @200s
first 45 s              513       3938 MB   999/ 5.3x   425/ 2.9x?  447/ 2.5x?
first 90 s              542       4164 MB   999/ 5.3x  1010/ 5.5x   487/ 2.7x?
whole side              605       4643 MB   999/ 5.1x  1010/ 5.0x  1231/ 5.9x
whole side, 1 in 4      152       1165 MB   271/ 4.6x   260/ 4.3x   287/ 4.6x
whole side, 1 in 8       77        591 MB   138/ 3.1x?  134/ 3.7x?  143/ 3.8x?
whole side, 1 in 16      37        285 MB    59/ 3.5x?   55/ 3.1x?   62/ 3.3x?
```

**Thinning out is a better knob than cutting off.** Enrolling the whole side at
one hash in four gives full coverage at a margin no worse than a 90 s window —
and that window abandons you the moment the needle moves on. Hence `enroll` now
uses `keep_one_in=4` by default and enrols the whole side.

Two caveats about this table: the synthetic records each share one scale, so a
part that was not enrolled still resembles the enrolled part too closely — on
real music those window rows at @200s will more likely produce a MISS than a
weak hit. And the margins were measured against four competitors; with eight
hundred sides the strongest coincidental hit gets higher and they drop.

## Where it gives up

With 100 sides of 90 s at full density:

```
4,760,532 hashes, database 152 MB
45 dB: correct, margin 4.8x, search time 1.8 s
30 dB: correct, margin 4.0x, search time 2.0 s
```

Still good, but the margin drops from ~7× to ~4.8× and the search time climbs.
Extrapolated to 400 albums (800 sides) that becomes ~1.2 GB and, on a Pi Zero,
soon half a minute per lookup. **That is the limit of this design and the next
thing to be tackled.**

The approach is obvious and not large:

1. **An index in memory instead of SQLite rows.** 5 million hashes is 40 MB as a
   sorted numpy array; `np.searchsorted` does in milliseconds what the current
   Python loop does in seconds. This is almost certainly a factor of 20-50, and
   most of the work is in loading it at startup.
2. **Filter coarsely first, in two stages.** Keep a thinned index in memory (say
   one hash in 32 — for eight hundred sides about 40 MB), use it to pick ten
   candidate sides, and only then read the full hashes of those candidates from
   disk. That is a contiguous stretch of file per side, so a sequential read. The
   naive variant — leaving the whole index on disk and seeking around in it — is
   what comes apart, because that turns into tens of thousands of separate reads.
3. **Thin out further.** From one in four to one in eight halves everything, at
   the cost of margin (4.5x to 3.5x). See the table above.

## The settings that matter

All of them at the top of `fingerprint.py`, with the measurements behind them.

| | | |
|---|---|---|
| `BANDS_PER_OCTAVE` | 48 | finer = more entropy, coarser = more speed tolerance |
| `PEAK_BOX_TIME` | 3 | larger = fewer and less stable peaks |
| `MAX_PEAKS_PER_FRAME` | 10 | sets the size of the database almost linearly |
| `DT_TOLERANCE` | 1 | 0 makes it unusable; higher only costs query time |
| `enroll(keep_one_in=)` | 4 | the most important knob for database size |
| `enroll(seconds=)` | None | whole side; cutting off costs coverage, see above |

## Not done yet

- The in-memory index (see above) — the real next piece of work
- Redetermining the thinning factor once there are hundreds of real sides in it
- Reading audio from the device; for now only wav files and numpy arrays
- Hooking up Discogs and the web interface to tag unrecognised sides
- Tested on **real** needle recordings. Everything above was measured on
  synthetic material with realistic noise and speed deviation. That is enough to
  trust the approach, not enough to sign it off.
