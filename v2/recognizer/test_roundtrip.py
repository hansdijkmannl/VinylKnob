"""
Bewijst dat het herkennen werkt onder de omstandigheden die er voor vinyl toe
doen. Draait zonder audiobestanden en zonder hardware: het maakt zijn eigen
"platen".

    python test_roundtrip.py

Wat er getest wordt is een reeks signaal-ruisverhoudingen, niet één willekeurig
punt. Zo weet je niet alleen of het werkt maar ook waar het ophoudt.

Ter ijking:

    45-55 dB   normale vinyl in goede staat
    35-45 dB   flink gedraaid, hoorbare oppervlakteruis
    25-35 dB   beschadigd; je zou hem niet meer opzetten
    onder 20   muziek in geruis, geen realistisch scenario

Elke variant wordt ook op 0,3 % te snel afgespeeld getest, want dat is wat een
plateau met een uitgerekte snaar doet - en dat is precies waar naïeve
fingerprinting op stukloopt.
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

# Waar we op afrekenen: bij deze SNR moet het nog goed gaan. Ruim onder wat een
# plaat die je nog opzet ooit haalt.
REQUIRED_SNR_DB = 25.0
MIN_SCORE = 20
MIN_MARGIN = 4.0


def make_side(seed: int, seconds: float = 90.0) -> np.ndarray:
    """Bouwt iets dat genoeg op muziek lijkt om te fingerprinten.

    Belangrijk is dat het geluid *continu* is. Een eerdere versie gebruikte
    kort wegstervende noten met stilte ertussen; daardoor bestond het grootste
    deel van de frames uit alleen maar ruis, en dat maakt piekdetectie
    kunstmatig onbetrouwbaar. Een plaat staat vrijwel altijd vol geluid.

    Dus: aangehouden akkoorden die in elkaar overlopen, een doorlopende baslijn
    en een zachte percussieve tik voor breedbandige inhoud.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    out = np.zeros(n, dtype=np.float32)

    # Elke plaat krijgt zijn eigen toonladder uit een grotere voorraad. Platen
    # verschillen in toonsoort en bezetting; ze allemaal uit dezelfde acht noten
    # opbouwen zou ze onrealistisch veel op elkaar laten lijken.
    pool = 110.0 * 2.0 ** (np.arange(36) / 12.0)
    scale = rng.choice(pool, size=8, replace=False)

    # Akkoorden van 1,5 s die een halve seconde overlappen.
    hold = int(1.5 * SAMPLE_RATE)
    step = int(1.0 * SAMPLE_RATE)

    for start in range(0, n, step):
        stop = min(start + hold, n)
        seg = slice(start, stop)
        m = stop - start
        ramp = np.linspace(0, 1, m, dtype=np.float32)
        # Aanslag, aanhouden, wegvallen - geen harde exponentiele val.
        envelope = np.minimum(ramp * 12.0, 1.0) * (1.0 - 0.6 * ramp)

        for root in rng.choice(scale, size=3, replace=False):
            for harmonic in (1, 2, 3, 4, 5, 7):
                amp = 0.3 / harmonic
                out[seg] += amp * envelope * np.sin(
                    2 * np.pi * root * harmonic * t[seg] + rng.uniform(0, 6.28)
                ).astype(np.float32)

    # Doorlopende bas, zodat er ook tussen de akkoorden door inhoud is.
    bass_root = float(rng.choice(scale)) / 2.0
    out += 0.25 * np.sin(2 * np.pi * bass_root * t).astype(np.float32)

    # Zachte tik op de tel: breedbandige inhoud, zoals percussie.
    beat = int(0.5 * SAMPLE_RATE)
    click = np.exp(-np.linspace(0, 8, 400, dtype=np.float32))
    for start in range(0, n - 400, beat):
        out[start:start + 400] += 0.15 * click * rng.standard_normal(400).astype(np.float32)

    return out / np.max(np.abs(out))


