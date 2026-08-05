#!/usr/bin/env python3
"""
Luisteren met de microfoon van je MacBook - de echte proef op de som.

Alles tot nu toe is gemeten op synthetisch materiaal. Dit is het gereedschapje
om te toetsen of het ook op echte muziek en een echte microfoon werkt, zonder
dat er ook maar iets besteld hoeft te worden.

    python listen.py proef                begeleide proefsessie - begin hier
    python listen.py devices              welke microfoons ziet hij
    python listen.py learn "Naam"         60 s opnemen en vastleggen
    python listen.py id                   15 s opnemen: wat is dit?
    python listen.py watch                blijven luisteren, zoals het apparaat
    python listen.py list                 wat zit er in de database
    python listen.py forget 3             een verkeerde koppeling weggooien
    python listen.py selftest             pijplijn testen zonder microfoon

Een zinnige eerste sessie:

    1. zet een plaat of nummer op
    2. `learn "Artiest - Album kant A"`
    3. zet het nummer ergens anders neer, of laat het gewoon doorlopen
    4. `id`  -> hij moet de goede naam geven, met de juiste tijdpositie
    5. zet iets heel anders op en `id` opnieuw -> hij moet niets vinden

Die laatste stap is de belangrijkste. Iets herkennen is makkelijk; niets
herkennen wanneer het er niet is, is waar zwakke fingerprinting op stukloopt.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from fingerprint import SAMPLE_RATE, resample_to_working_rate
from store import Store

RECORD_RATE = 44100
DB_PATH = "collection.db"

# Wanneer noemen we een treffer betrouwbaar. Onderbouwing staat in README.md.
SURE_SCORE, SURE_MARGIN = 30, 4.0
MAYBE_SCORE, MAYBE_MARGIN = 12, 2.0


def die(message: str) -> "NoReturn":  # noqa: F821
    print(f"\n{message}", file=sys.stderr)
    raise SystemExit(1)


def record(seconds: float, quiet: bool = False, strict: bool = True) -> np.ndarray:
    """Neemt op van de standaard-microfoon en zet om naar de werkfrequentie."""
    try:
        import sounddevice as sd
    except ImportError:
        die("sounddevice ontbreekt. Installeren met:\n"
            "    pip install sounddevice")

    frames = int(seconds * RECORD_RATE)
    buffer = sd.rec(frames, samplerate=RECORD_RATE, channels=1, dtype="float32")

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed >= seconds:
            break
        time.sleep(0.25)
        if quiet:
            continue
        # Niveau van de laatste seconde tonen, zodat je ziet dat er iets
        # binnenkomt voordat je twintig seconden voor niets staat te wachten.
        done = min(int(elapsed * RECORD_RATE), frames)
        window = buffer[max(0, done - RECORD_RATE):done, 0]
        peak = float(np.max(np.abs(window))) if len(window) else 0.0
        db = 20 * np.log10(peak) if peak > 1e-6 else -99.0
        bars = int(np.clip((db + 60) / 60 * 30, 0, 30))
        print(f"\r  {elapsed:4.1f}/{seconds:.0f}s  "
              f"[{'#' * bars}{' ' * (30 - bars)}] {db:6.1f} dBFS", end="", flush=True)

    sd.wait()
    if not quiet:
        print()

    audio = buffer[:, 0]
    peak = float(np.max(np.abs(audio)))
    if peak < 3e-3 and strict:
        die("Er kwam vrijwel geen geluid binnen.\n"
            "  - staat de muziek aan en hard genoeg?\n"
            "  - heeft je terminal toegang tot de microfoon?\n"
            "    Systeeminstellingen > Privacy en beveiliging > Microfoon\n"
            "  - `python listen.py devices` laat zien wat er gekozen is")

    return resample_to_working_rate(audio, RECORD_RATE)


def verdict(results) -> tuple[str, float]:
    """Betrouwbaar, twijfelachtig of onbekend."""
    if not results:
        return "onbekend", 0.0
    best = results[0]
    runner_up = results[1].score if len(results) > 1 else 0
    margin = best.score / runner_up if runner_up else float("inf")

    if best.score >= SURE_SCORE and margin >= SURE_MARGIN:
        return "zeker", margin
    if best.score >= MAYBE_SCORE and margin >= MAYBE_MARGIN:
        return "twijfel", margin
    return "onbekend", margin


def show(results, elapsed: float) -> None:
    level, margin = verdict(results)

    if level == "onbekend":
        print(f"  Niets herkend.  ({elapsed:.1f}s)")
        if results:
            best = results[0]
            print(f"    beste gok was {best.label} met score {best.score}, "
                  f"marge {margin:.1f}x - te zwak")
        return

    best = results[0]
    mark = "==>" if level == "zeker" else " ? "
    minutes, seconds = divmod(max(best.offset_seconds, 0.0), 60)
    print(f"  {mark} {best.label}")
    print(f"      naald op {int(minutes)}:{seconds:04.1f}  "
          f"score {best.score}  marge {margin:.1f}x  ({elapsed:.1f}s)")
    if level == "twijfel":
        print("      (zwakke treffer - langer opnemen of opnieuw vastleggen)")

    for other in results[1:3]:
        print(f"      ook overwogen: {other.label} (score {other.score})")


# ---------------------------------------------------------------------------
# Opdrachten
# ---------------------------------------------------------------------------
def cmd_devices(_args) -> None:
    try:
        import sounddevice as sd
    except ImportError:
        die("sounddevice ontbreekt. Installeren met:\n    pip install sounddevice")
    print(sd.query_devices())
    print(f"\nStandaard invoer: {sd.default.device[0]}")


def cmd_learn(args) -> None:
    store = Store(DB_PATH)
    print(f"Opnemen, {args.seconds:.0f} seconden. Zet de muziek nu aan.")
    audio = record(args.seconds)
    side_id = store.enroll(audio, label=args.label, keep_one_in=args.density)
    print(f"Vastgelegd als #{side_id}: {args.label} "
          f"({store.hash_count():,} hashes in totaal)")
    store.close()


def cmd_id(args) -> None:
    store = Store(DB_PATH)
    if not store.sides():
        die("De database is nog leeg. Begin met:\n"
            '    python listen.py learn "Artiest - Album kant A"')

    print(f"Luisteren, {args.seconds:.0f} seconden...")
    audio = record(args.seconds)
    t0 = time.time()
    results = store.identify(audio)
    show(results, time.time() - t0)
    store.close()


def cmd_watch(args) -> None:
    store = Store(DB_PATH)
    if not store.sides():
        die("De database is nog leeg.")

    print(f"Luisteren in blokken van {args.seconds:.0f} s. Ctrl-C stopt.\n")
    try:
        while True:
            audio = record(args.seconds, quiet=True)
            t0 = time.time()
            results = store.identify(audio)
            print(f"[{time.strftime('%H:%M:%S')}]")
            show(results, time.time() - t0)
            print()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        store.close()


def cmd_list(_args) -> None:
    store = Store(DB_PATH)
    sides = store.sides()
    if not sides:
        print("Nog niets vastgelegd.")
    else:
        for side_id, label in sides:
            print(f"  #{side_id:<4} {label}")
        print(f"\n{len(sides)} kanten, {store.hash_count():,} hashes")
    store.close()


def cmd_forget(args) -> None:
    store = Store(DB_PATH)
    store.forget(args.id)
    print(f"#{args.id} verwijderd.")
    store.close()


def cmd_selftest(_args) -> None:
    """Test de hele pijplijn zonder microfoon, zodat je weet of het aan de
    audio ligt of aan de code."""
    import os
    import tempfile

    from test_roundtrip import add_surface_noise, make_side

    print("Pijplijn testen zonder microfoon...")
    store = Store(os.path.join(tempfile.mkdtemp(), "selftest.db"))
    for i in range(3):
        music = make_side(31337 + i, seconds=60.0)
        store.enroll(add_surface_noise(music, 45.0, seed=i), label=f"Test {i}",
                     keep_one_in=1)
        if i == 1:
            excerpt = music[int(20 * SAMPLE_RATE):int(35 * SAMPLE_RATE)]

    results = store.identify(add_surface_noise(excerpt, 30.0, seed=777))
    show(results, 0.0)
    ok = results and results[0].label == "Test 1"
    print("\nPijplijn in orde." if ok else "\nPijplijn WERKT NIET.")
    store.close()
    raise SystemExit(0 if ok else 1)


def cmd_proef(args) -> None:
    """Begeleide proefsessie: precies de drie stappen die ertoe doen.

    Gebruikt een eigen database (proef.db) die telkens wordt leeggegooid, zodat
    je dit zo vaak kunt herhalen als je wil zonder je echte collectie te
    vervuilen.
    """
    import os

    print(__doc__.split("Een zinnige eerste sessie:")[0].strip().splitlines()[0])
    print("\nPROEFSESSIE\n" + "=" * 60)
    print("Je hebt nodig: je iPhone met twee verschillende nummers.")
    print("Leg hem op de afstand waarop het apparaat straks komt te staan.\n")

    if os.path.exists("proef.db"):
        os.remove("proef.db")
    store = Store("proef.db")

    # --- 0. hoort hij iets ------------------------------------------------
    print("Stap 0 - werkt de microfoon?")
    input("  Zet je muziek aan en druk op Enter... ")
    probe = record(4.0, strict=False)
    level = float(np.max(np.abs(probe)))
    db = 20 * np.log10(level) if level > 1e-6 else -99.0
    if db < -45:
        die(f"  Veel te zacht ({db:.0f} dBFS).\n"
            "  - staat de muziek aan, en hard genoeg?\n"
            "  - heeft je terminal toegang tot de microfoon?\n"
            "    Systeeminstellingen > Privacy en beveiliging > Microfoon")
    print(f"  Niveau {db:.0f} dBFS - "
          + ("prima.\n" if db > -30 else "mag wel wat harder, maar vooruit.\n"))

    # --- 1. leren ---------------------------------------------------------
    print("Stap 1 - dit nummer leren kennen")
    label = input("  Wat speelt er? (artiest - titel): ").strip() or "Onbekend nummer"
    print(f"  {args.learn_seconds:.0f} seconden opnemen. Laat het gewoon doorlopen.")
    store.enroll(record(args.learn_seconds), label=label, keep_one_in=1)
    print(f"  Vastgelegd: {store.hash_count():,} hashes.\n")

    results = []

    # --- 2. herkennen -----------------------------------------------------
    print("Stap 2 - herkent hij hetzelfde nummer terug?")
    input("  Laat het nog even doorlopen (of spoel door) en druk op Enter... ")
    hit = store.identify(record(args.id_seconds))
    show(hit, 0.0)
    level_2, margin_2 = verdict(hit)
    results.append(("herkent het nummer terug", level_2 == "zeker", level_2, margin_2, hit))
    print()

    # --- 3. niet herkennen ------------------------------------------------
    print("Stap 3 - houdt hij zijn mond bij iets anders?")
    print("  Dit is de belangrijkste stap: iets herkennen is makkelijk,")
    print("  niets herkennen wanneer het er niet is niet.")
    input("  Zet nu een HEEL ANDER nummer op en druk op Enter... ")
    miss = store.identify(record(args.id_seconds))
    show(miss, 0.0)
    level_3, margin_3 = verdict(miss)
    results.append(("zwijgt bij ander nummer", level_3 != "zeker", level_3, margin_3, miss))
    print()

    # --- uitslag ----------------------------------------------------------
    print("=" * 60)
    print("UITSLAG - stuur dit hele blok door\n")
    for name, ok, level, margin, res in results:
        score = res[0].score if res else 0
        marge = f"{margin:.1f}x" if margin != float("inf") else "geen concurrent"
        print(f"  {'GOED' if ok else 'MIS ':<5} {name:<26} "
              f"uitkomst={level:<9} score={score:<6} marge={marge}")

    print(f"\n  opnamelengte: leren {args.learn_seconds:.0f} s, "
          f"herkennen {args.id_seconds:.0f} s")
    print(f"  microfoonniveau: {db:.0f} dBFS")

    if all(ok for _, ok, _, _, _ in results):
        print("\n  Allebei goed. Het werkt op echte muziek.")
    else:
        print("\n  Nog niet goed. Wat het meestal is:")
        if not results[0][1]:
            print("   - te zacht of te ver weg; zet harder of leg de telefoon dichterbij")
            print("   - achtergrondgeluid; probeer het in een stille kamer")
            print("   - probeer --learn-seconds 90 --id-seconds 25")
        if not results[1][1]:
            print("   - hij is te goed van vertrouwen; de drempels moeten omhoog")
            print("   - dat is nuttige informatie, geen mislukking")

    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Muziekherkenning testen met de microfoon van je Mac.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="beschikbare microfoons tonen").set_defaults(
        func=cmd_devices)

    p = sub.add_parser("learn", help="opnemen en vastleggen")
    p.add_argument("label", help='bijvoorbeeld "Miles Davis - Kind of Blue A"')
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--density", type=int, default=1,
                   help="1 op N hashes bewaren (1 = alles, zoals bij testen)")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("id", help="opnemen en herkennen")
    p.add_argument("--seconds", type=float, default=15.0)
    p.set_defaults(func=cmd_id)

    p = sub.add_parser("watch", help="blijven luisteren")
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--interval", type=float, default=15.0,
                   help="pauze tussen twee blokken")
    p.set_defaults(func=cmd_watch)

    sub.add_parser("list", help="database tonen").set_defaults(func=cmd_list)

    p = sub.add_parser("forget", help="een kant verwijderen")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser("proef", help="begeleide proefsessie met je telefoon")
    p.add_argument("--learn-seconds", type=float, default=45.0)
    p.add_argument("--id-seconds", type=float, default=15.0)
    p.set_defaults(func=cmd_proef)

    sub.add_parser("selftest", help="pijplijn testen zonder microfoon"
                   ).set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
