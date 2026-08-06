"""
Proves that recognition works under the conditions that matter for vinyl. Runs
without audio files and without hardware: it makes its own "records".

    python test_roundtrip.py

What gets tested is a range of signal-to-noise ratios, not one arbitrary point.
That way you know not only whether it works but where it gives up.

For scale:

    45-55 dB   normal vinyl in good condition
    35-45 dB   well played, audible surface noise
    25-35 dB   damaged; you would not put it on any more
    below 20   music in hiss, not a realistic scenario

Every variant is also tested played 0.3 % too fast, because that is what a
platter with a stretched belt does - and it is precisely where naive
fingerprinting comes apart.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

import numpy as np

from fingerprint import SAMPLE_RATE, resample_to_working_rate
from store import Store

RNG_ROOT = 20260730

# What we hold it to: at this SNR it still has to work. Well below anything a
# record you would still put on ever reaches.
REQUIRED_SNR_DB = 25.0
MIN_SCORE = 20
MIN_MARGIN = 4.0


def make_side(seed: int, seconds: float = 90.0) -> np.ndarray:
    """Builds something enough like music to fingerprint.

    What matters is that the sound is *continuous*. An earlier version used
    short decaying notes with silence between them; that left most frames
    holding nothing but noise, which makes peak detection artificially
    unreliable. A record is nearly always full of sound.

    So: sustained chords that flow into one another, a continuous bass line and
    a soft percussive click for broadband content.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    out = np.zeros(n, dtype=np.float32)

    # Each record gets its own scale from a larger pool. Records differ in key
    # and instrumentation; building them all from the same eight notes would
    # make them resemble one another unrealistically closely.
    pool = 110.0 * 2.0 ** (np.arange(36) / 12.0)
    scale = rng.choice(pool, size=8, replace=False)

    # Chords of 1.5 s that overlap by half a second.
    hold = int(1.5 * SAMPLE_RATE)
    step = int(1.0 * SAMPLE_RATE)

    for start in range(0, n, step):
        stop = min(start + hold, n)
        seg = slice(start, stop)
        m = stop - start
        ramp = np.linspace(0, 1, m, dtype=np.float32)
        # Attack, sustain, decay - not a hard exponential fall.
        envelope = np.minimum(ramp * 12.0, 1.0) * (1.0 - 0.6 * ramp)

        for root in rng.choice(scale, size=3, replace=False):
            for harmonic in (1, 2, 3, 4, 5, 7):
                amp = 0.3 / harmonic
                out[seg] += amp * envelope * np.sin(
                    2 * np.pi * root * harmonic * t[seg] + rng.uniform(0, 6.28)
                ).astype(np.float32)

    # A continuous bass, so there is content between the chords too.
    bass_root = float(rng.choice(scale)) / 2.0
    out += 0.25 * np.sin(2 * np.pi * bass_root * t).astype(np.float32)

    # A soft click on the beat: broadband content, like percussion.
    beat = int(0.5 * SAMPLE_RATE)
    click = np.exp(-np.linspace(0, 8, 400, dtype=np.float32))
    for start in range(0, n - 400, beat):
        out[start:start + 400] += 0.15 * click * rng.standard_normal(400).astype(np.float32)

    return out / np.max(np.abs(out))


def add_surface_noise(samples: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """Surface noise at a given SNR, plus the occasional click."""
    rng = np.random.default_rng(seed)
    signal_rms = float(np.sqrt(np.mean(samples ** 2)))
    noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))

    noisy = samples + noise_rms * rng.standard_normal(len(samples)).astype(np.float32)
    for pos in rng.integers(0, len(samples) - 16, size=40):
        noisy[pos:pos + 12] += rng.uniform(-0.4, 0.4)
    return np.clip(noisy, -1.0, 1.0)


def change_speed(samples: np.ndarray, factor: float) -> np.ndarray:
    """Simulates a platter running `factor` too fast."""
    return resample_to_working_rate(samples, SAMPLE_RATE, speed=factor)