def add_surface_noise(samples: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """Oppervlakteruis op een gegeven SNR, plus af en toe een tik."""
    rng = np.random.default_rng(seed)
    signal_rms = float(np.sqrt(np.mean(samples ** 2)))
    noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))

    noisy = samples + noise_rms * rng.standard_normal(len(samples)).astype(np.float32)
    for pos in rng.integers(0, len(samples) - 16, size=40):
        noisy[pos:pos + 12] += rng.uniform(-0.4, 0.4)
    return np.clip(noisy, -1.0, 1.0)


def change_speed(samples: np.ndarray, factor: float) -> np.ndarray:
    """Simuleert een plateau dat `factor` te snel draait."""
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
    print("Vijf kanten aanmaken en vastleggen...")
    tmp = os.path.join(tempfile.mkdtemp(), "test.db")
    store = Store(tmp)

    # De referentie is zelf ook een naaldopname, met eigen oppervlakteruis. Dat
    # is precies hoe het apparaat zijn database opbouwt, en het is de reden dat
    # deze aanpak op vinyl beter werkt dan matchen tegen een digitale master.
    sides = {}
    t0 = time.time()
    for i in range(5):
        music = make_side(RNG_ROOT + i)
        sides[i] = music
        reference = add_surface_noise(music, 45.0, seed=500 + i)
        # Volle dichtheid: deze test meet de kwaliteit van het algoritme.
        # Wat uitdunnen met de databaseomvang doet staat in experiment_window.py.
        store.enroll(reference, label=f"Testplaat {i + 1} - kant A", keep_one_in=1)
    build = time.time() - t0
    print(f"  {store.hash_count():,} hashes uit 5 x 90 s, {build:.1f} s "
          f"({store.hash_count() / 5:,.0f} per kant)\n")

    # Fragment zoals het apparaat het zou opnemen: 15 seconden, ergens tijdens
    # het afspelen. Plaat 3, vanaf 30 seconden.
    target = 2
    expect_id = target + 1
    excerpt = sides[target][int(30 * SAMPLE_RATE):int(45 * SAMPLE_RATE)]

    print(f"{'SNR':>8}  {'snelheid':>9}  {'uitslag':<7} {'score':>7} {'marge':>8} "
          f"{'positie':>9} {'tijd':>7}")
    print("-" * 62)

    ok_by_snr: dict[float, list[bool]] = {}
    failures_in_scope = 0

    for snr_db in (None, 45.0, 35.0, 25.0, 20.0, 15.0, 10.0):
        for speed, speed_label in ((1.0, "normaal"), (1.003, "+0,3 %")):
            # Andere ruis dan bij het vastleggen: een tweede keer afspelen.
            audio = excerpt if snr_db is None else add_surface_noise(excerpt, snr_db, 99)
            if speed != 1.0:
                audio = change_speed(audio, speed)

            best, ok, margin, elapsed = evaluate(store, audio, expect_id)
            snr_label = "schoon" if snr_db is None else f"{snr_db:.0f} dB"

            if best is None:
                print(f"{snr_label:>8}  {speed_label:>9}  {'GEEN':<7}")
            else:
                print(f"{snr_label:>8}  {speed_label:>9}  {'ok' if ok else 'FOUT':<7} "
                      f"{best.score:>7} {margin:>7.1f}x {best.offset_seconds:>8.1f}s "
                      f"{elapsed:>6.2f}s")

            if snr_db is not None:
                ok_by_snr.setdefault(snr_db, []).append(bool(ok))
            if not ok and snr_db is not None and snr_db >= REQUIRED_SNR_DB:
                failures_in_scope += 1

    store.close()
    print()

    # Alleen SNR's waar *beide* snelheidsvarianten goed gingen tellen mee.
    solid = [snr for snr, results in ok_by_snr.items() if all(results)]
    if solid:
        print(f"Foutloos tot en met {min(solid):.0f} dB SNR, met en zonder "
              f"snelheidsafwijking.")
    if failures_in_scope:
        print(f"MISLUKT: {failures_in_scope} geval(len) op {REQUIRED_SNR_DB:.0f} dB "
              f"of beter gingen fout.")
        return 1
    print(f"Eis gehaald: foutloos op {REQUIRED_SNR_DB:.0f} dB en beter, "
          f"ruim onder wat echte vinyl haalt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
