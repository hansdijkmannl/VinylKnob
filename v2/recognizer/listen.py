#!/usr/bin/env python3
"""
Listening with your MacBook's microphone - the real test.

Everything so far has been measured on synthetic material. This is the little
tool for checking whether it also works on real music through a real
microphone, without having to order a single thing.

    python listen.py trial                guided trial session - start here
    python listen.py devices              which microphones does it see
    python listen.py learn "Name"         record 60 s and enrol it
    python listen.py id                   record 15 s: what is this?
    python listen.py watch                keep listening, as the device does
    python listen.py list                 what is in the database
    python listen.py forget 3             throw a wrong link away
    python listen.py selftest             test the pipeline without a microphone

A sensible first session:

    1. put a record or a track on
    2. `learn "Artist - Album side A"`
    3. move the track somewhere else, or just let it run on
    4. `id`  -> it should give the right name, with the right time position
    5. put something completely different on and `id` again -> it should find
       nothing

That last step is the important one. Recognising something is easy; recognising
nothing when there is nothing there is where weak fingerprinting comes apart.
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

# When do we call a hit reliable. The reasoning is in README.md.
SURE_SCORE, SURE_MARGIN = 30, 4.0
MAYBE_SCORE, MAYBE_MARGIN = 12, 2.0


def die(message: str) -> "NoReturn":  # noqa: F821
    print(f"\n{message}", file=sys.stderr)
    raise SystemExit(1)


def record(seconds: float, quiet: bool = False, strict: bool = True) -> np.ndarray:
    """Records from the default microphone and converts to the working rate."""
    try:
        import sounddevice as sd
    except ImportError:
        die("sounddevice is missing. Install it with:\n"
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
        # Show the level of the last second, so you can see something is coming
        # in before you stand there waiting twenty seconds for nothing.
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
        die("Almost no sound came in.\n"
            "  - is the music on, and loud enough?\n"
            "  - does your terminal have access to the microphone?\n"
            "    System Settings > Privacy & Security > Microphone\n"
            "  - `python listen.py devices` shows what has been picked")

    return resample_to_working_rate(audio, RECORD_RATE)


def verdict(results) -> tuple[str, float]:
    """Reliable, doubtful or unknown."""
    if not results:
        return "unknown", 0.0
    best = results[0]
    runner_up = results[1].score if len(results) > 1 else 0
    margin = best.score / runner_up if runner_up else float("inf")

    if best.score >= SURE_SCORE and margin >= SURE_MARGIN:
        return "certain", margin
    if best.score >= MAYBE_SCORE and margin >= MAYBE_MARGIN:
        return "doubtful", margin
    return "unknown", margin


def show(results, elapsed: float) -> None:
    level, margin = verdict(results)

    if level == "unknown":
        print(f"  Nothing recognised.  ({elapsed:.1f}s)")
        if results:
            best = results[0]
            print(f"    best guess was {best.label} with score {best.score}, "
                  f"margin {margin:.1f}x - too weak")
        return

    best = results[0]
    mark = "==>" if level == "certain" else " ? "
    minutes, seconds = divmod(max(best.offset_seconds, 0.0), 60)
    print(f"  {mark} {best.label}")
    print(f"      needle at {int(minutes)}:{seconds:04.1f}  "
          f"score {best.score}  margin {margin:.1f}x  ({elapsed:.1f}s)")
    if level == "doubtful":
        print("      (weak hit - record for longer, or enrol it again)")

    for other in results[1:3]:
        print(f"      also considered: {other.label} (score {other.score})")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_devices(_args) -> None:
    try:
        import sounddevice as sd
    except ImportError:
        die("sounddevice is missing. Install it with:\n    pip install sounddevice")
    print(sd.query_devices())
    print(f"\nDefault input: {sd.default.device[0]}")


def cmd_learn(args) -> None:
    store = Store(DB_PATH)
    print(f"Recording, {args.seconds:.0f} seconds. Start the music now.")
    audio = record(args.seconds)
    side_id = store.enroll(audio, label=args.label, keep_one_in=args.density)
    print(f"Enrolled as #{side_id}: {args.label} "
          f"({store.hash_count():,} hashes in total)")
    store.close()


def cmd_id(args) -> None:
    store = Store(DB_PATH)
    if not store.sides():
        die("The database is still empty. Start with:\n"
            '    python listen.py learn "Artist - Album side A"')

    print(f"Listening, {args.seconds:.0f} seconds...")
    audio = record(args.seconds)
    t0 = time.time()
    results = store.identify(audio)
    show(results, time.time() - t0)
    store.close()


def cmd_watch(args) -> None:
    store = Store(DB_PATH)
    if not store.sides():
        die("The database is still empty.")

    print(f"Listening in blocks of {args.seconds:.0f} s. Ctrl-C stops.\n")
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
        print("\nStopped.")
    finally:
        store.close()


def cmd_list(_args) -> None:
    store = Store(DB_PATH)
    sides = store.sides()
    if not sides:
        print("Nothing enrolled yet.")
    else:
        for side_id, label in sides:
            print(f"  #{side_id:<4} {label}")
        print(f"\n{len(sides)} sides, {store.hash_count():,} hashes")
    store.close()


def cmd_forget(args) -> None:
    store = Store(DB_PATH)
    store.forget(args.id)
    print(f"#{args.id} removed.")
    store.close()


def cmd_selftest(_args) -> None:
    """Tests the whole pipeline without a microphone, so you know whether it is
    the audio or the code."""
    import os
    import tempfile

    from test_roundtrip import add_surface_noise, make_side

    print("Testing the pipeline without a microphone...")
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
    print("\nPipeline in order." if ok else "\nPipeline DOES NOT WORK.")
    store.close()
    raise SystemExit(0 if ok else 1)


def cmd_trial(args) -> None:
    """Guided trial session: exactly the three steps that matter.

    Uses a database of its own (trial.db) that is emptied each time, so you can
    repeat this as often as you like without polluting your real collection.
    """
    import os

    print(__doc__.split("A sensible first session:")[0].strip().splitlines()[0])
    print("\nTRIAL SESSION\n" + "=" * 60)
    print("You need: your phone with two different tracks on it.")
    print("Put it at the distance the device will end up sitting at.\n")

    if os.path.exists("trial.db"):
        os.remove("trial.db")
    store = Store("trial.db")

    # --- 0. does it hear anything -----------------------------------------
    print("Step 0 - does the microphone work?")
    input("  Start your music and press Enter... ")
    probe = record(4.0, strict=False)
    level = float(np.max(np.abs(probe)))
    db = 20 * np.log10(level) if level > 1e-6 else -99.0
    if db < -45:
        die(f"  Far too quiet ({db:.0f} dBFS).\n"
            "  - is the music on, and loud enough?\n"
            "  - does your terminal have access to the microphone?\n"
            "    System Settings > Privacy & Security > Microphone")
    print(f"  Level {db:.0f} dBFS - "
          + ("fine.\n" if db > -30 else "could be louder, but it will do.\n"))

    # --- 1. learning ------------------------------------------------------
    print("Step 1 - getting to know this track")
    label = input("  What is playing? (artist - title): ").strip() or "Unknown track"
    print(f"  Recording {args.learn_seconds:.0f} seconds. Just let it run on.")
    store.enroll(record(args.learn_seconds), label=label, keep_one_in=1)
    print(f"  Enrolled: {store.hash_count():,} hashes.\n")

    results = []

    # --- 2. recognising ---------------------------------------------------
    print("Step 2 - does it recognise the same track again?")
    input("  Let it run on a while (or skip ahead) and press Enter... ")
    hit = store.identify(record(args.id_seconds))
    show(hit, 0.0)
    level_2, margin_2 = verdict(hit)
    results.append(("recognises the track again", level_2 == "certain", level_2, margin_2, hit))
    print()

    # --- 3. not recognising -----------------------------------------------
    print("Step 3 - does it keep quiet about something else?")
    print("  This is the most important step: recognising something is easy,")
    print("  recognising nothing when there is nothing there is not.")
    input("  Now put a COMPLETELY DIFFERENT track on and press Enter... ")
    miss = store.identify(record(args.id_seconds))
    show(miss, 0.0)
    level_3, margin_3 = verdict(miss)
    results.append(("stays quiet on another track", level_3 != "certain", level_3, margin_3, miss))
    print()

    # --- the result -------------------------------------------------------
    print("=" * 60)
    print("RESULT - send this whole block on\n")
    for name, ok, level, margin, res in results:
        score = res[0].score if res else 0
        shown = f"{margin:.1f}x" if margin != float("inf") else "no competitor"
        print(f"  {'GOOD' if ok else 'MISS':<5} {name:<30} "
              f"outcome={level:<9} score={score:<6} margin={shown}")

    print(f"\n  recording length: learning {args.learn_seconds:.0f} s, "
          f"recognising {args.id_seconds:.0f} s")
    print(f"  microphone level: {db:.0f} dBFS")

    if all(ok for _, ok, _, _, _ in results):
        print("\n  Both good. It works on real music.")
    else:
        print("\n  Not right yet. What it usually is:")
        if not results[0][1]:
            print("   - too quiet or too far away; turn it up or move the phone closer")
            print("   - background noise; try it in a quiet room")
            print("   - try --learn-seconds 90 --id-seconds 25")
        if not results[1][1]:
            print("   - it is too trusting; the thresholds need to go up")
            print("   - that is useful information, not a failure")

    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test music recognition with your Mac's microphone.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="show the available microphones").set_defaults(
        func=cmd_devices)

    p = sub.add_parser("learn", help="record and enrol")
    p.add_argument("label", help='for instance "Miles Davis - Kind of Blue A"')
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--density", type=int, default=1,
                   help="keep 1 in N hashes (1 = everything, as when testing)")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("id", help="record and recognise")
    p.add_argument("--seconds", type=float, default=15.0)
    p.set_defaults(func=cmd_id)

    p = sub.add_parser("watch", help="keep listening")
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--interval", type=float, default=15.0,
                   help="pause between two blocks")
    p.set_defaults(func=cmd_watch)

    sub.add_parser("list", help="show the database").set_defaults(func=cmd_list)

    p = sub.add_parser("forget", help="remove a side")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser("trial", help="guided trial session with your phone")
    p.add_argument("--learn-seconds", type=float, default=45.0)
    p.add_argument("--id-seconds", type=float, default=15.0)
    p.set_defaults(func=cmd_trial)

    sub.add_parser("selftest", help="test the pipeline without a microphone"
                   ).set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