def evaluate(store: Store, audio: np.ndarray, expect_side_id: int):
    t0 = time.time()
    results = store.identify(audio)
    elapsed = time.time() - t0
    if not results:
        return None, 0, 0.0, elapsed

    best = results[0]
    runner_up = results[1].score if len(results) > 1 else 0
    _ = runner_up
    margin = best.score / runner_up if runner_up else float("inf")
    ok = best.side_id == expect_side_id and best.score >= MIN_SCORE and margin >= MIN_MARGIN
    return best, ok, margin, elapsed


def main() -> int:
    print("Making and enrolling five sides...")
    tmp = os.path.join(tempfile.mkdtemp(), "test.db")
    store = Store(tmp)

    # The reference is itself a needle recording, with surface noise of its own.
    # That is exactly how the device builds its database, and it is why this
    # approach works better on vinyl than matching against a digital master.
    sides = {}
    t0 = time.time()
    for i in range(5):
        music = make_side(RNG_ROOT + i)
        sides[i] = music
        reference = add_surface_noise(music, 45.0, seed=500 + i)
        # Full density: this test measures the quality of the algorithm. What
        # thinning does to the database size is in experiment_window.py.
        store.enroll(reference, label=f"Test record {i + 1} - side A", keep_one_in=1)
    build = time.time() - t0
    print(f"  {store.hash_count():,} hashes from 5 x 90 s, {build:.1f} s "
          f"({store.hash_count() / 5:,.0f} per side)\n")

    # A clip as the device would record it: 15 seconds, somewhere during play.
    # Record 3, from 30 seconds in.
    target = 2
    expect_id = target + 1
    excerpt = sides[target][int(30 * SAMPLE_RATE):int(45 * SAMPLE_RATE)]

    print(f"{'SNR':>8}  {'speed':>9}  {'verdict':<7} {'score':>7} {'margin':>8} "
          f"{'position':>9} {'time':>7}")
    print("-" * 62)

    ok_by_snr: dict[float, list[bool]] = {}
    failures_in_scope = 0

    for snr_db in (None, 45.0, 35.0, 25.0, 20.0, 15.0, 10.0):
        for speed, speed_label in ((1.0, "normal"), (1.003, "+0.3 %")):
            # Different noise from the enrolment: a second time round.
            audio = excerpt if snr_db is None else add_surface_noise(excerpt, snr_db, 99)
            if speed != 1.0:
                audio = change_speed(audio, speed)

            best, ok, margin, elapsed = evaluate(store, audio, expect_id)
            snr_label = "clean" if snr_db is None else f"{snr_db:.0f} dB"

            if best is None:
                print(f"{snr_label:>8}  {speed_label:>9}  {'NONE':<7}")
            else:
                print(f"{snr_label:>8}  {speed_label:>9}  {'ok' if ok else 'WRONG':<7} "
                      f"{best.score:>7} {margin:>7.1f}x {best.offset_seconds:>8.1f}s "
                      f"{elapsed:>6.2f}s")

            if snr_db is not None:
                ok_by_snr.setdefault(snr_db, []).append(bool(ok))
            if not ok and snr_db is not None and snr_db >= REQUIRED_SNR_DB:
                failures_in_scope += 1

    store.close()
    print()

    # Only SNRs where *both* speed variants came out right count.
    solid = [snr for snr, results in ok_by_snr.items() if all(results)]
    if solid:
        print(f"Faultless down to {min(solid):.0f} dB SNR, with and without a "
              f"speed deviation.")
    if failures_in_scope:
        print(f"FAILED: {failures_in_scope} case(s) at {REQUIRED_SNR_DB:.0f} dB "
              f"or better came out wrong.")
        return 1
    print(f"Requirement met: faultless at {REQUIRED_SNR_DB:.0f} dB and better, "
          f"well below what real vinyl reaches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
